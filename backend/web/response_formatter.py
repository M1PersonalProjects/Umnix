"""Canonical Markdown+LaTeX formatting helpers for umnix.ai clients.

The database/API keeps canonical Markdown + LaTeX so WebApp clients can render
mathematics properly. Telegram is the exception: raw TeX must never be sent to
users, therefore this module converts formulas to readable Unicode text or a
rendered image.
"""
from __future__ import annotations

import importlib
import io
import re
from dataclasses import dataclass
from typing import List, Literal, Optional


def canonicalize_message(value: object) -> str:
    """Нормализовать пробелы в переносах, не нарушая Markdown или LaTeX."""
    return str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()


@dataclass(frozen=True)
class TelegramPart:
    kind: Literal["text", "formula"]
    content: str
    display: bool = False


_MATH_COMMANDS = (
    "frac", "dfrac", "tfrac", "sqrt", "times", "cdot", "div", "pm", "mp",
    "le", "leq", "ge", "geq", "ne", "neq", "approx", "equiv", "sim", "simeq",
    "propto", "in", "notin", "ni", "subset", "subseteq", "supset", "supseteq",
    "cap", "cup", "setminus", "emptyset", "forall", "exists", "nabla", "partial",
    "sum", "prod", "int", "iint", "iiint", "oint", "lim", "min", "max",
    "sin", "cos", "tan", "tg", "cot", "ctg", "log", "ln", "lg", "exp",
    "pi", "infty", "alpha", "beta", "gamma", "delta", "epsilon", "varepsilon",
    "zeta", "eta", "theta", "vartheta", "iota", "kappa", "lambda", "mu", "nu",
    "xi", "rho", "sigma", "tau", "upsilon", "phi", "varphi", "chi", "psi", "omega",
    "Gamma", "Delta", "Theta", "Lambda", "Xi", "Pi", "Sigma", "Phi", "Psi", "Omega",
    "quad", "qquad", "Rightarrow", "Leftarrow", "Leftrightarrow", "rightarrow",
    "leftarrow", "to", "mapsto", "implies", "iff", "text", "textrm", "mathrm",
    "mathbf", "mathit", "mathsf", "mathtt", "operatorname", "begin", "end", "left",
    "right", "overline", "underline", "vec", "hat", "bar", "dot", "ddot", "boxed",
    "ldots", "cdots", "vdots", "ddots",
)
_MATH_COMMAND_PATTERN = "|".join(sorted((re.escape(x) for x in _MATH_COMMANDS), key=len, reverse=True))

_DISPLAY_RE = re.compile(r"\\\[(.+?)\\\]|\$\$(.+?)\$\$", re.S)
_INLINE_RE = re.compile(r"\\\((.+?)\\\)|(?<!\$)\$([^$\n]{1,2000})\$(?!\$)", re.S)
_DOUBLE_ESCAPED_MATH_RE = re.compile(rf"\\\\(?=(?:\[|\]|\(|\)|(?:{_MATH_COMMAND_PATTERN})(?![A-Za-z])))")
_BARE_LATEX_RE = re.compile(rf"\\(?:{_MATH_COMMAND_PATTERN})(?![A-Za-z])")
_RAW_LATEX_RE = re.compile(
    rf"(?:\\){{1,2}}(?:{_MATH_COMMAND_PATTERN})(?![A-Za-z])"
    rf"|(?:\\){{1,2}}[\[\]()]"
    rf"|(?:\\){{1,2}}[,;:!]"
    rf"|(?:\\){{1,2}}[A-Za-z]+\*?(?=\s*(?:\{{|_|\^))",
    re.S,
)


def contains_raw_latex(value: object) -> bool:
    """Возвращать True, если текст, видимый пользователю, всё ещё содержит распознанный TeX."""
    return bool(_RAW_LATEX_RE.search(canonicalize_message(value)))


def normalize_latex_transport(value: object) -> str:
    """Нормализовать один случайный слой экранирования для математических токенов."""
    return _DOUBLE_ESCAPED_MATH_RE.sub(r"\\", canonicalize_message(value))


def _replace_nested_frac(text: str) -> str:
    r"""
    Замените вложенные \frac, \dfrac и \tfrac на простую форму (числитель)/(знаменатель).
    """
    pattern = re.compile(r"\\(?:dfrac|tfrac|frac)\{([^{}]*)\}\{([^{}]*)\}")
    previous = None
    while previous != text:
        previous = text
        text = pattern.sub(r"(\1)/(\2)", text)
    return text


