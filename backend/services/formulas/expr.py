"""Safe Excel-like formula language for user indicators (Russian).

    ДОЛЯ([ГЦБ]; [Итого ЧДУ])
    [ГЦБ] / [Итого ЧДУ] * 100
    ЕСЛИ([Дюрация портфеля] > [Коридор дюрации: до]; 1; 0)

* fields — names in square brackets, from the catalog (``fields.py``);
* numbers — 1 000 000 or 0,5 or 0.5;
* operators — + − * / ^, comparisons > < >= <= = <>, parentheses;
* functions — arguments separated by «;» as in Russian Excel.

The formula is parsed into a small tree and evaluated by this module only —
there is no ``eval``; nothing but the listed operations can run.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union


class FormulaError(ValueError):
    def __init__(self, message: str, position: Optional[int] = None):
        super().__init__(message)
        self.message = message
        self.position = position


# ───────────────────────────── functions ─────────────────────────────

def _share(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b in (None, 0):
        return None
    return a / b * 100.0


def _round(x: Optional[float], n: Optional[float] = 0) -> Optional[float]:
    return None if x is None else round(x, int(n or 0))


def _if(cond, a, b):
    return a if cond else b


def _nums(args: Sequence[Optional[float]]) -> List[float]:
    return [a for a in args if a is not None]


FUNCTIONS: Dict[str, Tuple[Callable[..., Any], int, Optional[int], str, str]] = {
    # name: (impl, min args, max args, signature, help)
    "ДОЛЯ": (_share, 2, 2, "ДОЛЯ(часть; целое)", "Доля в процентах: часть ÷ целое × 100; если целое 0 — пусто"),
    "ЕСЛИ": (_if, 3, 3, "ЕСЛИ(условие; если да; если нет)", "Выбор значения по условию, например [Дюрация портфеля] > 3"),
    "МИН": (lambda *a: min(_nums(a)) if _nums(a) else None, 1, None, "МИН(a; b; …)", "Наименьшее из значений"),
    "МАКС": (lambda *a: max(_nums(a)) if _nums(a) else None, 1, None, "МАКС(a; b; …)", "Наибольшее из значений"),
    "СУММ": (lambda *a: sum(_nums(a)), 1, None, "СУММ(a; b; …)", "Сумма значений"),
    "СРЗНАЧ": (lambda *a: (sum(_nums(a)) / len(_nums(a))) if _nums(a) else None, 1, None, "СРЗНАЧ(a; b; …)",
               "Среднее значение"),
    "ОКРУГЛ": (_round, 1, 2, "ОКРУГЛ(значение; знаков)", "Округление до заданного числа знаков"),
    "АБС": (lambda x: None if x is None else abs(x), 1, 1, "АБС(значение)", "Модуль числа (без знака)"),
}
ALIASES = {"IF": "ЕСЛИ", "MIN": "МИН", "MAX": "МАКС", "SUM": "СУММ", "ROUND": "ОКРУГЛ", "ABS": "АБС",
           "AVERAGE": "СРЗНАЧ", "СУММА": "СУММ", "ОКРУГЛИТЬ": "ОКРУГЛ"}


# ───────────────────────────── tokens ─────────────────────────────

@dataclass
class Tok:
    kind: str      # num field name op lp rp sep end
    value: Any
    pos: int


_TOKEN_RE = re.compile(r"""
    (?P<ws>\s+)
  | (?P<field>\[[^\]]*\]?)
  | (?P<num>\d[\d  ]*(?:[.,]\d+)?)
  | (?P<op><=|>=|<>|!=|[+\-*/^<>=×÷−])
  | (?P<lp>\()
  | (?P<rp>\))
  | (?P<sep>;)
  | (?P<name>[A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё_0-9]*)
