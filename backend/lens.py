"""Visual-search helpers: math/homework solving and translation.

The camera itself runs entirely in the browser. These endpoints handle the two
pieces that are better done on the server:

  * /api/solve      – safe symbolic math from text recognized in a photo
  * /api/translate  – translate recognized text for the Lens-style panel
"""

import asyncio
import re

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

router = APIRouter()

SOLVE_TIMEOUT_SECONDS = 8.0
TRANSLATE_TIMEOUT_SECONDS = 10.0
TRANSLATE_MAX_CHARS = 5000

_UNICODE_MATH = {
    "×": "*", "÷": "/", "−": "-", "–": "-", "—": "-",
    "√": "sqrt", "π": "pi", "∞": "oo",
    "²": "**2", "³": "**3", "⁴": "**4", "⁵": "**5",
    "½": "(1/2)", "¼": "(1/4)", "¾": "(3/4)",
    "≤": "<=", "≥": ">=", "≠": "!=",
}
_MATH_CHARS = re.compile(r"^[0-9A-Za-z_+\-*/^().=<>!% ]+$")
_MATH_HINT = re.compile(r"[=+\-*/^]")
_INSTRUCTION = re.compile(
    r"^(?:q(?:uestion)?\s*\d+\s*[\).:\-]?\s*"
    r"|solve(?:\s+(?:the\s+)?system(?:\s+of\s+equations)?)?"
    r"(?:\s+for\s+[A-Za-z]\s*)?[:\-]?\s*"
    r"|calculate\s*|evaluate\s*|compute\s*|simplify\s*"
    r"|what\s+is\s*|what's\s*|find\s*|differentiate\s*"
    r"|integrate\s*|derivative\s+of\s*|integral\s+of\s*)",
    re.I,
)


class SolveRequest(BaseModel):
    expression: str = Field(..., min_length=1, max_length=800)


class TranslateRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=TRANSLATE_MAX_CHARS)
    target: str = Field("en", min_length=2, max_length=12)
    source: str = Field("auto", min_length=2, max_length=12)


