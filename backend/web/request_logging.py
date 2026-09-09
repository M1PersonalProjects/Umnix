from __future__ import annotations

from typing import Optional

from fastapi import Request
from starlette.responses import Response

from backend.auth.security import session_tg_id_for_audit
from logger_config import exception_location, log_user_action, source_location

SKIPPED_PREFIXES = ("/static/", "/digitization-books/")
SKIPPED_PATHS = {"/api/v1/auth/frontend-error"}


def _request_tg_id(request: Request) -> Optional[int]:
    explicit = getattr(request.state, "audit_tg_id", None)
    if explicit is not None:
        try:
            return int(explicit)
        except (TypeError, ValueError):
            return None

    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return session_tg_id_for_audit(token)


def _description(request: Request, status_code: int) -> str:
    explicit = getattr(request.state, "audit_message", "")
    if explicit:
        return str(explicit)
    if status_code >= 500:
        return f"HTTP {request.method} request failed with a server error"
    if status_code >= 400:
        return f"HTTP {request.method} request was rejected"
    return f"HTTP {request.method} request completed"


async def log_http_request(request: Request, call_next) -> Response:
    """Логирует каждое серверное действие пользователя, кроме выдачи статических ресурсов."""
    if request.url.path.startswith(SKIPPED_PREFIXES) or request.url.path in SKIPPED_PATHS:
        return await call_next(request)

    try:
        response = await call_next(request)
    except Exception as exc:
        source_file, line_number = exception_location(exc)
        log_user_action(
            _request_tg_id(request),
            500,
            f"Unhandled {type(exc).__name__}",
            source_file,
            line_number,
        )
        raise

    endpoint = request.scope.get("endpoint")
    source_file, line_number = source_location(endpoint)
    log_user_action(
        _request_tg_id(request),
        response.status_code,
        _description(request, response.status_code),
        source_file,
        line_number,
    )
    return response
