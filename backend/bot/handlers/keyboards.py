from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
from config import settings

def get_role_keyboard() -> InlineKeyboardMarkup:
    """
    Возвращает клавиатуру для выбора роли пользователя в Telegram.
    """
    buttons = [
        [InlineKeyboardButton(text="👨‍💻 Я Ученик", callback_data="set_role_student")],
        [
            InlineKeyboardButton(text="👩‍🏫 Я Учитель", callback_data="set_role_teacher"),
            InlineKeyboardButton(text="👨‍👩‍👧 Я Родитель", callback_data="set_role_parent"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_parent_menu(mentor_kind: str = "teacher") -> ReplyKeyboardMarkup:
    """
    Telegram меню для Родителей.
    """
    buttons = [
        [
            KeyboardButton(text="➕ Привязать Ученика"),
            KeyboardButton(text="📊 Мониторинг в чате"),
        ],
        [
            KeyboardButton(text="📚 Учебники"),
            KeyboardButton(text="🤖 ИИ-помощник"),
        ],
        [
            KeyboardButton(
                text="🌐 Открыть Umnix",
                web_app=WebAppInfo(url=settings.webapp_base_url),
            ),
        ],
    ]
    return ReplyKeyboardMarkup(
        keyboard=buttons,
        resize_keyboard=True,
    )


def get_student_menu() -> ReplyKeyboardMarkup:
    """
    Telegram меню для Ученика.
    """
    buttons = [
        [
            KeyboardButton(text="📚 Учебники"),
            KeyboardButton(text="🧩 Квест-тест"),
        ],
        [KeyboardButton(text="🤖 ИИ-помощник")],
        [
            KeyboardButton(
                text="🌐 Открыть Umnix",
                web_app=WebAppInfo(url=settings.webapp_base_url),
            ),
        ],
    ]
    return ReplyKeyboardMarkup(
        keyboard=buttons,
        resize_keyboard=True,
    )


def get_admin_menu() -> InlineKeyboardMarkup:
    """Administrator quick actions without duplicating WebApp pages."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🌐 Открыть Umnix",
                    web_app=WebAppInfo(url=settings.webapp_base_url),
                )
            ],
            [
                InlineKeyboardButton(
                    text="⇄ Обычный режим",
                    callback_data="admin_toggle_role",
                )
            ],
        ]
    )