_SUPERSCRIPT = str.maketrans("0123456789+-=()n", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿ")
_SUBSCRIPT = str.maketrans("0123456789+-=()aeoxhklmnpst", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₒₓₕₖₗₘₙₚₛₜ")


def _simple_scripts(text: str) -> str:
    def sup(match: re.Match[str]) -> str:
        value = match.group(1)
        mapped = value.translate(_SUPERSCRIPT)
        return mapped if len(mapped) == len(value) else "^" + value

    def sub(match: re.Match[str]) -> str:
        value = match.group(1)
        mapped = value.translate(_SUBSCRIPT)
        return mapped if len(mapped) == len(value) else "_" + value

    text = re.sub(r"\^\{([0-9+\-=()n]+)\}", sup, text)
    text = re.sub(r"_\{([0-9+\-=()aeoxhklmnpst]+)\}", sub, text)
    text = re.sub(r"\^([0-9])", lambda m: m.group(1).translate(_SUPERSCRIPT), text)
    text = re.sub(r"_([0-9])", lambda m: m.group(1).translate(_SUBSCRIPT), text)
    return text


def _latex_fallback(expr: str) -> str:
    """Преобразование TeX в читаемый Unicode/обычный текст без раскрытия команд."""
    text = normalize_latex_transport(expr).strip()
    text = text.replace(r"\[", "").replace(r"\]", "").replace(r"\(", "").replace(r"\)", "")
    text = _replace_nested_frac(text)
    text = re.sub(r"\\sqrt\[([^]]+)\]\{([^{}]+)\}", r"root[\1](\2)", text)
    text = re.sub(r"\\sqrt\{([^{}]+)\}", r"√(\1)", text)

    wrapper = r"(?:text|textrm|mathrm|mathbf|mathit|mathsf|mathtt|operatorname|overline|underline|vec|hat|bar|boxed)"
    previous = None
    while previous != text:
        previous = text
        text = re.sub(rf"\\{wrapper}\s*\{{([^{{}}]*)\}}", r"\1", text)

    replacements = {
        r"\times": "×", r"\cdot": "·", r"\div": ":", r"\pm": "±", r"\mp": "∓",
        r"\le": "≤", r"\leq": "≤", r"\ge": "≥", r"\geq": "≥", r"\ne": "≠", r"\neq": "≠",
        r"\approx": "≈", r"\equiv": "≡", r"\sim": "∼", r"\simeq": "≃", r"\propto": "∝",
        r"\in": "∈", r"\notin": "∉", r"\ni": "∋", r"\subset": "⊂", r"\subseteq": "⊆",
        r"\supset": "⊃", r"\supseteq": "⊇", r"\cap": "∩", r"\cup": "∪", r"\setminus": "∖",
        r"\emptyset": "∅", r"\forall": "∀", r"\exists": "∃", r"\nabla": "∇", r"\partial": "∂",
        r"\sum": "∑", r"\prod": "∏", r"\int": "∫", r"\iint": "∬", r"\iiint": "∭", r"\oint": "∮",
        r"\Rightarrow": "⇒", r"\Leftarrow": "⇐", r"\Leftrightarrow": "⇔", r"\rightarrow": "→",
        r"\leftarrow": "←", r"\to": "→", r"\mapsto": "↦", r"\implies": "⇒", r"\iff": "⇔",
        r"\pi": "π", r"\infty": "∞", r"\alpha": "α", r"\beta": "β", r"\gamma": "γ", r"\delta": "δ",
        r"\epsilon": "ε", r"\varepsilon": "ϵ", r"\zeta": "ζ", r"\eta": "η", r"\theta": "θ",
        r"\vartheta": "ϑ", r"\iota": "ι", r"\kappa": "κ", r"\lambda": "λ", r"\mu": "μ", r"\nu": "ν",
        r"\xi": "ξ", r"\rho": "ρ", r"\sigma": "σ", r"\tau": "τ", r"\upsilon": "υ", r"\phi": "φ",
        r"\varphi": "ϕ", r"\chi": "χ", r"\psi": "ψ", r"\omega": "ω", r"\Gamma": "Γ", r"\Delta": "Δ",
        r"\Theta": "Θ", r"\Lambda": "Λ", r"\Xi": "Ξ", r"\Pi": "Π", r"\Sigma": "Σ", r"\Phi": "Φ",
        r"\Psi": "Ψ", r"\Omega": "Ω", r"\ldots": "…", r"\cdots": "⋯", r"\vdots": "⋮", r"\ddots": "⋱",
        r"\qquad": "  ", r"\quad": " ",
    }
    for source in sorted(replacements, key=len, reverse=True):
        text = text.replace(source, replacements[source])

    text = re.sub(r"\\(sin|cos|tan|tg|cot|ctg|log|ln|lg|exp|lim|min|max)\b", r"\1", text)
    text = text.replace(r"\\", "\n")
    environment_pattern = (
        r"\\begin\{(?:cases|aligned|align\*?|matrix|pmatrix|bmatrix|vmatrix)\}"
        r"|\\end\{(?:cases|aligned|align\*?|matrix|pmatrix|bmatrix|vmatrix)\}"
    )
    text = re.sub(environment_pattern, "", text)
    text = re.sub(r"\\(?:left|right)\b", "", text)
    text = re.sub(r"\\[,;:]", " ", text)
    text = text.replace(r"\!", "")
    text = _simple_scripts(text)

    text = re.sub(r"\\[A-Za-z]+\*?", "", text)
    text = text.replace("{", "").replace("}", "")
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def _latex_fallback_preserve_whitespace(value: str) -> str:
    text = str(value or "")
    leading = re.match(r"^[ \t]*", text).group(0)
    trailing = re.search(r"[ \t]*$", text).group(0)
    end = len(text) - len(trailing) if trailing else len(text)
    core = text[len(leading):end]
    return leading + _latex_fallback(core) + trailing



_WINDOWS_PATH_RE = re.compile(r"(?<![A-Za-z0-9_])(?:[A-Za-z]:)?(?:\\[A-Za-z0-9_. -]+){2,}")


def _latex_fallback_preserving_paths(value: str) -> str:
    """Запустить резервный вариант TeX, сохранив пути в стиле Windows/UNC без изменений."""
    paths: List[str] = []

    def protect(match: re.Match[str]) -> str:
        paths.append(match.group(0))
        return f"\x00PATH{len(paths) - 1}\x00"

    protected = _WINDOWS_PATH_RE.sub(protect, value)
    converted = _latex_fallback_preserve_whitespace(protected)
    for index, path in enumerate(paths):
        converted = converted.replace(f"\x00PATH{index}\x00", path)
    return converted

def is_complex_formula(expr: str) -> bool:
    value = normalize_latex_transport(expr).strip()
    return bool(
        len(value) > 36
        or re.search(r"\\(?:frac|dfrac|tfrac|begin|sum|prod|int|iint|iiint|lim)\b", value)
        or r"\sqrt[" in value
        or value.count("^") >= 2
    )


def _looks_like_bare_formula(line: str) -> bool:
    value = line.strip()
    if not _BARE_LATEX_RE.search(value):
        return False
    if value.startswith(("http://", "https://")):
        return False
    return True


def telegram_parts(value: object) -> List[TelegramPart]:
    """Разделить канонический контент, сохранив обычный код/URLы."""
    text = canonicalize_message(value)
    parts: List[TelegramPart] = []
    code_re = re.compile(r"```[\s\S]*?```|`[^`\n]*`")
    cursor = 0
    for match in code_re.finditer(text):
        if match.start() > cursor:
            parts.extend(_math_parts_segment(normalize_latex_transport(text[cursor:match.start()])))
        parts.append(TelegramPart("text", match.group(0)))
        cursor = match.end()
    if cursor < len(text):
        parts.extend(_math_parts_segment(normalize_latex_transport(text[cursor:])))
    return [part for part in parts if part.content]


def _math_parts_segment(text: str) -> List[TelegramPart]:
    parts: List[TelegramPart] = []
    cursor = 0
    for match in _DISPLAY_RE.finditer(text):
        if match.start() > cursor:
            parts.extend(_inline_parts(text[cursor:match.start()]))
        expr = match.group(1) or match.group(2) or ""
        parts.append(TelegramPart("formula", expr.strip(), True))
        cursor = match.end()
    if cursor < len(text):
        parts.extend(_inline_parts(text[cursor:]))
    return parts


def _inline_parts(text: str) -> List[TelegramPart]:
    result: List[TelegramPart] = []
    cursor = 0
    for match in _INLINE_RE.finditer(text):
        if match.start() > cursor:
            result.extend(_bare_parts(text[cursor:match.start()]))
        expr = (match.group(1) or match.group(2) or "").strip()
        if is_complex_formula(expr):
            result.append(TelegramPart("formula", expr, False))
        else:
            result.append(TelegramPart("text", _latex_fallback(expr)))
        cursor = match.end()
    if cursor < len(text):
        result.extend(_bare_parts(text[cursor:]))
    return result


def _bare_parts(text: str) -> List[TelegramPart]:
    result: List[TelegramPart] = []
    for line in text.splitlines(keepends=True):
        stripped = line.rstrip("\r\n")
        suffix = line[len(stripped):]
        if _looks_like_bare_formula(stripped):
            result.append(TelegramPart("text", _latex_fallback_preserving_paths(stripped) + suffix))
        else:
            result.append(TelegramPart("text", stripped + suffix))
    return result


def telegram_formula_fallback(expr: str) -> str:
    return _latex_fallback(expr)


def _strip_telegram_markdown(segment: str) -> str:
    """Убрать управляющие маркеры Markdown, не затрагивая обычные знаки препинания."""
    text = segment
    # Headings are structural markers only when they start a line.
    text = re.sub(r"(?m)^[ \t]{0,3}#{1,6}[ \t]+", "", text)
    # Markdown bullets become readable Unicode bullets; arithmetic '*' elsewhere stays intact.
    text = re.sub(r"(?m)^[ \t]*[*+-][ \t]+", "• ", text)
    # Strong/emphasis markers are removed only when they form a balanced Markdown pair.
    text = re.sub(r"\*\*([^*\n]+?)\*\*", r"\1", text)
    text = re.sub(r"__([^_\n]+?)__", r"\1", text)
    text = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"\1", text)
    # A spaced arithmetic slash is a school-division sign, not a URL/path separator.
    text = re.sub(r"(?<=\d)[ \t]+/[ \t]+(?=\d)", " : ", text)
    return text


def _format_telegram_prose(segment: str) -> str:
    """Отформатировать один сегмент, не являющийся кодом, защитив URL от преобразования текста."""
    urls: List[str] = []

    def protect_url(match: re.Match[str]) -> str:
        urls.append(match.group(0))
        return f"\x00URL{len(urls) - 1}\x00"

    work = re.sub(r"https?://[^\s<>()]+", protect_url, segment)
    converted: List[str] = []
    work = _DOUBLE_ESCAPED_MATH_RE.sub(r"\\", work)
    for part in _math_parts_segment(work):
        if part.kind == "formula":
            converted.append(_latex_fallback(part.content))
        else:
            converted.append(part.content)
    work = "".join(converted)
    if contains_raw_latex(work):
        work = "\n".join(
            _latex_fallback_preserving_paths(line) if contains_raw_latex(line) else line
            for line in work.splitlines()
        )
    work = _strip_telegram_markdown(work)
    for index, url in enumerate(urls):
        work = work.replace(f"\x00URL{index}\x00", url)
    return work


def format_for_telegram(value: object) -> str:
    """
    Форматировать канонический контент в безопасный для Telegram Markdown.
    """
    text = canonicalize_message(value)
    code_re = re.compile(r"```[\s\S]*?```|`[^`\n]*`")
    parts: List[str] = []
    cursor = 0
    for match in code_re.finditer(text):
        if match.start() > cursor:
            parts.append(_format_telegram_prose(text[cursor:match.start()]))
        code = match.group(0)
        if contains_raw_latex(code):
            code = _latex_fallback(code)
        parts.append(code)
        cursor = match.end()
    if cursor < len(text):
        parts.append(_format_telegram_prose(text[cursor:]))
    result = "".join(parts)

    if contains_raw_latex(result):
        result = "\n".join(
            _latex_fallback_preserving_paths(line) if contains_raw_latex(line) else line
            for line in result.splitlines()
        )
    result = re.sub(r"(?m)^[ \t]{0,3}#{1,6}[ \t]+", "", result)
    result = result.replace("**", "")
    return result.strip()


def telegram_safe_text(value: object) -> str:
    return format_for_telegram(value)


def render_formula_png(expr: str) -> Optional[bytes]:
    """Рендерит формулу в PNG, если Matplotlib установлен в окружении."""
    try:
        matplotlib = importlib.import_module("matplotlib")
        matplotlib.use("Agg")
        plt = importlib.import_module("matplotlib.pyplot")

        fig = plt.figure(figsize=(0.01, 0.01), dpi=180)
        fig.patch.set_alpha(0)
        source = normalize_latex_transport(expr)
        text = fig.text(0.02, 0.5, f"${source.strip()}$", fontsize=18, va="center")
        fig.canvas.draw()
        bbox = text.get_window_extent(renderer=fig.canvas.get_renderer()).expanded(1.08, 1.35)
        width, height = bbox.width / fig.dpi, bbox.height / fig.dpi
        fig.set_size_inches(max(width, 0.4), max(height, 0.35))
        text.set_position((0.02, 0.5))
        buffer = io.BytesIO()
        fig.savefig(buffer, format="png", transparent=True, bbox_inches="tight", pad_inches=0.08)
        plt.close(fig)
        return buffer.getvalue()
    except Exception:
        return None
