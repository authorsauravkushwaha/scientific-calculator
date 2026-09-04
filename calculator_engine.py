"""
calculator_engine.py
=====================
Author: Saurav Kushwaha

Pure-logic core of the Scientific Calculator.

This module has ZERO dependency on any GUI toolkit. It can be imported
and used from a script, a REPL, or a test suite on its own:

    >>> from calculator_engine import CalculatorEngine
    >>> calc = CalculatorEngine()
    >>> calc.evaluate("2 + 3 * 4")
    '14'
    >>> calc.evaluate("sqrt(16) + 5!")
    '124'

Design goals
------------
1. SAFE  - No use of Python's built-in eval()/exec() on user text. Every
   expression is parsed into an Abstract Syntax Tree (ast.parse) and then
   walked manually, allowing ONLY numeric literals, the four basic
   arithmetic operators, power/modulo, parentheses, and a small whitelist
   of math functions/constants. Arbitrary code execution is not possible.
2. FAST  - Expressions typed on a calculator are tiny, so parsing with
   `ast` costs microseconds. No regex backtracking traps, no recursion
   beyond the natural depth of the expression itself.
3. STABLE - Every failure mode (division by zero, log of a negative
   number, malformed syntax, absurdly large exponents, etc.) is caught
   and converted into a `CalculatorError` with a short, human-readable
   message instead of crashing the process.
"""

from __future__ import annotations

import ast
import math
import operator as op
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------
class CalculatorError(Exception):
    """Raised for any user-facing calculator problem (bad syntax, domain
    error, overflow guard, etc.). The GUI catches this and shows the
    message on-screen instead of letting the exception propagate.
    """


# --------------------------------------------------------------------------
# Safety limits (protect against pathological / hostile input freezing
# the UI or exhausting memory)
# --------------------------------------------------------------------------
_MAX_EXPONENT = 1_000_000       # abs() cap on the right-hand side of `**`
_MAX_FACTORIAL = 3_000          # n! is only computed for n <= this
_MAX_EXPR_LENGTH = 300          # characters


# --------------------------------------------------------------------------
# Whitelisted operators
# --------------------------------------------------------------------------
_BIN_OPS: Dict[type, Callable] = {
    ast.Add: op.add,
    ast.Sub: op.sub,
    ast.Mult: op.mul,
    ast.Div: op.truediv,
    ast.Mod: op.mod,
    ast.Pow: op.pow,
}

_UNARY_OPS: Dict[type, Callable] = {
    ast.UAdd: op.pos,
    ast.USub: op.neg,
}


