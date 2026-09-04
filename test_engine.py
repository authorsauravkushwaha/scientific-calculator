"""
test_engine.py
================
Author: Saurav Kushwaha

Unit tests for calculator_engine.py. These tests need no display / no
tkinter, so they run anywhere, including CI pipelines like GitHub
Actions.

Run with:
    python -m unittest test_engine.py -v
or, if pytest is installed:
    pytest test_engine.py -v
"""

import math
import unittest

from calculator_engine import CalculatorEngine, CalculatorError, format_number


class TestBasicArithmetic(unittest.TestCase):
    def setUp(self):
        self.calc = CalculatorEngine()

    def test_addition(self):
        self.assertEqual(self.calc.evaluate("2 + 3"), "5")

    def test_subtraction(self):
        self.assertEqual(self.calc.evaluate("10 - 4"), "6")

    def test_multiplication(self):
        self.assertEqual(self.calc.evaluate("6 * 7"), "42")

    def test_division(self):
        self.assertEqual(self.calc.evaluate("9 / 2"), "4.5")

    def test_order_of_operations(self):
        self.assertEqual(self.calc.evaluate("2 + 3 * 4"), "14")

    def test_parentheses(self):
        self.assertEqual(self.calc.evaluate("(2 + 3) * 4"), "20")

    def test_auto_close_parens(self):
        # user forgot the closing ')'
        self.assertEqual(self.calc.evaluate("(2 + 3"), "5")

    def test_power(self):
        self.assertEqual(self.calc.evaluate("2 ** 10"), "1024")

    def test_modulo(self):
        self.assertEqual(self.calc.evaluate("10 % 3"), "1")

    def test_unary_minus(self):
        self.assertEqual(self.calc.evaluate("-5 + 2"), "-3")

    def test_division_by_zero(self):
        with self.assertRaises(CalculatorError):
            self.calc.evaluate("1 / 0")


class TestScientificFunctions(unittest.TestCase):
    def setUp(self):
        self.calc = CalculatorEngine()

    def test_sqrt(self):
        self.assertEqual(self.calc.evaluate("sqrt(16)"), "4")

    def test_sqrt_negative_raises(self):
        with self.assertRaises(CalculatorError):
            self.calc.evaluate("sqrt(-4)")

    def test_factorial(self):
        self.assertEqual(self.calc.evaluate("5!"), "120")

    def test_factorial_of_expression(self):
        self.assertEqual(self.calc.evaluate("(2+3)!"), "120")

    def test_factorial_negative_raises(self):
        with self.assertRaises(CalculatorError):
            self.calc.evaluate("(-3)!")

    def test_ln(self):
        result = float(self.calc.evaluate("ln(e)"))
        self.assertAlmostEqual(result, 1.0, places=8)

    def test_log10(self):
        self.assertEqual(self.calc.evaluate("log(1000)"), "3")

    def test_trig_degrees_default(self):
        # DEG is the default mode
        result = float(self.calc.evaluate("sin(90)"))
        self.assertAlmostEqual(result, 1.0, places=8)

    def test_trig_radians_mode(self):
        self.calc.toggle_angle_mode()  # -> RAD
        result = float(self.calc.evaluate("sin(pi/2)"))
        self.assertAlmostEqual(result, 1.0, places=8)

    def test_constants(self):
        result = float(self.calc.evaluate("pi"))
        self.assertAlmostEqual(result, math.pi, places=10)

    def test_ans(self):
        self.calc.evaluate("2 + 2")
        self.assertEqual(self.calc.evaluate("ans * 10"), "40")


class TestSecurity(unittest.TestCase):
    """Confirms the evaluator behaves like a calculator, not a Python
    interpreter -- these should all be rejected, never executed."""

    def setUp(self):
        self.calc = CalculatorEngine()

    def test_rejects_attribute_access(self):
        with self.assertRaises(CalculatorError):
            self.calc.evaluate("().__class__")

    def test_rejects_import(self):
        with self.assertRaises(CalculatorError):
            self.calc.evaluate("__import__('os')")

    def test_rejects_unknown_function(self):
        with self.assertRaises(CalculatorError):
            self.calc.evaluate("open('file.txt')")

    def test_rejects_string_literals(self):
        with self.assertRaises(CalculatorError):
            self.calc.evaluate("'hello'")

    def test_rejects_unknown_name(self):
        with self.assertRaises(CalculatorError):
            self.calc.evaluate("secret_variable")

    def test_rejects_huge_exponent(self):
        with self.assertRaises(CalculatorError):
            self.calc.evaluate("9 ** 99999999")


class TestMemory(unittest.TestCase):
    def setUp(self):
        self.calc = CalculatorEngine()

    def test_memory_add_and_recall(self):
        self.calc.memory_add(5)
        self.calc.memory_add(2.5)
        self.assertEqual(self.calc.memory, 7.5)

    def test_memory_clear(self):
        self.calc.memory_add(10)
        self.calc.memory_clear()
        self.assertEqual(self.calc.memory, 0.0)

    def test_memory_subtract(self):
        self.calc.memory_add(10)
        self.calc.memory_subtract(3)
        self.assertEqual(self.calc.memory, 7)


class TestHistory(unittest.TestCase):
    def setUp(self):
        self.calc = CalculatorEngine()

    def test_history_records_entries(self):
        self.calc.evaluate("1 + 1")
        self.calc.evaluate("2 + 2")
        self.assertEqual(len(self.calc.history), 2)
        self.assertEqual(self.calc.history[-1].result, "4")

    def test_clear_history(self):
        self.calc.evaluate("1 + 1")
        self.calc.clear_history()
        self.assertEqual(len(self.calc.history), 0)

    def test_history_cap(self):
        for i in range(CalculatorEngine.MAX_HISTORY + 10):
            self.calc.evaluate(f"{i} + 1")
        self.assertEqual(len(self.calc.history), CalculatorEngine.MAX_HISTORY)


class TestNumberFormatting(unittest.TestCase):
    def test_integer_like_float(self):
        self.assertEqual(format_number(4.0), "4")

    def test_trailing_zero_stripped(self):
        self.assertEqual(format_number(2.5000000000), "2.5")

    def test_scientific_notation_large(self):
        self.assertTrue("e" in format_number(1.23e20))

    def test_scientific_notation_small(self):
        self.assertTrue("e" in format_number(1.23e-15))

    def test_zero(self):
        self.assertEqual(format_number(0.0), "0")

    def test_infinity(self):
        self.assertEqual(format_number(float("inf")), "Infinity")


if __name__ == "__main__":
    unittest.main(verbosity=2)
