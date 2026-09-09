"""Общий слой доступа Umnix к OpenAI."""

from .client import (
    AIUpstreamError,
    DEFAULT_MODEL,
    create_chat_completion,
    get_openai_client,
    openai_client,
    parse_chat_completion,
    transcribe_audio,
)

__all__ = [
    "AIUpstreamError",
    "DEFAULT_MODEL",
    "create_chat_completion",
    "get_openai_client",
    "openai_client",
    "parse_chat_completion",
    "transcribe_audio",
]