def _normalize_math(text: str) -> str:
    text = (text or "").strip()
    for old, new in _UNICODE_MATH.items():
        text = text.replace(old, new)
    text = text.replace("\u00a0", " ")
    # "15% of 80" and "15 percent of 80" are common homework questions.
    text = re.sub(
        r"(\d+(?:\.\d+)?)\s*(?:%|percent)\s+of\s+(\d+(?:\.\d+)?)",
        r"(\1/100)*\2",
        text,
        flags=re.I,
    )
    # Collapse spaces and tabs but keep line breaks: equation systems may be
    # written on separate lines.
    text = re.sub(r"[^\S\n]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def _candidate_lines(text: str) -> list[str]:
    """Turn OCR-ish text into plausible math expressions, best candidate first."""
    raw = _normalize_math(text)
    candidates: list[str] = []

    def add(value: str) -> None:
        value = value.strip().strip("?.!,:;")
        value = _INSTRUCTION.sub("", value).strip().strip("?.!,:;")
        value = re.sub(r"\s*(?:=|equals?)\s*", " = ", value)
        value = re.sub(r"\s+", " ", value).strip()
        if value and value not in candidates:
            candidates.append(value)

    add(raw)
    for line in re.split(r"[\n;]+", raw):
        add(line)

    # "What is 2 + 2?" style sentences: keep the math-looking middle section.
    for match in re.finditer(r"[0-9A-Za-z().+\-*/^=<>! ]{3,}", raw):
        add(match.group(0))

    return candidates


def _parse_expr(text: str):
    import sympy as sp
    from sympy.parsing.sympy_parser import (
        convert_xor,
        implicit_multiplication_application,
        parse_expr,
        standard_transformations,
    )

    local = {
        "sqrt": sp.sqrt, "sin": sp.sin, "cos": sp.cos, "tan": sp.tan,
        "asin": sp.asin, "acos": sp.acos, "atan": sp.atan,
        "log": sp.log, "ln": sp.log, "exp": sp.exp, "Abs": sp.Abs,
        "factorial": sp.factorial, "pi": sp.pi, "E": sp.E,
        "oo": sp.oo,
    }
    global_dict = {
        "__builtins__": {},
        "Symbol": sp.Symbol,
        "Integer": sp.Integer,
        "Float": sp.Float,
        "Rational": sp.Rational,
        "Function": sp.Function,
        **local,
    }
    transformations = standard_transformations + (
        implicit_multiplication_application,
        convert_xor,
    )
    return parse_expr(
        text,
        local_dict=local,
        global_dict=global_dict,
        transformations=transformations,
        evaluate=True,
    )


def _valid_math(text: str) -> bool:
    text = text.strip()
    if len(text) < 2 or len(text) > 500:
        return False
    if "__" in text or not _MATH_CHARS.match(text):
        return False
    # Block attribute access (``x.real``, ``f.func``) while allowing decimals.
    if re.search(r"[A-Za-z_)]\s*\.", text):
        return False
    if not re.search(r"\d", text):
        return False
    # Reject ordinary sentences: long letter runs without math operators.
    letters = re.sub(r"[^A-Za-z]", "", text)
    if len(letters) > 18 and not _MATH_HINT.search(text):
        return False
    return bool(_MATH_HINT.search(text))


def sp_text(value) -> str:
    try:
        import sympy as sp
        simplified = sp.simplify(value)
        if simplified in (sp.zoo, sp.nan):
            return "undefined"
        return str(simplified)
    except Exception:
        return str(value)


def _format_number(value) -> str:
    import sympy as sp

    if value in (sp.zoo, sp.nan):
        return "undefined"
    if value.has(sp.zoo, sp.nan):
        return str(value)
    if value.is_Integer:
        return str(value)
    if value.is_Rational and value.q != 1:
        return f"{value.p}/{value.q}"
    if value.is_real:
        try:
            number = float(value)
            if number.is_integer():
                return str(int(number))
            return f"{number:.10g}"
        except (TypeError, ValueError, OverflowError):
            pass
    return str(value)


def _solve_system(raw: str, original: str) -> dict | None:
    """Solve two or more equations separated by semicolons/newlines."""
    import sympy as sp

    parts = []
    for part in re.split(r"[\n;]+", raw):
        cleaned = _INSTRUCTION.sub("", part).strip()
        if cleaned:
            parts.append(cleaned)
    if len(parts) < 2 or not all("=" in part for part in parts):
        return None

    equations = []
    for part in parts:
        if not _valid_math(part):
            return None
        sides = part.split("=")
        if len(sides) != 2:
            return None
        equations.append(sp.Eq(_parse_expr(sides[0]), _parse_expr(sides[1])))

    symbols = sorted(
        set().union(*(equation.free_symbols for equation in equations)),
        key=lambda symbol: symbol.name,
    )
    if not symbols:
        return None

    solutions = sp.solve(equations, symbols, dict=True)
    if not solutions:
        return None

    rendered = []
    for solution in solutions[:6]:
        parts_out = [
            f"{symbol.name} = {sp_text(solution[symbol])}"
            for symbol in symbols
            if solution.get(symbol) is not None
        ]
        if parts_out:
            rendered.append(", ".join(parts_out))

    return {
        "solved": True,
        "kind": "system",
        "input": original.strip(),
        "normalized": " ; ".join(parts),
        "solution": " | ".join(rendered),
        "solutions": rendered,
        "steps": [
            "Write the system as " + "; ".join(parts) + ".",
            "Solve the equations together.",
            "Solution: " + " | ".join(rendered),
        ],
    }


def _solve_sync(expression: str) -> dict:
    import sympy as sp

    raw = _normalize_math(expression)
    lowered_raw = raw.lower()

    system = _solve_system(raw, expression)
    if system:
        return system

    for candidate in _candidate_lines(raw):
        if not _valid_math(candidate):
            continue

        try:
            if "=" in candidate:
                sides = candidate.split("=")
                if len(sides) != 2:
                    continue
                left, right = _parse_expr(sides[0]), _parse_expr(sides[1])
                equation = sp.Eq(left, right)
                symbols = sorted(
                    equation.free_symbols, key=lambda symbol: symbol.name
                )
                if not symbols:
                    if sp.simplify(left - right) == 0:
                        return {
                            "solved": True,
                            "kind": "identity",
                            "input": expression.strip(),
                            "normalized": candidate,
                            "solution": "This is true for every value.",
                            "solutions": [],
                            "steps": [f"{sp_text(left)} = {sp_text(right)}"],
                        }
                    continue

                solution_set = sp.solve(equation, symbols, dict=True)
                if not solution_set:
                    continue
                rendered = []
                for solution in solution_set[:6]:
                    for symbol in symbols:
                        value = solution.get(symbol)
                        if value is not None:
                            rendered.append(f"{symbol.name} = {sp_text(value)}")

                moved = sp.simplify(left - right)
                factored = sp.factor(moved)
                steps = [
                    f"Start with {sp_text(left)} = {sp_text(right)}.",
                    f"Bring every term to one side: {sp_text(moved)} = 0.",
                ]
                if factored != moved:
                    steps.append(f"Factor: {sp_text(factored)} = 0.")
                steps.append("Solve: " + ", ".join(rendered))
                return {
                    "solved": True,
                    "kind": "equation",
                    "input": expression.strip(),
                    "normalized": candidate,
                    "solution": ", ".join(rendered),
                    "solutions": rendered,
                    "steps": steps,
                }

            expr = _parse_expr(candidate)
            symbols = sorted(expr.free_symbols, key=lambda symbol: symbol.name)
            var = symbols[0] if symbols else sp.Symbol("x")

            if "d/d" in lowered_raw or re.search(
                r"\b(derivative|differentiate)\b", lowered_raw
            ):
                result = sp.simplify(sp.diff(expr, var))
                return {
                    "solved": True,
                    "kind": "derivative",
                    "input": expression.strip(),
                    "normalized": candidate,
                    "solution": f"d/d{var.name} ({sp_text(expr)}) = {sp_text(result)}",
                    "solutions": [sp_text(result)],
                    "steps": [
                        f"Differentiate {sp_text(expr)} with respect to {var.name}.",
                        f"Result: {sp_text(result)}",
                    ],
                }

            if re.search(r"\b(integral|integrate|antiderivative)\b", lowered_raw):
                result = sp.simplify(sp.integrate(expr, var))
                return {
                    "solved": True,
                    "kind": "integral",
                    "input": expression.strip(),
                    "normalized": candidate,
                    "solution": f"∫ {sp_text(expr)} d{var.name} = {sp_text(result)} + C",
                    "solutions": [sp_text(result)],
                    "steps": [
                        f"Integrate {sp_text(expr)} with respect to {var.name}.",
                        f"Result: {sp_text(result)} + C",
                    ],
                }

            simplified = sp.simplify(expr)
            if simplified.has(sp.zoo, sp.nan):
                return {
                    "solved": True,
                    "kind": "expression",
                    "input": expression.strip(),
                    "normalized": candidate,
                    "solution": "undefined",
                    "solutions": [],
                    "steps": [
                        f"Evaluate {sp_text(expr)}.",
                        "The expression is undefined.",
                    ],
                }
            if not symbols:
                value = _format_number(sp.N(simplified, 12))
                return {
                    "solved": True,
                    "kind": "expression",
                    "input": expression.strip(),
                    "normalized": candidate,
                    "solution": value,
                    "solutions": [value],
                    "steps": [
                        f"Evaluate {sp_text(expr)}.",
                        f"Result: {value}",
                    ],
                }

            return {
                "solved": True,
                "kind": "expression",
                "input": expression.strip(),
                "normalized": candidate,
                "solution": sp_text(simplified),
                "solutions": [sp_text(simplified)],
                "steps": [
                    f"Simplify {sp_text(expr)}.",
                    f"Result: {sp_text(simplified)}",
                ],
            }
        except (SyntaxError, TypeError, ValueError, ZeroDivisionError, AttributeError):
            continue
        except Exception:
            # SymPy raises many specialized exceptions for unsupported input.
            continue

    return {
        "solved": False,
        "input": expression.strip(),
        "reason": "No solvable math expression was found in the text.",
    }


@router.post("/api/solve")
async def solve_math(payload: SolveRequest):
    """Solve an equation or evaluate a math expression from recognized text."""
    try:
        return await asyncio.wait_for(
            run_in_threadpool(_solve_sync, payload.expression),
            timeout=SOLVE_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="The math solver timed out.")


@router.post("/api/translate")
async def translate_text(payload: TranslateRequest):
    """Translate recognized text with Google's public translate endpoint."""
    target = payload.target.strip().lower()
    source = payload.source.strip().lower()
    if not re.fullmatch(r"[a-z]{2,3}(?:-[a-z]{2,4})?", target):
        raise HTTPException(status_code=422, detail="Unsupported target language.")
    if source != "auto" and not re.fullmatch(r"[a-z]{2,3}(?:-[a-z]{2,4})?", source):
        raise HTTPException(status_code=422, detail="Unsupported source language.")

    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="There is no text to translate.")

    try:
        async with httpx.AsyncClient(timeout=TRANSLATE_TIMEOUT_SECONDS) as client:
            response = await client.get(
                "https://translate.googleapis.com/translate_a/single",
                params={
                    "client": "gtx",
                    "sl": source,
                    "tl": target,
                    "dt": "t",
                    "q": text[:TRANSLATE_MAX_CHARS],
                },
                headers={"User-Agent": "8search/1.0"},
            )
            response.raise_for_status()
            data = response.json()
    except Exception:
        raise HTTPException(status_code=502, detail="Translation is temporarily unavailable.")

    segments = data[0] if isinstance(data, list) and data else []
    translated = "".join(
        part[0] for part in segments
        if isinstance(part, list) and part and isinstance(part[0], str)
    ).strip()
    if not translated:
        raise HTTPException(status_code=502, detail="Translation returned no text.")

    detected = data[2] if isinstance(data, list) and len(data) > 2 else source
    return {
        "text": translated,
        "source_language": detected or "auto",
        "target_language": target,
    }