# --------------------------------------------------------------------------
# Safe expression evaluator
# --------------------------------------------------------------------------
class SafeEvaluator:
    """
    Evaluates a tightly restricted subset of Python expression syntax.

    Allowed:
        - int / float literals
        - + - * / % ** and unary +/-
        - parentheses
        - calls to a fixed whitelist of one-argument math functions
        - the named constants: pi, e, tau, ans

    NOT allowed (and will raise CalculatorError instead of executing):
        - attribute access ("().__class__"), subscripting, slicing
        - assignments, imports, lambdas, comprehensions, f-strings
        - any function name that is not explicitly whitelisted
        - multi-argument calls

    Because evaluation walks a real `ast` tree node-by-node against an
    explicit whitelist (rather than trying to sanitize a string and then
    calling eval()), there is no string-escaping trick that can smuggle
    arbitrary code through.
    """

    def __init__(self, angle_mode_provider: Callable[[], str]):
        # angle_mode_provider() returns "DEG" or "RAD" at call time, so the
        # evaluator always reflects the calculator's *current* setting.
        self._angle_mode = angle_mode_provider

    # ---- angle helpers ---------------------------------------------------
    def _to_radians(self, x: float) -> float:
        return math.radians(x) if self._angle_mode() == "DEG" else x

    def _from_radians(self, x: float) -> float:
        return math.degrees(x) if self._angle_mode() == "DEG" else x

    # ---- domain-checked math wrappers ------------------------------------
    def _safe_sqrt(self, x: float) -> float:
        if x < 0:
            raise CalculatorError("Cannot take the square root of a negative number")
        return math.sqrt(x)

    @staticmethod
    def _safe_cbrt(x: float) -> float:
        return math.copysign(abs(x) ** (1.0 / 3.0), x)

    @staticmethod
    def _safe_log10(x: float) -> float:
        if x <= 0:
            raise CalculatorError("log(x) is only defined for x > 0")
        return math.log10(x)

    @staticmethod
    def _safe_ln(x: float) -> float:
        if x <= 0:
            raise CalculatorError("ln(x) is only defined for x > 0")
        return math.log(x)

    @staticmethod
    def _safe_log2(x: float) -> float:
        if x <= 0:
            raise CalculatorError("log2(x) is only defined for x > 0")
        return math.log2(x)

    @staticmethod
    def _safe_factorial(x: float) -> float:
        if x != int(x) or x < 0:
            raise CalculatorError("n! requires a non-negative whole number")
        if x > _MAX_FACTORIAL:
            raise CalculatorError(f"n! is limited to n <= {_MAX_FACTORIAL}")
        return float(math.factorial(int(x)))

    @staticmethod
    def _safe_asin(x: float) -> float:
        if not -1 <= x <= 1:
            raise CalculatorError("asin(x) requires -1 <= x <= 1")
        return x

    @staticmethod
    def _safe_acos(x: float) -> float:
        if not -1 <= x <= 1:
            raise CalculatorError("acos(x) requires -1 <= x <= 1")
        return x

    def _functions(self) -> Dict[str, Callable[[float], float]]:
        """Built fresh on every evaluate() call so DEG/RAD toggles apply
        immediately without needing to rebuild the evaluator itself."""
        return {
            "sin": lambda x: math.sin(self._to_radians(x)),
            "cos": lambda x: math.cos(self._to_radians(x)),
            "tan": lambda x: math.tan(self._to_radians(x)),
            "asin": lambda x: self._from_radians(math.asin(self._safe_asin(x))),
            "acos": lambda x: self._from_radians(math.acos(self._safe_acos(x))),
            "atan": lambda x: self._from_radians(math.atan(x)),
            "sinh": math.sinh,
            "cosh": math.cosh,
            "tanh": math.tanh,
            "sqrt": self._safe_sqrt,
            "cbrt": self._safe_cbrt,
            "log": self._safe_log10,
            "ln": self._safe_ln,
            "log2": self._safe_log2,
            "exp": math.exp,
            "abs": abs,
            "factorial": self._safe_factorial,
        }

    @staticmethod
    def _constants(ans: float) -> Dict[str, float]:
        return {"pi": math.pi, "e": math.e, "tau": math.tau, "ans": ans}

    # ---- public entry point ----------------------------------------------
    def evaluate(self, expression: str, ans: float = 0.0) -> float:
        if not expression or not expression.strip():
            raise CalculatorError("Nothing to calculate")
        if len(expression) > _MAX_EXPR_LENGTH:
            raise CalculatorError("Expression is too long")

        try:
            tree = ast.parse(expression, mode="eval")
        except (SyntaxError, ValueError) as exc:
            raise CalculatorError("Invalid expression") from exc

        functions = self._functions()
        constants = self._constants(ans)
        result = self._eval_node(tree.body, functions, constants)

        if isinstance(result, complex):
            raise CalculatorError("Result is not a real number")
        if isinstance(result, float) and math.isnan(result):
            raise CalculatorError("Result is undefined")
        return result

    # ---- recursive, whitelist-only AST walker -----------------------------
    def _eval_node(self, node, functions, constants):
        # Numeric literal, e.g. 3, 4.5
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise CalculatorError("Invalid literal in expression")
            return node.value

        # Binary operator, e.g. a + b, a ** b
        if isinstance(node, ast.BinOp):
            op_func = _BIN_OPS.get(type(node.op))
            if op_func is None:
                raise CalculatorError("Unsupported operator")
            left = self._eval_node(node.left, functions, constants)
            right = self._eval_node(node.right, functions, constants)
            if isinstance(node.op, ast.Pow) and abs(right) > _MAX_EXPONENT:
                raise CalculatorError("Exponent too large")
            try:
                return op_func(left, right)
            except ZeroDivisionError as exc:
                raise CalculatorError("Cannot divide by zero") from exc
            except OverflowError as exc:
                raise CalculatorError("Result is too large to display") from exc

        # Unary operator, e.g. -a, +a
        if isinstance(node, ast.UnaryOp):
            op_func = _UNARY_OPS.get(type(node.op))
            if op_func is None:
                raise CalculatorError("Unsupported operator")
            return op_func(self._eval_node(node.operand, functions, constants))

        # Function call, e.g. sin(30) -- name must be in the whitelist
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in functions:
                raise CalculatorError("Unknown function")
            if node.keywords or len(node.args) != 1:
                raise CalculatorError(f"'{node.func.id}(...)' takes exactly one argument")
            arg = self._eval_node(node.args[0], functions, constants)
            try:
                return functions[node.func.id](arg)
            except CalculatorError:
                raise
            except ValueError as exc:
                raise CalculatorError(str(exc) or "Math domain error") from exc
            except OverflowError as exc:
                raise CalculatorError("Result is too large to display") from exc

        # Named constant, e.g. pi, e, ans
        if isinstance(node, ast.Name):
            if node.id in constants:
                return constants[node.id]
            raise CalculatorError(f"Unknown symbol '{node.id}'")

        # Anything else (attribute access, subscripts, lambdas, comprehensions,
        # string/byte literals, comparisons, boolean ops, ...) is rejected.
        raise CalculatorError("Unsupported expression syntax")


