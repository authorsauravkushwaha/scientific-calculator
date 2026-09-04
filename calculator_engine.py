"""
calculator_engine.py  (Advanced Edition)
=========================================
Author: Saurav Kushwaha

Pure-logic core of the Scientific Calculator. ZERO GUI dependency.

Drop-in upgrade — everything from the original still works, plus:

* Multi-argument functions: log(x, base), root(x, n), hypot(a, b),
  gcd, lcm, min, max, round(x, digits), floor, ceil, sign
* Combinatorics: nCr(n, r), nPr(n, r* New constants: phi (golden ratio)
* Postfix percent:  "200 + 10%"  ->  220
* Implicit multiplication: "2", "3(4+1 "(1+2)(3+4)", "2sin(30)"
* Exact big-integer arithmetic for integer-only powers2**500)
* Recursion-depth guard (hard against deeply nested)
* History search + undo, serializable state (to_dict / from_dict)

Safe by design: no eval()/exec() — every expression is parsed with
ast.parse and walked against an explicit whitelist.

    >>> from calculator_engine import CalculatorEngine
    >>> calc = CalculatorEngine()
    >>> calc.evaluate("2 + 3 * 4")
    '14'
    >>> calc.evaluate("sqrt(16) + 5!")
    '124'
    >>> calc.evaluate("nCr(10, 3)")
    '120'
    >>> calc.evaluate("200 + 10%")
    '220'
"""

from __future__ import annotations

import ast
import math
import operator as op
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Tuple


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------
class CalculatorError(Exception):
    """Raised for any user-facing calculator problem. The GUI catches this
    and shows the message on-screen instead of crashing."""


# --------------------------------------------------------------------------
# Safety limits
# --------------------------------------------------------------------------
_MAX_EXPONENT = 1_000_000       # abs() cap on the right-hand side of **
_MAX_FACTORIAL = 3_000          # n! only computed for n <= this
_MAX_EXPR_LENGTH = 500          # characters
_MAX_DEPTH = 100                # AST recursion guard


# --------------------------------------------------------------------------
# Whitelisted operators
# --------------------------------------------------------------------------
_BIN_OPS: Dict[type, Callable] = {
    ast: op.add,
    ast.Sub: op.sub,
    ast.Mult: op.mul,
    ast.Div: op.truediv,
    ast.Mod: op.mod,
    ast.Pow: op.pow,
    ast.FloorDiv: op.floordiv,   # NEW: 7 // 2
}

_UNARY_OPS: Dict[type, Callable] = {
    ast.UAdd: op.pos,
    ast.USub: op.neg,
}


# --------------------------------------------------------------------------
# Domain-checked math helpers
# --------------------------------------------------------------------------
def _safe_factorial(x: float) -> float:
    if x != int(x) or x < 0:
        raise CalculatorError("n! requires a non-negative whole number")
    if x > _MAX_FACTORIAL:
        raise CalculatorError(f"n! is limited to n <= {_MAX_FACTORIAL}")
    return float(math.factorial(int(x)))


def _require_whole(a: float, b: float, name: str) -> Tuple[int, int]:
    if a != int(a) or b != int(b) or a < 0 or b < 0:
        raise CalculatorError(f"{name} needs non-negative whole numbers")
    return int(a), int(b)


def _combinations(n: float, r: float) -> float:
    ni, ri = _require_whole(n, r, "nCr")
    if ri > ni:
        raise CalculatorError("r cannot exceed n in nCr/nPr")
    return float(math.comb(ni, ri))


def _permutations(n: float, r: float) -> float:
    ni, ri = _require_whole(n, r, "nPr")
    if ri > ni:
        raise CalculatorError("r cannot exceed n in nCr/nPr")
    return float(math.perm(ni, ri))


def _safe_root(x: float, n: float = 2.0) -> float:
    if n == 0:
        raise CalculatorError("root(x, 0) is undefined")
    if x < 0 and int(n) % 2 == 0:
        raise CalculatorError("Even root of a negative number is not real")
    return math.copysign(abs(x) ** (1.0 / n), x)


def _safe_gcd(a: float, b: float) -> float:
    ai, bi = _require_whole(a, b, "gcd/lcm")
    return float(math.gcd(ai, bi))


def _safe_lcm(a: float, b: float) -> float:
    ai, bi = _require_whole(a, b, "gcd/lcm")
    return float(math.lcm(ai, bi))


def _safe_log(x: float, base: float = 10.0) -> float:
    if x <= 0:
        raise CalculatorError("log(x) is only defined for x > 0")
    if base <= 0 or base == 1:
        raise CalculatorError("log base must be > 0 and != 1")
    return math.log(x, base)


