#!/usr/bin/env python3
"""
scientific_calculator.py
==========================
Author: Saurav Kushwaha

A fast, stable, good-looking scientific calculator built with nothing
but the Python standard library (tkinter + math). No pip install, no
external packages -- clone the repo and run it anywhere Python 3.8+ is
installed (Windows, macOS, Linux).

Run it with:

    python scientific_calculator.py

Features
--------
- All standard arithmetic + parentheses, with automatic paren closing
- Scientific functions: sin, cos, tan, asin, acos, atan, sinh, cosh,
  tanh, log, ln, log2, sqrt, cbrt, exp, x^y, x^2, x^3, 1/x, n!, |x|
- DEG / RAD toggle for trigonometric functions
- Constants: pi, e
- Memory register: MC, MR, M+, M-, MS
- Full calculation history panel (click any past entry to reuse it)
- "Ans" -- reuse the previous result in a new expression
- Live result preview as you type
- Full keyboard support (typing, Enter, Backspace, Escape, etc.)
- Every error (division by zero, bad syntax, domain errors, ...) is
  caught and shown politely -- the app never crashes on bad input
- No use of eval()/exec() on user input -- expressions are evaluated
  through a whitelisted AST walker (see calculator_engine.py)

This file only contains the presentation layer (tkinter widgets and
event handlers). All calculation logic lives in calculator_engine.py
so it can be tested and reused independently of the GUI.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont

from calculator_engine import CalculatorEngine, CalculatorError, format_number

APP_TITLE = "Scientific Calculator"
APP_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Color palette (dark theme)
# ---------------------------------------------------------------------------
COLOR_BG = "#1e1f29"
COLOR_PANEL = "#262836"
COLOR_DISPLAY_BG = "#12131a"
COLOR_TEXT = "#f5f6fa"
COLOR_TEXT_DIM = "#8b8fa3"
COLOR_ACCENT = "#7c5cff"
COLOR_ACCENT_HOVER = "#9376ff"
COLOR_DIGIT = "#33354a"
COLOR_DIGIT_HOVER = "#40435c"
COLOR_FUNC = "#2b2d3f"
COLOR_FUNC_HOVER = "#383b52"
COLOR_OP = "#4d3fb0"
COLOR_OP_HOVER = "#5f4fd6"
COLOR_DANGER = "#e15c5c"
COLOR_DANGER_HOVER = "#ea7a7a"
COLOR_EQUALS = "#00c896"
COLOR_EQUALS_HOVER = "#22e0b0"


class RoundedButton(tk.Button):
    """A tkinter Button pre-styled to fit the calculator's flat, dark
    theme, with a simple hover effect. Kept as a small subclass so all
    button creation in the grid stays one-liner-simple.
    """

    def __init__(self, master, text, command, bg, hover, fg=COLOR_TEXT,
                 font=None, **kwargs):
        super().__init__(
            master,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            activebackground=hover,
            activeforeground=fg,
            relief="flat",
            bd=0,
            highlightthickness=0,
            cursor="hand2",
            font=font,
            **kwargs,
        )
        self._bg = bg
        self._hover = hover
        self.bind("<Enter>", lambda e: self.config(bg=self._hover))
        self.bind("<Leave>", lambda e: self.config(bg=self._bg))


class ScientificCalculatorApp:
    """Owns the tkinter root window and all widgets. Delegates every
    actual calculation to a `CalculatorEngine` instance."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.engine = CalculatorEngine()
        self.expression = tk.StringVar(value="")
        self.history_visible = False

        self._configure_window()
        self._build_fonts()
        self._build_layout()
        self._bind_keyboard()

        self._refresh_status()
        self._refresh_preview()

    # ------------------------------------------------------------------
    # Window / layout setup
    # ------------------------------------------------------------------
    def _configure_window(self) -> None:
        self.root.title(f"{APP_TITLE} v{APP_VERSION}")
        self.root.configure(bg=COLOR_BG)
        self.root.geometry("380x660")
        self.root.minsize(360, 620)

    def _build_fonts(self) -> None:
        families = set(tkfont.families())
        preferred = "Segoe UI" if "Segoe UI" in families else "Helvetica"
        mono = "Consolas" if "Consolas" in families else "Courier New"

        self.font_display = tkfont.Font(family=mono, size=30, weight="bold")
        self.font_preview = tkfont.Font(family=mono, size=13)
        self.font_status = tkfont.Font(family=preferred, size=10)
        self.font_button = tkfont.Font(family=preferred, size=13)
        self.font_button_small = tkfont.Font(family=preferred, size=11)

    def _build_layout(self) -> None:
        self.main_frame = tk.Frame(self.root, bg=COLOR_BG)
        self.main_frame.pack(side="left", fill="both", expand=True)

        self._build_status_bar(self.main_frame)
        self._build_display(self.main_frame)
        self._build_button_grid(self.main_frame)
        self._build_history_panel()  # hidden until toggled

    def _build_status_bar(self, parent: tk.Frame) -> None:
        bar = tk.Frame(parent, bg=COLOR_BG)
        bar.pack(fill="x", padx=14, pady=(12, 0))

        self.angle_label = tk.Label(
            bar, text="", bg=COLOR_BG, fg=COLOR_ACCENT, font=self.font_status
        )
        self.angle_label.pack(side="left")

        self.memory_label = tk.Label(
            bar, text="", bg=COLOR_BG, fg=COLOR_TEXT_DIM, font=self.font_status
        )
        self.memory_label.pack(side="left", padx=(10, 0))

        self.history_toggle_btn = tk.Label(
            bar, text="History ▾", bg=COLOR_BG, fg=COLOR_TEXT_DIM,
            font=self.font_status, cursor="hand2",
        )
        self.history_toggle_btn.pack(side="right")
        self.history_toggle_btn.bind("<Button-1>", lambda e: self.toggle_history())

    def _build_display(self, parent: tk.Frame) -> None:
        frame = tk.Frame(parent, bg=COLOR_DISPLAY_BG)
        frame.pack(fill="x", padx=14, pady=10)

        self.preview_label = tk.Label(
            frame, text=" ", anchor="e", bg=COLOR_DISPLAY_BG,
            fg=COLOR_TEXT_DIM, font=self.font_preview,
        )
        self.preview_label.pack(fill="x", padx=14, pady=(10, 0))

        self.display_entry = tk.Entry(
            frame, textvariable=self.expression, justify="right",
            bg=COLOR_DISPLAY_BG, fg=COLOR_TEXT, insertbackground=COLOR_TEXT,
            relief="flat", font=self.font_display, bd=0,
            highlightthickness=0, width=1,
        )
        self.display_entry.pack(fill="x", padx=10, pady=(0, 14), ipady=6)
        self.display_entry.focus_set()
        self.expression.trace_add("write", lambda *a: self._refresh_preview())

    def _build_button_grid(self, parent: tk.Frame) -> None:
        grid = tk.Frame(parent, bg=COLOR_BG)
        grid.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        for col in range(5):
            grid.grid_columnconfigure(col, weight=1, uniform="col")
        for row in range(7):
            grid.grid_rowconfigure(row, weight=1)

        # (label, callback, color, hover, column_span, font)
        Row = list  # readability alias

        layout = [
            [("DEG", self.toggle_angle, COLOR_FUNC, COLOR_FUNC_HOVER),
             ("(", lambda: self.insert_text("("), COLOR_FUNC, COLOR_FUNC_HOVER),
             (")", lambda: self.insert_text(")"), COLOR_FUNC, COLOR_FUNC_HOVER),
             ("MC", self.memory_clear, COLOR_FUNC, COLOR_FUNC_HOVER),
             ("MR", self.memory_recall, COLOR_FUNC, COLOR_FUNC_HOVER)],

            [("sin", lambda: self.insert_text("sin("), COLOR_FUNC, COLOR_FUNC_HOVER),
             ("cos", lambda: self.insert_text("cos("), COLOR_FUNC, COLOR_FUNC_HOVER),
             ("tan", lambda: self.insert_text("tan("), COLOR_FUNC, COLOR_FUNC_HOVER),
             ("M+", self.memory_add, COLOR_FUNC, COLOR_FUNC_HOVER),
             ("M-", self.memory_subtract, COLOR_FUNC, COLOR_FUNC_HOVER)],

            [("ln", lambda: self.insert_text("ln("), COLOR_FUNC, COLOR_FUNC_HOVER),
             ("log", lambda: self.insert_text("log("), COLOR_FUNC, COLOR_FUNC_HOVER),
             ("x!", lambda: self.insert_text("!"), COLOR_FUNC, COLOR_FUNC_HOVER),
             ("π", lambda: self.insert_text("pi"), COLOR_FUNC, COLOR_FUNC_HOVER),
             ("e", lambda: self.insert_text("e"), COLOR_FUNC, COLOR_FUNC_HOVER)],

            [("x²", lambda: self.insert_text("**2"), COLOR_FUNC, COLOR_FUNC_HOVER),
             ("x^y", lambda: self.insert_text("**"), COLOR_FUNC, COLOR_FUNC_HOVER),
             ("√", lambda: self.insert_text("sqrt("), COLOR_FUNC, COLOR_FUNC_HOVER),
             ("1/x", self.reciprocal, COLOR_FUNC, COLOR_FUNC_HOVER),
             ("%", lambda: self.insert_text("%"), COLOR_FUNC, COLOR_FUNC_HOVER)],

            [("C", self.clear_all, COLOR_DANGER, COLOR_DANGER_HOVER),
             ("⌫", self.backspace, COLOR_DANGER, COLOR_DANGER_HOVER),
             ("7", lambda: self.insert_text("7"), COLOR_DIGIT, COLOR_DIGIT_HOVER),
             ("8", lambda: self.insert_text("8"), COLOR_DIGIT, COLOR_DIGIT_HOVER),
             ("9", lambda: self.insert_text("9"), COLOR_DIGIT, COLOR_DIGIT_HOVER)],

            [("Ans", lambda: self.insert_text("ans"), COLOR_FUNC, COLOR_FUNC_HOVER),
             ("÷", lambda: self.insert_text("/"), COLOR_OP, COLOR_OP_HOVER),
             ("4", lambda: self.insert_text("4"), COLOR_DIGIT, COLOR_DIGIT_HOVER),
             ("5", lambda: self.insert_text("5"), COLOR_DIGIT, COLOR_DIGIT_HOVER),
             ("6", lambda: self.insert_text("6"), COLOR_DIGIT, COLOR_DIGIT_HOVER)],

            [("+/-", self.toggle_sign, COLOR_FUNC, COLOR_FUNC_HOVER),
             ("×", lambda: self.insert_text("*"), COLOR_OP, COLOR_OP_HOVER),
             ("1", lambda: self.insert_text("1"), COLOR_DIGIT, COLOR_DIGIT_HOVER),
             ("2", lambda: self.insert_text("2"), COLOR_DIGIT, COLOR_DIGIT_HOVER),
             ("3", lambda: self.insert_text("3"), COLOR_DIGIT, COLOR_DIGIT_HOVER)],
        ]

        for r, row in enumerate(layout):
            for c, (label, cmd, color, hover) in enumerate(row):
                btn = RoundedButton(grid, label, cmd, color, hover,
                                     font=self.font_button)
                btn.grid(row=r, column=c, sticky="nsew", padx=4, pady=4)

        # Bottom row: 0, ., -, +, =  -- laid out separately for a wider "0"
        bottom = tk.Frame(parent, bg=COLOR_BG)
        bottom.pack(fill="x", padx=10, pady=(0, 12))
        for i in range(5):
            bottom.grid_columnconfigure(i, weight=1, uniform="bottomcol")

        RoundedButton(bottom, "0", lambda: self.insert_text("0"),
                      COLOR_DIGIT, COLOR_DIGIT_HOVER, font=self.font_button
                      ).grid(row=0, column=0, columnspan=2, sticky="nsew", padx=4, pady=4)
        RoundedButton(bottom, ".", lambda: self.insert_text("."),
                      COLOR_DIGIT, COLOR_DIGIT_HOVER, font=self.font_button
                      ).grid(row=0, column=2, sticky="nsew", padx=4, pady=4)
        RoundedButton(bottom, "−", lambda: self.insert_text("-"),
                      COLOR_OP, COLOR_OP_HOVER, font=self.font_button
                      ).grid(row=0, column=3, sticky="nsew", padx=4, pady=4)
        RoundedButton(bottom, "+", lambda: self.insert_text("+"),
                      COLOR_OP, COLOR_OP_HOVER, font=self.font_button
                      ).grid(row=0, column=4, sticky="nsew", padx=4, pady=4)

        equals_row = tk.Frame(parent, bg=COLOR_BG)
        equals_row.pack(fill="x", padx=10, pady=(0, 14))
        equals_row.grid_columnconfigure(0, weight=1)
        RoundedButton(equals_row, "=", self.calculate,
                      COLOR_EQUALS, COLOR_EQUALS_HOVER, fg="#0b1f18",
                      font=self.font_button).grid(row=0, column=0, sticky="nsew",
                                                   ipady=6, padx=4)

    def _build_history_panel(self) -> None:
        self.history_frame = tk.Frame(self.root, bg=COLOR_PANEL, width=300)
        # Without this, the frame would auto-shrink to fit its children's
        # natural size and ignore the width= hint above.
        self.history_frame.pack_propagate(False)

        header = tk.Frame(self.history_frame, bg=COLOR_PANEL)
        header.pack(fill="x", padx=10, pady=(10, 4))
        tk.Label(header, text="History", bg=COLOR_PANEL, fg=COLOR_TEXT,
                 font=self.font_button).pack(side="left")
        clear_lbl = tk.Label(header, text="Clear", bg=COLOR_PANEL,
                              fg=COLOR_DANGER, font=self.font_status,
                              cursor="hand2")
        clear_lbl.pack(side="right")
        clear_lbl.bind("<Button-1>", lambda e: self.clear_history())

        list_frame = tk.Frame(self.history_frame, bg=COLOR_PANEL)
        list_frame.pack(fill="both", expand=True, padx=6, pady=6)

        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side="right", fill="y")

        self.history_listbox = tk.Listbox(
            list_frame, bg=COLOR_PANEL, fg=COLOR_TEXT,
            selectbackground=COLOR_ACCENT, activestyle="none",
            relief="flat", highlightthickness=0, font=self.font_button_small,
            yscrollcommand=scrollbar.set,
        )
        self.history_listbox.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.history_listbox.yview)
        self.history_listbox.bind("<Double-Button-1>", self._use_history_item)

    # ------------------------------------------------------------------
    # Keyboard support
    # ------------------------------------------------------------------
    def _bind_keyboard(self) -> None:
        bindings = {
            "<Return>": lambda e: self.calculate(),
            "<KP_Enter>": lambda e: self.calculate(),
            "<BackSpace>": lambda e: self.backspace(),
            "<Escape>": lambda e: self.clear_all(),
            "<Delete>": lambda e: self.clear_all(),
        }
        for seq, handler in bindings.items():
            self.root.bind(seq, handler)

        # '^' is not a Python power operator (it's bitwise XOR), so remap
        # the key users instinctively reach for into '**'.
        def _caret_to_power(event):
            self.insert_text("**")
            return "break"

        self.root.bind("<KeyPress-asciicircum>", _caret_to_power)

        # All normal digit/operator typing goes straight into the Entry
        # widget itself since it's a regular editable Entry -- no extra
        # binding needed for 0-9, +, -, *, /, ., (, ).

    # ------------------------------------------------------------------
    # Button actions
    # ------------------------------------------------------------------
    def insert_text(self, text: str) -> None:
        pos = self.display_entry.index(tk.INSERT)
        current = self.expression.get()
        new_value = current[:pos] + text + current[pos:]
        self.expression.set(new_value)
        self.display_entry.icursor(pos + len(text))
        self.display_entry.focus_set()

    def backspace(self) -> None:
        pos = self.display_entry.index(tk.INSERT)
        current = self.expression.get()
        if pos == 0:
            return
        new_value = current[:pos - 1] + current[pos:]
        self.expression.set(new_value)
        self.display_entry.icursor(pos - 1)

    def clear_all(self) -> None:
        self.expression.set("")
        self.preview_label.config(text=" ")

    def toggle_sign(self) -> None:
        current = self.expression.get().strip()
        if not current:
            return
        if current.startswith("-("):
            self.expression.set(current[2:-1] if current.endswith(")") else current[1:])
        elif current.startswith("-"):
            self.expression.set(current[1:])
        else:
            self.expression.set(f"-({current})")
        self.display_entry.icursor(tk.END)
        self.display_entry.xview_moveto(1.0)

    def reciprocal(self) -> None:
        current = self.expression.get().strip()
        if not current:
            return
        self.expression.set(f"1/({current})")
        self.display_entry.icursor(tk.END)
        self.display_entry.xview_moveto(1.0)

    def toggle_angle(self) -> None:
        mode = self.engine.toggle_angle_mode()
        self._refresh_status()
        self._refresh_preview()

    def memory_recall(self) -> None:
        # Insert the memory value as a literal number.
        self.insert_text(_number_to_literal(self.engine.memory))

    def memory_clear(self) -> None:
        self.engine.memory_clear()
        self._refresh_status()

    def memory_add(self) -> None:
        value = self._current_numeric_value()
        if value is not None:
            self.engine.memory_add(value)
            self._refresh_status()

    def memory_subtract(self) -> None:
        value = self._current_numeric_value()
        if value is not None:
            self.engine.memory_subtract(value)
            self._refresh_status()

    def calculate(self) -> None:
        raw = self.expression.get()
        try:
            result = self.engine.evaluate(raw)
        except CalculatorError as exc:
            self._show_error(str(exc))
            return
        except Exception as exc:  # last-resort safety net -- never crash
            self._show_error(f"Unexpected error: {exc}")
            return

        self.expression.set(result)
        self.display_entry.icursor(tk.END)
        self.display_entry.xview_moveto(1.0)
        self._refresh_history_list()
        self._refresh_preview()

    def clear_history(self) -> None:
        self.engine.clear_history()
        self._refresh_history_list()

    def toggle_history(self) -> None:
        self.history_visible = not self.history_visible
        if self.history_visible:
            self.history_frame.pack(side="right", fill="y")
            self.root.geometry("680x660")
            self.history_toggle_btn.config(text="History ▴")
        else:
            self.history_frame.pack_forget()
            self.root.geometry("380x660")
            self.history_toggle_btn.config(text="History ▾")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _current_numeric_value(self):
        raw = self.expression.get()
        if not raw.strip():
            return self.engine.last_answer
        try:
            return self.engine.peek(raw)
        except CalculatorError:
            return None

    def _refresh_preview(self) -> None:
        raw = self.expression.get()
        if not raw.strip():
            self.preview_label.config(text=" ")
            return
        try:
            value = self.engine.peek(raw)
            self.preview_label.config(text=format_number(value), fg=COLOR_TEXT_DIM)
        except CalculatorError:
            self.preview_label.config(text=" ")

    def _refresh_status(self) -> None:
        self.angle_label.config(text=self.engine.angle_mode)
        self.memory_label.config(
            text="M" if self.engine.memory != 0 else ""
        )

    def _refresh_history_list(self) -> None:
        self.history_listbox.delete(0, tk.END)
        for entry in reversed(self.engine.history):
            self.history_listbox.insert(tk.END, f"{entry.expression} = {entry.result}")

    def _use_history_item(self, event) -> None:
        selection = self.history_listbox.curselection()
        if not selection:
            return
        index = selection[0]
        entry = list(reversed(self.engine.history))[index]
        self.expression.set(entry.result)
        self.display_entry.icursor(tk.END)
        self.display_entry.xview_moveto(1.0)

    def _show_error(self, message: str) -> None:
        self.preview_label.config(text=message, fg=COLOR_DANGER)
        self.root.after(2200, lambda: self._refresh_preview())


def _number_to_literal(value: float) -> str:
    """Render a float/int as a clean literal safe to splice back into an
    expression (e.g. memory recall inserting '12' instead of '12.0')."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def main() -> None:
    root = tk.Tk()
    ScientificCalculatorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
