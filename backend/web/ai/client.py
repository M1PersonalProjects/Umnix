"""Единая конфигурация и вызовы OpenAI для всех функций Umnix."""

from __future__ import annotations

from typing import Any, Iterable, Optional, Type

from openai import APIConnectionError, APITimeoutError, AsyncOpenAI

from config import settings
from logger_config import logger

DEFAULT_MODEL = settings.openai_model


class AIUpstreamError(RuntimeError):
    """Ошибка внешнего AI-сервиса без утечки деталей пользователю."""


def get_openai_client() -> AsyncOpenAI:
    """Создаёт OpenAI-клиент с едиными timeout/retry настройками проекта."""
    return AsyncOpenAI(
        api_key=settings.openai_api_key.get_secret_value(),
        timeout=settings.openai_timeout_seconds,
        max_retries=settings.openai_max_retries,
    )


openai_client = get_openai_client()


async def create_chat_completion(
    client: AsyncOpenAI,
    *,
    messages: Iterable[dict[str, Any]],
    model: Optional[str] = None,
    **kwargs: Any,
) -> Any:
    """Выполняет обычный chat completion через общий слой логирования ошибок."""
    try:
        return await client.chat.completions.create(
            model=model or DEFAULT_MODEL,
            messages=list(messages),
            **kwargs,
        )
    except (APITimeoutError, APIConnectionError) as exc:
        logger.warning("Временная ошибка OpenAI: %s", type(exc).__name__)
        raise AIUpstreamError("AI service is temporarily unavailable") from exc
    except Exception as exc:
        logger.error("Ошибка OpenAI completion: %s", type(exc).__name__)
        raise


async def parse_chat_completion(
    client: AsyncOpenAI,
    *,
    messages: Iterable[dict[str, Any]],
    response_format: Type[Any],
    model: Optional[str] = None,
    **kwargs: Any,
) -> Any:
    """Выполняет Structured Output через общий слой конфигурации и ошибок."""
    try:
        return await client.beta.chat.completions.parse(
            model=model or DEFAULT_MODEL,
            messages=list(messages),
            response_format=response_format,
            **kwargs,
        )
    except (APITimeoutError, APIConnectionError) as exc:
        logger.warning("Временная ошибка OpenAI Structured Output: %s", type(exc).__name__)
        raise AIUpstreamError("AI service is temporarily unavailable") from exc
    except Exception as exc:
        logger.error("Ошибка OpenAI Structured Output: %s", type(exc).__name__)
        raise


async def transcribe_audio(
    *,
    data: bytes,
    filename: str = "voice.webm",
    content_type: str = "audio/webm",
    model: Optional[str] = None,
) -> str:
    """Транскрибирует короткое голосовое сообщение без сохранения временного файла."""
    if not data:
        raise ValueError("Пустое голосовое сообщение")
    try:
        response = await openai_client.audio.transcriptions.create(
            model=model or settings.openai_transcription_model,
            file=(filename or "voice.webm", data, content_type or "application/octet-stream"),
        )
    except (APITimeoutError, APIConnectionError) as exc:
        logger.warning("Временная ошибка распознавания голоса OpenAI: %s", type(exc).__name__)
        raise AIUpstreamError("Voice transcription service is temporarily unavailable") from exc
    except Exception as exc:
        logger.error("Ошибка распознавания голоса OpenAI: %s", type(exc).__name__)
        raise
    text = str(getattr(response, "text", "") or "").strip()
    if not text:
        raise ValueError("Не удалось распознать речь")
    return text