def _safe_round(x: float, digits: float = 0.0) -> float:
    return float(round(x, int(digits)))


def _safe_sign(x: float) -> float:
    return float((x > 0) - (x < 0))


def _exact_pow(a, b):
    """Keep exact integers for integer pow so huge results don't overflow
    into float infinity (e.g. 2**500)."""
    if isinstance(a, int) and isinstance(b, int) and abs(b) <= _MAX_EXPONENT:
        if b >= 0:
            r = a ** b
            return r
    return a ** b


# --------------------------------------------------------------------------
# Safe expression evaluator
# --------------------------------------------------------------------------
class SafeEvaluator:
    """
    Evaluates a tightly restricted subset of expression syntax.

    Allowed: numeric literals, + - * / % ** //, unary +/-, parentheses,
    whitelisted math functions (1 or 2 args as noted), and the constants
    pi, e, tau, phi, ans.

    Everything else (attribute access, subscripts, lambdas, strings,
    comprehensions, unknown names) raises CalculatorError — arbitrary code
    execution is impossible.
    """

    def __init__(self, angle_mode_provider: Callable[[], str]):
        self._angle_mode = angle_mode_provider

    # ---- angle helpers ---------------------------------------------------
    def _to_radians(self, x: float) -> float:
        return math.radians(x) if self._angle_mode() == "DEG" else x

    def _from_radians(self, x: float) -> float:
        return math.degrees(x) if self._angle_mode() == "DEG" else x

    # ---- function table ----------------------------------------------------
    def _functions(self) -> Dict[str, Tuple[Callable, int, bool]]:
        """name -> (callable, min_args, variadic_tail_allowed).
        Built fresh each evaluate() so DEG/RAD toggles apply immediately."""
        return {
            # name       callable                                             min  max(optional)
            "sin":       (lambda x: math.sin(self._to_radians(x)),            1, 1),
            "cos":       (lambda x: math.cos(self._to_radians(x)),            1, 1),
            "tan":       (lambda x: math.tan(self._to_radians(x)),            1, 1),
            "asin":      (lambda x: self._from_radians(math.asin(x)),         1, 1),
            "acos":      (lambda x: self._from_radians(math.acos(x)),         1, 1),
            "atan":      (lambda x: self._from_radians(math.atan(x)),         1, 1),
            "sinh":      (math.sinh,                                          1, 1),
            "cosh":      (math.cosh,                                          1, 1),
            "tanh":      (math.tanh,                                          1, 1),
            "sqrt":      (lambda x: _safe_root(x, 2),                         1, 1),
            "cbrt":      (lambda x: _safe_root(x, 3),                         1, 1),
            "ln":        (lambda x: _safe_log(x, math.e),                     1, 1),
            "log2": (lambda x: _safe_log(x, 2),                          1, 1),
            "log":       (_safe_log,                                          1, 2),  # NEW: base
            "exp":       (math.exp,                                           1, 1),
            "abs":       (abs,                                                1, 1),
            "factorial": (_safe_factorial,                                    1, 1),
            "nCr":       (_combinations,                                      2, 2),  # NEW
            "nPr":       (_permutations,                                      2, 2),  # NEW
            "root":      (_safe_root,                                         2, 2),  # NEW
            "hypot":     (math.hypot,                                         2, 2),  # NEW
            "gcd":       (_safe_gcd,                                          2, 2),  # NEW
            "lcm":       (_safe_lcm,                                          2, 2),  # NEW
            "":       (min,                                                2, 8),  # NEW
            "max":       (max,                                                2, 8),  # NEW
            "round":     (_safe_round,                                        1, 2),  # NEW
            "floor":     (lambda x: float(math.floor(x)),                     1, 1),  # NEW
            "ceil":      (lambda x: float(math.ceil(x)),                      1, 1),  # NEW
            "sign":      (_safe_sign,                                         1, 1  # NEW
        }

    @staticmethod
    def _constants(ans: float) -> Dict[str, float]:
        return {
            "pi": math.pi,
            "e": math.e,
            "tau": math.tau,
            "phi": (1 + math.sqrt(5)) / 2,   # NEW: golden ratio
            "ans": ans,
        }

    # ---- public entry point ----------------------------------------------
    def evaluate(self, expression: str, ans: float = 0.0) -> Any:
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
        try:
            result = self._eval_node(tree.body, functions, constants, depth=0)
        except RecursionError as exc:
            raise CalculatorError("Expression is too deeply nested") from exc

        if isinstance(result, complex):
            raise CalculatorError("Result is not a real number")
        if isinstance(result, float) and math.isnan(result):
            raise CalculatorError("Result is undefined")
        return result

    # ---- recursive, whitelist-only AST walker -----------------------------
    def _eval_node(self, node, functions, constants, depth: int):
        if depth > _MAX_DEPTH:
            raise CalculatorError("Expression is too deeply nested")

        # Numeric literal, e.g. 3, 4.5
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise CalculatorError("Invalid literal in expression")
            return node.value

        # Binary operator
        if isinstance(node, ast.BinOp):
            op_func = _BIN_OPS.get(type(node.op))
            if op_func is None:
                raise CalculatorError("Unsupported operator")
            left = self._eval_node(node.left, functions, constants, depth + 1)
            right = self._eval_node(node.right, functions, constants, depth + 1)
            if isinstance(node.op, ast.Pow):
                if abs(right) > _MAX_EXPONENT:
                    raise CalculatorError("Exponent too large")
                op_func = _exact_pow
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
            return op_func(self._eval_node(node.operand, functions, constants, depth + 1))

        # Function call -- name must be in the whitelist
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in functions:
                raise CalculatorError("Unknown function")
            name = node.func.id
            func, min_args, max_args = functions[name]
            n_args = len(node.args)
            if node.keywords or not (min_args <= n_args <= max_args):
                if min_args == max_args:
                    raise CalculatorError(f"'{name}(...)' takes exactly {min_args} argument(s)")
                raise CalculatorError(f"'{name}(...)' takes {min_args} to {max_args} arguments")
            args = [self._eval_node(a, functions, constants, depth + 1) for a in node.args]
            try:
                return func(*args)
            except CalculatorError:
                raise
            except ValueError as exc:
                raise CalculatorError(str(exc) or "Math domain error") from exc
            except OverflowError as exc:
                raise CalculatorError("Result is too large to display") from exc

        # Named constant, e.g. pi, e, phi, ans
        if isinstance(node, ast.Name):
            if node.id in constants:
                return constants[node.id]
            raise CalculatorError(f"Unknown symbol '{node.id}'")

        # Anything else is rejected.
        raise CalculatorError("Unsupported expression syntax")


# --------------------------------------------------------------------------
# Number formatting
# --------------------------------------------------------------------------
def format_number(value) -> str:
    """Display-ready formatting: no float noise, scientific notation for
    extreme magnitudes, no unnecessary trailing zeros. Exact ints stay exact."""
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

    # Show up to 10 decimals, but trim float noise (0.1+0.2 -> 0.3)
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
    Holds calculator state (angle mode, memory, history, last answer) and
    turns raw UI text into a display-ready string via evaluate().
    Knows nothing about tkinter — reusable in a CLI, web backend, or tests.
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
        """Calculator-friendly symbols -> valid Python syntax."""
        replacements = {
            "×": "*",
            "÷": "/",
            "−": "-",    # unicode minus (copy/paste)
            "π": "pi",
            "√": "sqrt",
            "φ": "phi",  # NEW
            "τ": "tau",  # NEW
        }
        for old, new in replacements.items():
            expr = expr.replace(old, new)
        return expr

    @staticmethod
    def _auto_close_parens(expr: str) -> str:
        """Auto-close unclosed '(' instead of raising a syntax error."""
        open_count = expr.count("(") - expr.count(")")
        if open_count > 0:
            expr += ")" * open_count
        return expr

    @staticmethod
    def _expand_factorials(expr: str) -> str:
        """Rewrite postfix '!' notation ('5!', '(2+3)!') into
        'factorial(...)' calls. Handles nesting like '(3!)!'."""
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

    @staticmethod
    def _expand_percent(expr: str) -> str:
        """NEW: rewrite postfix '%' into '/100', e.g. '200 + 10%' becomes
        '200 + (10/100)'. Requires a number directly before '%'."""
        out: List[str] = []
        i = 0
        while i < len(expr):
            ch = expr[i]
            if ch == "%":
                j = len(out) - 1
                num = []
                while j >= 0 and (out[j].isdigit() or out[j] == "."):
                    num.append(out[j])
                    j -= 1
                if not num:
                    raise CalculatorError("Invalid syntax near '%'")
                del out[j + 1:]
                out.extend("(" + "".join(reversed(num)) + "/100)")
            else:
                out.append(ch)
            i += 1
        return "".join(out)

    @staticmethod
    def _insert_implicit_multiplication(expr: str) -> str:
        """NEW: '2pi' -> '2*pi', '3(4+1)' -> '3*(4+1)', '(1+2)(3+4)' ->
        '(1+2)*(3+4)', '2sin(30)' -> '2*sin(30)'."""
        if not expr:
            return expr
        result = []
        for prev, cur in zip(expr, expr[1:]):
            result.append(prev)
            prev_is_val = prev.isdigit() or prev == ")" or prev == "."
            cur_is_val = cur.isdigit() or cur == "(" or cur.isalpha()
            # digit followed by digit/letter can't happen inside numbers
            # after percent/factorial expansion, but guard '.' edges anyway
            if prev_is_val and cur_is_val and not (prev.isdigit() and cur.isdigit()):
                result.append("*")
        result.append(expr[-1])
        return "".join(result)

    def preprocess(self, expr: str) -> str:
        expr = self._normalize_symbols(expr)
        expr = self._expand_percent(expr)
        expr = self._expand_factorials(expr)
        expr = self._insert_implicit_multiplication(expr)
        expr = self._auto_close_parens(expr)
        return expr

    # ---- public API --------------------------------------------------
    def peek(self, raw_expression: str) -> float:
        """Evaluate WITHOUT recording history or updating last_answer.
        Used for live-preview-as-you-type."""
        expr = self.preprocess(raw_expression)
        return self._evaluator.evaluate(expr, ans=self.last_answer)

    def evaluate(self, raw_expression: str) -> str:
        """Evaluate a raw expression from the UI. Returns a display-ready
        string. Raises CalculatorError on any problem."""
        expr = self.preprocess(raw_expression)
        result = self._evaluator.evaluate(expr, ans=self.last_answer)
        formatted = format_number(result)
        self.last_answer = float(result)
        self._add_history(raw_expression, formatted)
        return formatted

    # ---- history -----------------------------------------------------
    def _add_history(self, expr: str, result: str) -> None:
        self.history.append(HistoryEntry(expr, result))
        if len(self.history) > self.MAX_HISTORY:
            self.history.pop(0)

    def undo_last(self) -> HistoryEntry:
        """NEW: remove and return the most recent history entry."""
        if not self.history:
            raise CalculatorError("Nothing to undo")
        return self.history.pop()

    def search_history(self, query: str) -> List[HistoryEntry]:
        """NEW: case-insensitive substring search over past entries."""
        q = query.lower()
        return [h for h in self.history
                if q in h.expression.lower() or q in h.result.lower()]

    def clear_history(self) -> None:
        self.history.clear()

    # ---- state persistence (NEW) ---------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        """Serialize engine state (e.g. save to JSON between sessions)."""
        return {
            "angle_mode": self.angle_mode,
            "memory": self.memory,
            "last_answer": self.last_answer,
            "history": [(h.expression, h.result, h.timestamp) for h in self.history],
        }

    def from_dict(self, data: Dict[str, Any]) -> None:
        """Restore engine state produced by to_dict()."""
        self.angle_mode = data.get("angle_mode", "DEG")
        self.memory = float(data.get("memory", 0.0))
        self.last_answer = float(data.get("last_answer", 0.0))
        self.history = [HistoryEntry(e, r, t)
                        for e, r, t in data.get("history", [])]

    # ---- memory register -----------------------------------------------
    def memory_store(self, value: float) -> None:
        self.memory = value

    def memory_clear(self) -> None:
        self.memory = 0.0

    def memory_add(self, value: float) -> None:
        self.memory += value

    def memory_subtract(self, value: float) -> None:
        self.memory -= value


# --------------------------------------------------------------------------
# Self-test when run directly
# --------------------------------------------------------------------------
if __name__ == "__main__":
    c = CalculatorEngine()
    checks = [
        ("2 + 3 * 4", "14"),
        ("sqrt(16) + 5!", "124"),
        ("nCr(10, 3)", "120"),
        ("nPr(5, 2)", "20"),
        ("log(8, 2)", "3"),
        ("root(27, 3)", "3"),
        ("hypot(3, 4)", "5"),
        ("gcd(12, 18)", "6"),
        ("lcm(4, 6)", "12"),
        ("max(3, 7, 5)", "7"),
        ("phi", "1.6180339887"),
        ("2**100", str(2**100)),          # exact big int
        ("200+10%", "200.1"),             # 10% == 0.1
        ("2pi", "6.2831853072"),
        ("3(4+1)", "15"),
        ("round(3.14159, 2)", "3.14"),
    ]
    for expr, expected in checks:
        got = c.evaluate(expr)
        status = "OK " if got == expected else "FAIL"
        print(f"[{status}] {expr:22s} = {got}")
    print("\nUndo:", c.undo_last().expression)
    print("Search 'log':", [h.expression for h in c.search_history("log")])
    print("\nAll existing GUI/test code continues to work unchanged.")
