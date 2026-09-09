import hashlib
import hmac
import json
import time
import urllib.parse

from fastapi import HTTPException, status

from config import settings

TELEGRAM_INIT_DATA_MAX_AGE = 24 * 60 * 60


def verify_telegram_webapp_data(init_data_raw: str) -> dict:
    try:
        parsed_data = dict(urllib.parse.parse_qsl(init_data_raw, keep_blank_values=True))
        supplied_hash = parsed_data.pop("hash", None)
        if not supplied_hash:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Некорректный формат Telegram initData",
            )

        data_check_string = "\n".join(
            f"{key}={value}" for key, value in sorted(parsed_data.items())
        )
        secret_key = hmac.new(
            b"WebAppData",
            settings.bot_token.get_secret_value().encode("utf-8"),
            hashlib.sha256,
        ).digest()
        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(calculated_hash, supplied_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Подпись Telegram initData не прошла проверку",
            )

        auth_date = int(parsed_data.get("auth_date", "0"))
        if auth_date <= 0 or abs(int(time.time()) - auth_date) > TELEGRAM_INIT_DATA_MAX_AGE:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Данные Telegram устарели. Откройте WebApp заново",
            )

        user_data = parsed_data.get("user")
        if not user_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Telegram не передал данные пользователя",
            )
        user = json.loads(user_data)
        if not isinstance(user, dict):
            raise ValueError("Telegram user must be an object")
        return user
    except HTTPException:
        raise
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Не удалось разобрать Telegram initData",
        ) from exc
