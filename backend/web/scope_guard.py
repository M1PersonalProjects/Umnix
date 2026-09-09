from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel, Field

from backend.web.context_resolver import ResolvedContext


class ScopeClassification(BaseModel):
    """Backward-compatible shape retained for old imports/tests."""
    is_educational: bool = Field(default=True)
    matches_selected_context: bool = Field(default=True)
    reason: str = Field(default="")


@dataclass
class ScopeGuardResult:
    allowed: bool
    reason: str
    refusal_message: Optional[str] = None


EDUCATIONAL_PATTERNS: tuple[re.Pattern[str], ...] = ()
OUT_OF_SCOPE_PATTERNS: tuple[re.Pattern[str], ...] = ()

_EDUCATIONAL_SENSITIVE = re.compile(
    r"\b(анатоми|биологи|медицин|репродукц|полов\w*\s+созрев|полов\w*\s+систем|"
    r"истори|обществознани|литератур|психологи)\w*\b",
    re.IGNORECASE,
)
_SEXUAL_18 = re.compile(
    r"\b(секс\s*чат|эротическ|порнограф|порно|сексуальн\w*\s+фантази|"
    r"интимн\w*\s+переписк|возбуди\s+меня|sex\s*chat|erotic|porn(?:ography)?|"
    r"sexual\s+fantas(?:y|ies)|sexting)\w*\b",
    re.IGNORECASE,
)
_HARM_OPERATIONAL = re.compile(
    r"\b(как|инструкц|сделать|собрать|изготовить|создать|приготовить|спрятать|"
    r"обойти|усилить|how\s+to|instructions?|build|make|construct|prepare|hide|"
    r"improve)\b.{0,120}\b(бомб|взрывчат|оружи|самодельн\w*\s+оруж|яд|"
    r"отрав|убить|покалеч|теракт|террорист|bomb|explosive|weapon|poison|kill|"
    r"terror(?:ism|ist))\w*\b",
    re.IGNORECASE | re.DOTALL,
)
_GAME_PROGRESS = re.compile(
    r"\b(как\s+пройти|прохождени|лучший\s+билд|мета\s+билд|прокачк|"
    r"фарм\w*\s+(?:ресурс|золот|опыт)|чит\w*|cheat|exploit|эксплойт|"
    r"тактик\w*\s+для\s+(?:босс|рейд)|walkthrough|best\s+build|meta\s+build|"
    r"leveling\s+guide|farm(?:ing)?\s+(?:gold|xp|resources?)|boss\s+tactics?)\b",
    re.IGNORECASE,
)
_GAME_EDUCATION = re.compile(
    r"\b(как\s+устроен|объясни\s+алгоритм|математик|физик|истори|"
    r"программирован|разработк\w*\s+игр|game\s+development)\b",
    re.IGNORECASE,
)
_PROFESSIONAL_OUTSOURCING = re.compile(
    r"\b(сделай|напиши|разработай|реализуй|создай|build|write|develop|implement|create)\b.{0,180}"
    r"\b(под\s+ключ|готов\w*\s+проект|production|продакшн|для\s+клиента|"
    r"коммерческ\w*\s+проект|рабоч\w*\s+(?:сервис|код)|полностью\s+готов\w*\s+"
    r"(?:приложени|код|сайт|сервис)|turnkey|complete\s+production|production-ready|"
    r"for\s+(?:my|a)\s+client|commercial\s+project|full\s+working\s+(?:app|service|code))\b",
    re.IGNORECASE | re.DOTALL,
)


def build_refusal_message(
    context: Optional[ResolvedContext],
    reason: Optional[str] = None,
) -> str:
    base = (
        "Я могу помочь с обучением, обычными вопросами и повседневным разговором, "
        "но не могу помогать с этой конкретной опасной или запрещённой задачей."
    )
    return f"{base}\n\n{reason}" if reason else base


def _quick_check(
    message_text: str,
    context: Optional[ResolvedContext],
    attachment_text: str = "",
) -> ScopeGuardResult:
    combined = f"{message_text or ''}\n{attachment_text or ''}".strip()

    if not combined:
        return ScopeGuardResult(True, "No text to classify; allow attachment analysis.")

    if _SEXUAL_18.search(combined) and not _EDUCATIONAL_SENSITIVE.search(combined):
        return ScopeGuardResult(
            False,
            "Non-educational sexual/18+ conversation is not supported.",
            build_refusal_message(context),
        )

    if _HARM_OPERATIONAL.search(combined):
        return ScopeGuardResult(
            False,
            "Operational assistance for weapons, terrorism, poisoning, or deliberate harm is not supported.",
            build_refusal_message(context),
        )

    if _GAME_PROGRESS.search(combined) and not _GAME_EDUCATION.search(combined):
        return ScopeGuardResult(
            False,
            "umnix.ai does not provide game walkthroughs, builds, cheats, or progression tactics.",
            (
                "Я могу обсудить игру как обычную тему или помочь изучать программирование, "
                "математику, историю и другие знания на её примере, но не буду вести "
                "прохождение, подбирать билды, читы или тактики прокачки."
            ),
        )

    if _PROFESSIONAL_OUTSOURCING.search(combined):
        return ScopeGuardResult(
            False,
            "The request is framed as outsourcing a complete professional deliverable rather than learning.",
            (
                "Я могу объяснить подход, помочь спроектировать учебный пример, разобрать "
                "ошибки и вместе пройти реализацию по шагам, но не буду выполнять за вас "
                "полный профессиональный проект под ключ."
            ),
        )

    return ScopeGuardResult(True, "Allowed ordinary/educational request.")


async def validate_request_scope(
    message_text: str,
    context: Optional[ResolvedContext],
    attachment_text: str = "",
) -> ScopeGuardResult:
    """Permissive default-deny-only guard shared by WebApp and Telegram."""
    return _quick_check(message_text, context, attachment_text)