# --------------------------------------------------------------------------
# Number formatting
# --------------------------------------------------------------------------
def format_number(value) -> str:
    """Render a numeric result the way a calculator display should look:
    no ugly floating point noise, scientific notation for very large or
    very small magnitudes, no unnecessary trailing zeros.
    """
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)

    if not isinstance(value, float):
        raise CalculatorError("Unsupported result type")

    if math.isnan(value):
        return "Undefined"
    if math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    if value == 0:
        return "0"

    abs_val = abs(value)
    if abs_val >= 1e15 or abs_val < 1e-9:
        text = f"{value:.10e}"
        mantissa, exponent = text.split("e")
        mantissa = mantissa.rstrip("0").rstrip(".")
        exp_int = int(exponent)
        sign = "+" if exp_int >= 0 else ""
        return f"{mantissa}e{sign}{exp_int}"

    text = f"{value:.10f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-") else "0"


# --------------------------------------------------------------------------
# History
# --------------------------------------------------------------------------
@dataclass
class HistoryEntry:
    expression: str
    result: str
    timestamp: float = field(default_factory=time.time)


# --------------------------------------------------------------------------
# Calculator engine — the stateful object the GUI talks to
# --------------------------------------------------------------------------
class CalculatorEngine:
    """
    Holds calculator state (angle mode, memory register, history,
    last answer) and turns raw text the user has typed/clicked into a
    final, display-ready string via `evaluate()`.

    This class knows nothing about tkinter and can be reused in a CLI
    tool, a web backend, or a test suite.
    """

    MAX_HISTORY = 200

    def __init__(self) -> None:
        self.angle_mode: str = "DEG"        # "DEG" or "RAD"
        self.memory: float = 0.0
        self.last_answer: float = 0.0
        self.history: List[HistoryEntry] = []
        self._evaluator = SafeEvaluator(lambda: self.angle_mode)

    # ---- settings ----------------------------------------------------
    def toggle_angle_mode(self) -> str:
        self.angle_mode = "RAD" if self.angle_mode == "DEG" else "DEG"
        return self.angle_mode

    # ---- expression preprocessing --------------------------------------
    @staticmethod
    def _normalize_symbols(expr: str) -> str:
        """Turn calculator-friendly symbols into valid Python syntax."""
        replacements = {
            "×": "*",
            "÷": "/",
            "−": "-",   # unicode minus, in case of copy/paste
            "π": "pi",
            "√": "sqrt",
        }
        for old, new in replacements.items():
            expr = expr.replace(old, new)
        return expr

    @staticmethod
    def _auto_close_parens(expr: str) -> str:
        """If the user hits '=' with unclosed '(' still open, close them
        automatically instead of raising a syntax error. Small usability
        touch that noticeably reduces annoying error messages."""
        open_count = expr.count("(") - expr.count(")")
        if open_count > 0:
            expr += ")" * open_count
        return expr

    @staticmethod
    def _expand_factorials(expr: str) -> str:
        """Rewrite postfix factorial notation, e.g. '5!' or '(2+3)!',
        into function-call form 'factorial(5)' the evaluator understands.
        Runs left to right, repeatedly, so '5!+2!' and even nested cases
        like '(3!)!' are supported.
        """
        while "!" in expr:
            idx = expr.index("!")
            if idx == 0:
                raise CalculatorError("Invalid syntax near '!'")
            j = idx - 1
            if expr[j] == ")":
                depth = 0
                k = j
                while k >= 0:
                    if expr[k] == ")":
                        depth += 1
                    elif expr[k] == "(":
                        depth -= 1
                        if depth == 0:
                            break
                    k -= 1
                if depth != 0:
                    raise CalculatorError("Mismatched parentheses before '!'")
                start = k
            else:
                k = j
                while k >= 0 and (expr[k].isdigit() or expr[k] == "."):
                    k -= 1
                start = k + 1
                if start > j:
                    raise CalculatorError("Invalid syntax near '!'")
            token = expr[start:idx]
            expr = expr[:start] + "factorial(" + token + ")" + expr[idx + 1:]
        return expr

    def preprocess(self, expr: str) -> str:
        expr = self._normalize_symbols(expr)
        expr = self._auto_close_parens(expr)
        expr = self._expand_factorials(expr)
        return expr

    # ---- public API --------------------------------------------------
    def peek(self, raw_expression: str) -> float:
        """Evaluate an expression WITHOUT recording it to history or
        updating `last_answer`. Used for live-preview-as-you-type in the
        GUI, where every keystroke triggers a (possibly incomplete,
        possibly invalid) evaluation attempt.
        """
        expr = self.preprocess(raw_expression)
        return self._evaluator.evaluate(expr, ans=self.last_answer)

    def evaluate(self, raw_expression: str) -> str:
        """Evaluate a raw expression exactly as built by the UI/keyboard.
        Returns a display-ready string. Raises CalculatorError on any
        problem -- callers should catch this and show it to the user
        without letting the app crash.
        """
        expr = self.preprocess(raw_expression)
        result = self._evaluator.evaluate(expr, ans=self.last_answer)
        formatted = format_number(result)
        self.last_answer = float(result)
        self._add_history(raw_expression, formatted)
        return formatted

    def _add_history(self, expr: str, result: str) -> None:
        self.history.append(HistoryEntry(expr, result))
        if len(self.history) > self.MAX_HISTORY:
            self.history.pop(0)

    def clear_history(self) -> None:
        self.history.clear()

    # ---- memory register -----------------------------------------------
    def memory_store(self, value: float) -> None:
        self.memory = value

    def memory_clear(self) -> None:
        self.memory = 0.0

    def memory_add(self, value: float) -> None:
        self.memory += value

    def memory_subtract(self, value: float) -> None:
        self.memory -= value
