from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from backend.bot.handlers.media import parse_telegram_attachment
from backend.bot.handlers.media import answer_plain
from database import db
from logger_config import logger
from backend.web.file_parser import AttachmentError
from backend.web.thinking import TelegramThinkingIndicator
from backend.web.ai_tutor import ensure_telegram_session, exit_book_mode
from backend.web.ai_tutor import generate_response
from backend.web.activity import record_activity


router = Router()


def exit_book_keyboard() -> InlineKeyboardMarkup:
    """
    Возвращает клавиатуру с кнопкой для выхода из режима учебника.
    """
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Открепить учебник", callback_data="exit_book_mode")
    ]])


@router.message(Command("exit_book"))
async def exit_book_command(message: Message, state: FSMContext):
    """
    Команда для выхода из режима учебника и очистки контекста.
    """
    try:
        session = await ensure_telegram_session(message.from_user.id)
        await exit_book_mode(message.from_user.id, str(session["session_id"]))
    except LookupError:
        pass
    await state.clear()
    await message.answer(
        "✅ Учебник откреплён. Чтобы снова начать чат с ИИ, "
        "нажмите «🤖 ИИ-помощник»."
    )


@router.callback_query(F.data == "exit_book_mode")
async def exit_book_callback(callback: CallbackQuery, state: FSMContext):
    """
    Обработчик нажатия кнопки для выхода из режима учебника.
    """
    try:
        session = await ensure_telegram_session(callback.from_user.id)
        await exit_book_mode(callback.from_user.id, str(session["session_id"]))
    except LookupError:
        pass
    await state.clear()
    await callback.answer("Учебник откреплён")
    await callback.message.answer(
        "✅ Контекст учебника очищен. Для начала чата нажмите «🤖 ИИ-помощник»."
    )


@router.message(F.text == "🤖 ИИ-помощник")
async def enter_general_ai_helper(message: Message, state: FSMContext):
    """
    Включает постоянный режим свободного чата с ИИ до тех пор, пока другой workflow не заменит его.
    """
    try:
        session = await ensure_telegram_session(message.from_user.id)
        await exit_book_mode(message.from_user.id, str(session["session_id"]))
    except LookupError:
        pass
    await state.clear()
    await message.answer(
        "🤖 ИИ-помощник включён. Теперь просто пишите вопросы или присылайте "
        "фото/документы — повторно нажимать кнопку не нужно. Режим останется "
        "активным, пока вы явно не выберете другой раздел."
    )


@router.message(Command("new_chat"))
async def new_bot_chat(message: Message):
    """
    Создаёт новый чат с ИИ-тьютором для пользователя.
    """
    session = await ensure_telegram_session(message.from_user.id)
    await message.answer(
        "📱 Telegram использует один постоянный чат "
        f"«{session['title']}». Дополнительные чаты создаются в Umnix WebApp."
    )


async def _handle_ai_message(message: Message):
    """
    Обрабатывает сообщение от пользователя в постоянном режиме чата с ИИ.
    """
    user_text = (message.text or message.caption or "").strip()
    if user_text.startswith("/"):
        return

    async with db.pool.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT role FROM users WHERE tg_id = $1", message.from_user.id
        )
    if not user:
        await message.answer(
            "Сначала зарегистрируйтесь: отправьте /start и выберите свою роль."
        )
        return
    if user["role"] not in ("student", "parent", "admin"):
        await message.answer("Для вашей роли ИИ-тьютор пока недоступен.")
        return

    indicator = await TelegramThinkingIndicator(message, "ИИ-тьютор думает").start()
    try:
        attachment = await parse_telegram_attachment(message)
        session = await ensure_telegram_session(message.from_user.id)
        result = await generate_response(
            user_id=message.from_user.id,
            role=user["role"],
            session_id=str(session["session_id"]),
            message=user_text,
            mode="chat",
            attachment=attachment,
            attachment_id=getattr(attachment, "attachment_id", None),
            message_source="telegram",
        )
        await record_activity(
            int(message.from_user.id),
            "tutor_message",
            user_text or (attachment.filename if attachment else "Вложение"),
            source="telegram",
            session_id=str(session["session_id"]),
            attachment_id=getattr(attachment, "attachment_id", None),
        )
        await indicator.stop(delete=False)
        await answer_plain(
            message,
            result.get("message_text") or "",
            reply_markup=exit_book_keyboard() if result.get("book_mode") else None,
        )
        await indicator.stop()
    except AttachmentError as exc:
        await indicator.stop(delete=False)
        await indicator.status_message.edit_text(f"❌ {exc}")
    except Exception as exc:
        logger.exception("Telegram tutor failed for %s: %s", message.from_user.id, exc)
        await indicator.stop(delete=False)
        try:
            if indicator.status_message:
                await indicator.status_message.edit_text(
                    "❌ Не удалось связаться с ИИ-тьютором. Попробуйте позже."
                )
            else:
                await message.answer(
                    "❌ Не удалось связаться с ИИ-тьютором. Попробуйте позже."
                )
        except Exception:
            await message.answer(
                "❌ Не удалось связаться с ИИ-тьютором. Попробуйте позже."
            )


@router.message(F.text | F.photo | F.document)
async def quick_ai_chat_fallback(message: Message):
    """
    Обрабатывает сообщения от пользователя в постоянном режиме чата с ИИ.
    """
    await _handle_ai_message(message)
