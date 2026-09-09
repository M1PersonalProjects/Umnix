import re

import logger_config


def test_user_action_log_uses_required_diagnostic_format(monkeypatch) -> None:
    messages = []
    monkeypatch.setattr(
        logger_config.user_action_logger,
        "info",
        lambda message, **_: messages.append(message),
    )

    logger_config.log_user_action(
        123456789,
        200,
        "Telegram ID login completed",
        "backend/api/auth_router.py",
        77,
    )

    assert len(messages) == 1
    pattern = (
        r"^\d{2}\.\d{2}\.\d{2}_\d{2}\.\d{2}\.\d{2}_123456789_"
        r"\[200 OK\]_Telegram ID login completed_backend/api/auth_router\.py:77$"
    )
    assert re.match(pattern, messages[0])