""", re.VERBOSE)


def tokenize(text: str) -> List[Tok]:
    out: List[Tok] = []
    i = 0
    src = text.lstrip("=")
    shift = len(text) - len(src)
    while i < len(src):
        m = _TOKEN_RE.match(src, i)
        if not m:
            ch = src[i]
            hint = " — аргументы функций разделяются «;»" if ch == "," else ""
            raise FormulaError(f"Непонятный символ «{ch}»{hint}", i + shift)
        kind = m.lastgroup
        value = m.group(kind)
        pos = i + shift
        i = m.end()
        if kind == "ws":
            continue
        if kind == "field":
            if not value.endswith("]"):
                raise FormulaError("Не закрыта квадратная скобка у поля", pos)
            out.append(Tok("field", value[1:-1].strip(), pos))
        elif kind == "num":
            clean = value.replace(" ", "").replace(" ", "").replace(",", ".")
            out.append(Tok("num", float(clean), pos))
        elif kind == "op":
            out.append(Tok("op", {"×": "*", "÷": "/", "−": "-", "!=": "<>"}.get(value, value), pos))
        else:
            out.append(Tok(kind, value, pos))
    out.append(Tok("end", None, len(text)))
    return out


# ───────────────────────────── parser ─────────────────────────────

Node = Union[Tuple[str, Any], Tuple[str, Any, Any], Tuple[str, Any, List[Any]]]


class _Parser:
    def __init__(self, tokens: List[Tok], field_names: Dict[str, str]):
        self.t = tokens
        self.i = 0
        self.fields = field_names       # lower-case alias → canonical name

    def peek(self) -> Tok:
        return self.t[self.i]

    def take(self) -> Tok:
        tok = self.t[self.i]
        self.i += 1
        return tok

    def parse(self):
        node = self.comparison()
        tok = self.peek()
        if tok.kind != "end":
            raise FormulaError(self._unexpected(tok), tok.pos)
        return node

    def _unexpected(self, tok: Tok) -> str:
        if tok.kind == "rp":
            return "Лишняя закрывающая скобка"
        if tok.kind == "sep":
            return "Символ «;» допустим только между аргументами функции"
        if tok.kind in ("num", "field", "name", "lp"):
            return "Пропущен знак действия (+ − × ÷) между значениями"
        return f"Неожиданное «{tok.value}»"

    def comparison(self):
        left = self.additive()
        tok = self.peek()
        if tok.kind == "op" and tok.value in ("<", ">", "<=", ">=", "=", "<>"):
            self.take()
            right = self.additive()
            return ("cmp", tok.value, [left, right])
        return left

    def additive(self):
        node = self.term()
        while self.peek().kind == "op" and self.peek().value in ("+", "-"):
            op = self.take().value
            node = ("bin", op, [node, self.term()])
        return node

    def term(self):
        node = self.unary()
        while self.peek().kind == "op" and self.peek().value in ("*", "/"):
            op = self.take().value
            node = ("bin", op, [node, self.unary()])
        return node

    def unary(self):
        tok = self.peek()
        if tok.kind == "op" and tok.value in ("-", "+"):
            self.take()
            inner = self.unary()
            return ("neg", None, [inner]) if tok.value == "-" else inner
        return self.power()

    def power(self):
        base = self.primary()
        if self.peek().kind == "op" and self.peek().value == "^":
            self.take()
            return ("bin", "^", [base, self.unary()])
        return base

    def primary(self):
        tok = self.take()
        if tok.kind == "num":
            return ("num", tok.value)
        if tok.kind == "field":
            key = tok.value.lower().replace("ё", "е")
            if key not in self.fields:
                raise FormulaError(f"Неизвестное поле «{tok.value}» — выберите поле из списка", tok.pos)
            return ("field", self.fields[key])
        if tok.kind == "lp":
            node = self.comparison()
            if self.take().kind != "rp":
                raise FormulaError("Не закрыта круглая скобка", tok.pos)
            return node
        if tok.kind == "name":
            name = tok.value.upper().replace("Ё", "Е")
            name = ALIASES.get(name, name)
            if name not in FUNCTIONS:
                if self.peek().kind != "lp":
                    raise FormulaError(f"«{tok.value}»: поля пишутся в квадратных скобках, например [{tok.value}]",
                                       tok.pos)
                raise FormulaError(f"Неизвестная функция «{tok.value}»", tok.pos)
            if self.take().kind != "lp":
                raise FormulaError(f"После {name} нужна открывающая скобка", tok.pos)
            args = []
            if self.peek().kind != "rp":
                args.append(self.comparison())
                while self.peek().kind == "sep":
                    self.take()
                    args.append(self.comparison())
            close = self.take()
            if close.kind != "rp":
                raise FormulaError(f"Не закрыта скобка функции {name} (аргументы разделяются «;»)", tok.pos)
            _, mn, mx, sig, _ = FUNCTIONS[name]
            if len(args) < mn or (mx is not None and len(args) > mx):
                raise FormulaError(f"{name}: неверное число аргументов, нужно {sig}", tok.pos)
            return ("fn", name, args)
        if tok.kind == "end":
            raise FormulaError("Формула обрывается — после знака действия нужно значение", tok.pos)
        raise FormulaError(self._unexpected(tok) if tok.kind != "op" else
                           f"Два знака подряд или знак без значения: «{tok.value}»", tok.pos)


def parse(text: str, field_names: Sequence[str]) -> Any:
    if not (text or "").strip():
        raise FormulaError("Формула пустая", 0)
    names = {n.lower().replace("ё", "е"): n for n in field_names}
    return _Parser(tokenize(text), names).parse()


def fields_used(node) -> List[str]:
    out: List[str] = []

    def walk(n):
        if n[0] == "field":
            if n[1] not in out:
                out.append(n[1])
        elif len(n) == 3:
            for a in n[2]:
                walk(a)
    walk(node)
    return out


# ───────────────────────────── evaluation ─────────────────────────────

class EvalError(ValueError):
    pass


def evaluate(node, ctx: Dict[str, Optional[float]]) -> Optional[float]:
    kind = node[0]
    if kind == "num":
        return node[1]
    if kind == "field":
        return ctx.get(node[1])
    if kind == "neg":
        v = evaluate(node[2][0], ctx)
        return None if v is None else -v
    if kind == "bin":
        a = evaluate(node[2][0], ctx)
        b = evaluate(node[2][1], ctx)
        if a is None or b is None:
            return None
        op = node[1]
        if op == "+":
            return a + b
        if op == "-":
            return a - b
        if op == "*":
            return a * b
        if op == "/":
            if b == 0:
                raise EvalError("деление на ноль")
            return a / b
        if op == "^":
            try:
                r = a ** b
            except (OverflowError, ZeroDivisionError):
                raise EvalError("слишком большое число") from None
            if isinstance(r, complex) or (isinstance(r, float) and (math.isnan(r) or math.isinf(r))):
                raise EvalError("недопустимая степень")
            return r
    if kind == "cmp":
        a = evaluate(node[2][0], ctx)
        b = evaluate(node[2][1], ctx)
        if a is None or b is None:
            return None
        op = node[1]
        return float({"<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b,
                      "=": abs(a - b) < 1e-9, "<>": abs(a - b) >= 1e-9}[op])
    if kind == "fn":
        impl = FUNCTIONS[node[1]][0]
        if node[1] == "ЕСЛИ":
            cond = evaluate(node[2][0], ctx)
            return evaluate(node[2][1] if cond else node[2][2], ctx)
        args = [evaluate(a, ctx) for a in node[2]]
        return impl(*args)
    raise EvalError(f"неизвестный элемент {kind}")


# ───────────────────────────── explanation ─────────────────────────────

def fmt_number(v: Optional[float], digits: int = 2) -> str:
    if v is None:
        return "пусто"
    if abs(v - round(v)) < 1e-9 and abs(v) >= 1:
        digits = 0
    s = f"{v:,.{digits}f}".replace(",", " ").replace(".", ",")
    return s


_PREC = {"cmp": 1, "+": 2, "-": 2, "*": 3, "/": 3, "^": 4}
_SHOW = {"*": "×", "/": "÷", "-": "−", "<>": "≠", "<=": "≤", ">=": "≥"}


def render(node, ctx: Optional[Dict[str, Optional[float]]] = None, parent: int = 0) -> str:
    """The formula as text; with ``ctx`` the fields are replaced by their values."""
    kind = node[0]
    if kind == "num":
        return fmt_number(node[1], 6).rstrip("0").rstrip(",") if node[1] % 1 else fmt_number(node[1], 0)
    if kind == "field":
        return f"[{node[1]}]" if ctx is None else fmt_number(ctx.get(node[1]))
    if kind == "neg":
        return "−" + render(node[2][0], ctx, 5)
    if kind in ("bin", "cmp"):
        p = _PREC["cmp" if kind == "cmp" else node[1]]
        text = f"{render(node[2][0], ctx, p)} {_SHOW.get(node[1], node[1])} {render(node[2][1], ctx, p + 1)}"
        return f"({text})" if p < parent else text
    if kind == "fn":
        return f"{node[1]}(" + "; ".join(render(a, ctx) for a in node[2]) + ")"
    return "?"
