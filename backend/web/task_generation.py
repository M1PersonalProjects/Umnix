from __future__ import annotations

import re
from typing import Any, List, Optional, Sequence

from pydantic import BaseModel, Field

from backend.web.ai import parse_chat_completion
from backend.web.prompts import AI_TUTOR_SYSTEM_PROMPT


class GeneratedTaskItem(BaseModel):
    question: str = Field(..., min_length=1, max_length=12000)
    answer: str = Field(..., min_length=1, max_length=8000)
    short_answer: str = Field(default="", max_length=1000)
    task_type: str = Field(default="practice", max_length=80)
    # Квесты используют эти поля для закрытых вопросов с одним или несколькими
    # правильными вариантами. Для обычных заданий поля остаются пустыми.
    options: List[str] = Field(default_factory=list, max_length=6)
    correct_option_numbers: List[int] = Field(default_factory=list, max_length=6)


class GeneratedTaskSet(BaseModel):
    title: str = Field(..., min_length=1, max_length=240)
    description: str = Field(default="", max_length=40000)
    correct_answer: str = Field(default="", max_length=30000)
    items: List[GeneratedTaskItem] = Field(default_factory=list, max_length=100)


_COUNT_RE = re.compile(
    r"(?<!\d)(\d{1,3})\s+"
    r"(?:(?:[A-Za-zА-Яа-яЁё-]{2,32})\s+){0,3}"
    r"(?:задач(?:а|и|у|е|ами|)?|задани(?:е|я|й|ю|ями)|"
    r"упражнени(?:е|я|й|ю|ями)|вопрос(?:а|ов|ы)?|пример(?:а|ов|ы)?|"
    r"tasks?|questions?|exercises?|problems?)\b",
    re.I,
)


def find_requested_task_count(*values: object, maximum: int = 100) -> Optional[int]:
    """Return an explicitly requested task count, or None when no count was stated."""
    for value in values:
        match = _COUNT_RE.search(str(value or ""))
        if match:
            return max(1, min(int(match.group(1)), maximum))
    return None


def extract_requested_task_count(*values: object, default: int = 1, maximum: int = 100) -> int:
    explicit = find_requested_task_count(*values, maximum=maximum)
    if explicit is not None:
        return explicit
    return max(1, min(int(default or 1), maximum))


def normalize_task_set(generated: GeneratedTaskSet) -> GeneratedTaskSet:
    """Keep legacy description/answer fields while making item count programmatically inspectable."""
    if not generated.items and generated.description.strip():
        generated.items = [
            GeneratedTaskItem(
                question=generated.description.strip(),
                answer=generated.correct_answer.strip() or "Ответ проверяется Учителем.",
            )
        ]
    if generated.items:
        generated.description = "\n\n".join(
            f"{index}. {item.question.strip()}" for index, item in enumerate(generated.items, start=1)
        )
        solution_blocks = []
        short_answers = []
        for index, item in enumerate(generated.items, start=1):
            solution = item.answer.strip()
            short = item.short_answer.strip()
            if not short:
                lines = [line.strip() for line in solution.splitlines() if line.strip()]
                short = lines[-1] if lines else solution
                short = re.sub(r"^(?:ответ|answer)\s*:\s*", "", short, flags=re.I)
            solution_blocks.append(f"Задание {index}\nРешение:\n{solution}")
            short_answers.append(f"{index}. {short}")
        generated.correct_answer = (
            "\n\n".join(solution_blocks)
            + "\n\nОтветы:\n"
            + "\n".join(short_answers)
        )
    return generated


def generated_count(generated: GeneratedTaskSet) -> int:
    return len(normalize_task_set(generated).items)


def task_set_payload(generated: GeneratedTaskSet) -> dict[str, Any]:
    normalized = normalize_task_set(generated)
    return {
        "title": normalized.title,
        "question_text": normalized.description,
        "reference_answer": normalized.correct_answer,
        "question_count": len(normalized.items),
        "items": [
            {
                "id": f"q{index}",
                "question_text": item.question,
                "reference_answer": item.answer,
                "task_type": item.task_type,
                "options": list(item.options or []),
                "correct_option_numbers": list(item.correct_option_numbers or []),
                "allow_multiple": len(set(item.correct_option_numbers or [])) > 1,
            }
            for index, item in enumerate(normalized.items, start=1)
        ],
    }


async def generate_exact_task_set(
    client,
    *,
    user_content: Any,
    requested_count: int,
    model: Optional[str] = None,
    temperature: float = 0.3,
) -> GeneratedTaskSet:
    """Generate and verify the requested count, with the required repair request on mismatch."""
    requested_count = max(1, min(int(requested_count or 1), 100))
    count_instruction = (
        f"\n\nREQUESTED_COUNT: {requested_count}\n"
        f"Return exactly {requested_count} distinct item(s) in the `items` field."
    )

    async def request(content: Any, *, repair: bool = False) -> Optional[GeneratedTaskSet]:
        if isinstance(content, str):
            final_content: Any = content + count_instruction
            if repair:
                final_content += (
                    f"\n\nCOUNT REPAIR: The previous response had the wrong number of tasks. "
                    f"It takes exactly {requested_count}. Return exactly {requested_count} items now."
                )
        elif isinstance(content, Sequence):
            final_content = list(content)
            final_content.append({"type": "text", "text": count_instruction + (
                f"\nCOUNT REPAIR: The previous response had the wrong number. It takes exactly {requested_count}."
                if repair else ""
            )})
        else:
            final_content = str(content) + count_instruction
        response = await parse_chat_completion(client,
            model=model,
            temperature=temperature if not repair else min(temperature, 0.2),
            messages=[
                {"role": "system", "content": AI_TUTOR_SYSTEM_PROMPT},
                {"role": "user", "content": final_content},
            ],
            response_format=GeneratedTaskSet,
        )
        parsed = response.choices[0].message.parsed
        return normalize_task_set(parsed) if parsed else None

    generated = await request(user_content)
    if generated is not None and generated_count(generated) == requested_count:
        return generated

    repaired = await request(user_content, repair=True)
    if repaired is None or generated_count(repaired) != requested_count:
        actual = generated_count(repaired) if repaired is not None else 0
        raise ValueError(
            f"Task generation count mismatch: requested_count={requested_count}, generated_count={actual}"
        )
    return repaired
