import json
from urllib.parse import quote
from config import settings

from aiogram import Router, F
from aiogram.filters import CommandStart, CommandObject, Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from database import db
from backend.auth.bot_login import approve_bot_login
from backend.bot.handlers.media import answer_plain
from backend.bot.handlers.keyboards import (
    get_admin_menu,
    get_parent_menu,
    get_role_keyboard,
    get_student_menu,
)
from logger_config import logger
from backend.web.activity import record_activity
from backend.web.mentor_identity import mentor_label, normalize_mentor_kind

router = Router()

STUDENT_START_TEXT = (
    "👋 *Добро пожаловать в Umnix!*\n\n"
    "🤖 *В Telegram можно:*\n"
    "• общаться с ИИ-тьютором и разбирать учебные темы;\n"
    "• отправлять фотографии и учебные файлы;\n"
    "• выбирать учебник в разделе «📚 Учебники» или спрашивать свободно через «🤖 ИИ-помощник»;\n"
    "• получать задания и отправлять решения;\n"
    "• следить за своим учебным прогрессом.\n\n"
    "🌐 *В Umnix WebApp доступно больше:*\n"
    "• полноценный чат и история диалогов;\n"
    "• удобная работа с заданиями и результатами;\n"
    "• учебники, задания, история диалогов и подробные результаты.\n\n"
    "Для полного интерфейса нажмите *«🌐 Открыть Umnix»*."
)

def parent_start_text(mentor_kind: str = "teacher") -> str:
    role = mentor_label(mentor_kind)
    return (
        f"👋 *Добро пожаловать в Umnix, {role}!*\n\n"
        "🤖 *В Telegram можно:*\n"
        "• привязать Ученика;\n"
        "• быстро посмотреть учебную активность;\n"
        "• выбирать учебник для вопроса или использовать свободный «🤖 ИИ-помощник»;\n"
        "• получать важные уведомления о заданиях и результатах.\n\n"
        "🌐 *В Umnix WebApp доступно больше:*\n"
        "• создавать задания вручную или с помощью ИИ;\n"
        "• прикреплять учебные материалы;\n"
        "• просматривать историю заданий, попытки и результаты;\n"
        "• управлять Учениками и учебным процессом.\n\n"
        "Для полного интерфейса нажмите *«🌐 Открыть Umnix»*."
    )


ADMIN_START_TEXT = (
    "👑 *Umnix · режим Администратора*\n\n"
    "🤖 В Telegram доступны быстрые действия и переключение роли.\n\n"
    "🌐 *В Umnix WebApp:*\n"
    "• управление учебниками и страницами;\n"
    "• пакетная оцифровка;\n"
    "• пользователи и активности;\n"
    "• административные инструменты.\n\n"
    "Откройте полный интерфейс кнопкой *«🌐 Открыть Umnix»*."
)

NEW_USER_START_TEXT = (
    "👋 *Добро пожаловать в Umnix!*\n\n"
    "Umnix — образовательный помощник для Учеников, Учителей и Родителей.\n\n"
    "🤖 Telegram подходит для быстрых действий, общения, уведомлений "
    "и работы с учебными заданиями.\n"
    "🌐 WebApp открывает полный интерфейс и расширенные возможности.\n\n"
    "Для начала выберите свою роль:"
)



@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, state: FSMContext = None):
    if state is not None:
        await state.clear()
    user_id = message.from_user.id
    username = message.from_user.username
    args = command.args

    if args and args.startswith("web_auth_"):
        auth_token = args.removeprefix("web_auth_")
        approved = await approve_bot_login(auth_token, user_id)
        if not approved:
            await message.answer(
                "Ссылка для входа недействительна или устарела. Вернитесь на сайт и повторите вход."
            )
            return

        async with db.pool.acquire() as conn:
            existing_user = await conn.fetchrow(
                "SELECT role, mentor_kind FROM users WHERE tg_id = $1",
                user_id,
            )
            if not existing_user and user_id in settings.admin_ids:
                await conn.execute(
                    """
                    INSERT INTO users (tg_id, username, role)
                    VALUES ($1, $2, 'admin'::user_role)
                    ON CONFLICT (tg_id) DO UPDATE SET username = EXCLUDED.username
                    """,
                    user_id,
                    username,
                )
                existing_user = await conn.fetchrow(
                    "SELECT role, mentor_kind FROM users WHERE tg_id = $1",
                    user_id,
                )
        if existing_user:
            await record_activity(
                user_id,
                "web_auth_confirm",
                "Подтверждение входа WebApp через Telegram-бот",
                source="telegram",
            )
            await message.answer(
                "✅ Вход подтверждён через Telegram. Вернитесь на страницу Umnix — аккаунт откроется автоматически."
            )
        else:
            await message.answer(
                "✅ Telegram подтверждён. Теперь выберите роль, чтобы завершить регистрацию и вход на сайте.",
                reply_markup=get_role_keyboard(),
            )
        return

    # Вход в Telegram фиксируется как одно значимое действие.
    try:
        async with db.pool.acquire() as conn:
            exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM users WHERE tg_id = $1)",
                user_id,
            )
        if exists:
            await record_activity(
                user_id,
                "login",
                "Вход в Telegram-бот",
                source="telegram",
            )
    except Exception:
        pass

    # --- СЦЕНАРИЙ 1: Регистрация по реферальной ссылке от родителя ---
    if args and args.startswith("reg_"):
        try:
            parent_id = int(args.split("_")[1])
        except (IndexError, ValueError):
            await message.answer("Некорректная ссылка для регистрации.")
            return

        if user_id == parent_id:
            await message.answer("Вы не можете привязать свой собственный аккаунт в качестве Ученика.")
            return

        async with db.pool.acquire() as conn:
            inviter = await conn.fetchrow(
                "SELECT role, mentor_kind FROM users WHERE tg_id = $1",
                parent_id,
            )
            if not inviter or inviter["role"] not in ("parent", "admin"):
                await message.answer("Эта ссылка привязки недействительна или отправитель больше недоступен.")
                return
            inviter_kind = normalize_mentor_kind(inviter.get("mentor_kind"))
            inviter_label = mentor_label(inviter_kind)

            existing = await conn.fetchrow(
                "SELECT role, parent_id FROM users WHERE tg_id = $1",
                user_id,
            )
            if existing and existing["role"] in ("parent", "admin"):
                await message.answer(
                    "Аккаунт Учителя, Родителя или Администратора нельзя "
                    "перепривязать как Ученика по ссылке-приглашению."
                )
                return
            if existing and existing["role"] == "student":
                current_parent = existing.get("parent_id")
                if current_parent and int(current_parent) != parent_id:
                    await message.answer(
                        f"Этот аккаунт Ученика уже привязан к другому {mentor_label(inviter_kind, 'dative')}. "
                        "Сначала отвяжите существующую связь в Umnix."
                    )
                    return
                if current_parent and int(current_parent) == parent_id:
                    await message.answer(
                        f"✅ Ваш аккаунт уже привязан к этому {mentor_label(inviter_kind, 'dative')}.",
                        reply_markup=get_student_menu(),
                    )
                    return

            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO users (tg_id, username, role, parent_id)
                    VALUES ($1, $2, 'student'::user_role, $3)
                    ON CONFLICT (tg_id) DO UPDATE
                    SET parent_id = $3, role = 'student'::user_role, username = EXCLUDED.username
                    """,
                    user_id, username, parent_id
                )

        await message.answer(
            (
                f"🎉 Аккаунт успешно связан: ваш {inviter_label} теперь видит "
                "назначенные задания и результаты.\n\n" + STUDENT_START_TEXT
            ),
            reply_markup=get_student_menu()
        )

        student_label = f"@{username}" if username else f"ID: {user_id}"
        try:
            await message.bot.send_message(
                chat_id=parent_id,
                text=f"🔔 Ученик ({student_label}) успешно привязал аккаунт. Теперь вы указаны как его {inviter_label}."
            )
        except Exception as e:
            logger.warning(f"Не удалось отправить уведомление наставнику {parent_id}: {e}")
        return

    # --- СЦЕНАРИЙ 2: Вход или первичная инициализация Администратора ---
    if user_id in settings.admin_ids:
        async with db.pool.acquire() as conn:
            user = await conn.fetchrow("SELECT role, mentor_kind FROM users WHERE tg_id = $1", user_id)
            if not user or user["role"] not in ["admin", "parent"]:
                await conn.execute(
                    """
                    INSERT INTO users (tg_id, username, role) VALUES ($1, $2, 'admin'::user_role)
                    ON CONFLICT (tg_id) DO UPDATE SET role = 'admin'::user_role
                    """,
                    user_id, username
                )
                role = "admin"
            else:
                role = user["role"]

        if role == "admin":
            await message.answer(
                ADMIN_START_TEXT,
                reply_markup=get_admin_menu(),
                parse_mode="Markdown",
            )
        else:
            await message.answer(
                (
                    parent_start_text(user.get("mentor_kind"))
                    + "\n\nИспользуйте /toggle, чтобы вернуться в режим Администратора."
                ),
                reply_markup=get_parent_menu(normalize_mentor_kind(user.get("mentor_kind"))),
                parse_mode="Markdown"
            )
        return

    # --- СЦЕНАРИЙ 3: Обычный авторизованный пользователь (Учитель / Ученик) ---
    async with db.pool.acquire() as conn:
        user = await conn.fetchrow("SELECT role, mentor_kind FROM users WHERE tg_id = $1", user_id)

    if user:
        role = user['role']
        if role == 'parent':
            await message.answer(
                parent_start_text(user.get("mentor_kind")),
                reply_markup=get_parent_menu(normalize_mentor_kind(user.get("mentor_kind"))),
                parse_mode="Markdown",
            )
        elif role == 'student':
            await message.answer(
                STUDENT_START_TEXT,
                reply_markup=get_student_menu(),
                parse_mode="Markdown",
            )
        return

    # --- СЦЕНАРИЙ 4: Новый пользователь (Выбор роли) ---
    await message.answer(
        NEW_USER_START_TEXT,
        reply_markup=get_role_keyboard(),
        parse_mode="Markdown",
    )


async def toggle_admin_role_logic(user_id: int, message_or_call) -> None:
    """Общая логика смены роли для админа"""
    if user_id not in settings.admin_ids:
        return

    async with db.pool.acquire() as conn:
        user = await conn.fetchrow("SELECT role, mentor_kind FROM users WHERE tg_id = $1", user_id)
        if not user:
            return

        current_role = user["role"]
        new_role = "parent" if current_role == "admin" else "admin"

        await conn.execute(
            "UPDATE users SET role = $1::user_role, "
            "mentor_kind = CASE WHEN $1 = 'parent' "
            "THEN COALESCE(mentor_kind, 'teacher') ELSE mentor_kind END "
            "WHERE tg_id = $2",
            new_role,
            user_id,
        )

    text_msg = ""
    reply_kb = None
    inline_kb = None

    if new_role == "admin":
        text_msg = (
            "👑 *Режим Администратора активирован!*\n\n"
            "Вы вернулись в панель управления. Все админские права и доступ к API восстановлены."
        )
        inline_kb = get_admin_menu()
    else:
        mentor_kind = normalize_mentor_kind(user.get("mentor_kind"))
        role_label = mentor_label(mentor_kind)
        text_msg = (
            f"👨‍👩‍👦 *Режим {role_label} активирован!*\n\n"
            f"Теперь бот отображает для вас меню роли «{role_label}». "
            "Чтобы вернуться в режим администрирования, используйте команду /toggle."
        )
        reply_kb = get_parent_menu(mentor_kind)

    if isinstance(message_or_call, CallbackQuery):
        try:
            await message_or_call.message.delete()
        except Exception:
            pass
        await message_or_call.message.answer(text_msg, reply_markup=reply_kb or inline_kb, parse_mode="Markdown")
    else:
        await message_or_call.answer(text_msg, reply_markup=reply_kb or inline_kb, parse_mode="Markdown")


@router.message(Command("toggle"))
async def cmd_toggle_role(message: Message, state: FSMContext = None):
    if state is not None:
        await state.clear()
    if message.from_user.id in settings.admin_ids:
        await toggle_admin_role_logic(message.from_user.id, message)


# Переключатель по инлайн-кнопке для админа
@router.callback_query(F.data == "admin_toggle_role")
async def callback_toggle_role(callback: CallbackQuery, state: FSMContext = None):
    if state is not None:
        await state.clear()
    if callback.from_user.id in settings.admin_ids:
        await toggle_admin_role_logic(callback.from_user.id, callback)
    await callback.answer()


# Сохранение первичной роли для обычных пользователей
@router.callback_query(F.data.startswith("set_role_"))
async def callbacks_num(callback: CallbackQuery):
    user_id = callback.from_user.id
    username = callback.from_user.username
    selected_role = callback.data.split("_")[2]
    db_role = "parent" if selected_role in {"teacher", "parent"} else selected_role
    mentor_kind = selected_role if selected_role in {"teacher", "parent"} else None

    if user_id in settings.admin_ids:
        await callback.answer("У вас максимальный уровень прав. Используйте переключатель!", show_alert=True)
        return

    async with db.pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO users (tg_id, username, role, mentor_kind)
                VALUES ($1, $2, $3::user_role, $4)
                ON CONFLICT (tg_id) DO UPDATE SET role = $3::user_role, mentor_kind = $4
                """,
                user_id, username, db_role, mentor_kind
            )

    if selected_role == 'student':
        await callback.message.edit_text(
            "✅ Роль успешно сохранена!\n\nТы зарегистрирован как **Ученик**.",
            parse_mode="Markdown",
        )
        await callback.message.answer(
            STUDENT_START_TEXT,
            reply_markup=get_student_menu(),
            parse_mode="Markdown",
        )
    elif selected_role in {"teacher", "parent"}:
        label = mentor_label(mentor_kind)
        await callback.message.edit_text(
            f"✅ Роль успешно сохранена!\n\nВы зарегистрированы как **{label}**.",
            parse_mode="Markdown",
        )
        await callback.message.answer(
            parent_start_text(mentor_kind),
            reply_markup=get_parent_menu(mentor_kind),
            parse_mode="Markdown",
        )

    await callback.answer()


@router.message(F.text == "➕ Привязать Ученика")
async def generate_child_link(message: Message, state: FSMContext = None):
    if state is not None:
        await state.clear()
    user_id = message.from_user.id

    async with db.pool.acquire() as conn:
        user = await conn.fetchrow("SELECT role, mentor_kind FROM users WHERE tg_id = $1", user_id)
        
    if not user or user['role'] not in ['parent', 'admin']:
        await message.answer("Эта команда доступна Учителю, Родителю или Администратору.")
        return
        
    mentor_kind = normalize_mentor_kind(user.get('mentor_kind'))
    role_label = mentor_label(mentor_kind)
    bot_user = await message.bot.get_me()
    link = f"https://t.me/{bot_user.username}?start=reg_{user_id}"

    share_url = (
        "https://t.me/share/url?url="
        + quote(link, safe="")
        + "&text="
        + quote(f"{role_label} приглашает тебя присоединиться к Umnix как Ученик", safe="")
    )
    await message.answer(
        f"👤 *Приглашение от роли «{role_label}»*\n\n"
        f"Отправьте эту ссылку Ученику. После перехода и нажатия *Старт* бот покажет, "
        f"что приглашение отправил именно {role_label}, и свяжет аккаунт с вашим профилем Umnix.\n\n"
        f"`{link}`",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(text="Поделиться ссылкой", url=share_url),
            ]]
        ),
    )


@router.message(F.text == "📊 Мониторинг в чате")
async def show_parent_monitoring(message: Message, state: FSMContext = None):
    if state is not None:
        await state.clear()
    user_id = message.from_user.id

    async with db.pool.acquire() as conn:
        user = await conn.fetchrow("SELECT role, mentor_kind FROM users WHERE tg_id = $1", user_id)
        if not user or user['role'] not in ['parent', 'admin']:
            await message.answer("Эта статистика доступна Учителям, Родителям и Администраторам.")
            return

        children = await conn.fetch(
            """
            SELECT u.tg_id, u.username,
                   COUNT(t.task_id) AS tasks_total,
                   COUNT(t.task_id) FILTER (WHERE t.status IN ('completed', 'evaluated')) AS tasks_done,
                   COALESCE(ROUND(AVG(t.score))::int, 0) AS average_score
            FROM users u
            LEFT JOIN tasks_history t
              ON t.student_id = u.tg_id AND t.assignment_source = 'teacher'
            WHERE u.parent_id = $1 AND u.role = 'student'
            GROUP BY u.tg_id, u.username
            ORDER BY u.username NULLS LAST
            """,
            user_id
        )

    if not children:
        await message.answer(
            "У вас пока нет привязанных Учеников.\n\n"
            "Нажмите кнопку **➕ Привязать Ученика**, чтобы отправить ему инвайт-ссылку.",
            parse_mode="Markdown"
        )
        return

    report = "📊 Мониторинг успеваемости Учеников:\n\n"
    for idx, child in enumerate(children, start=1):
        name = f"@{child['username']}" if child['username'] else f"Ученик ID: {child['tg_id']}"
        tasks_total = int(child['tasks_total'] or 0)
        tasks_done = int(child['tasks_done'] or 0)
        average_score = int(child['average_score'] or 0)

        report += (
            f"{idx}. 👤 {name}\n"
            f"   📝 Заданий: {tasks_done}/{tasks_total} выполнено\n"
            f"   📊 Средняя оценка: {average_score}\n\n"
        )

    await answer_plain(message, report)
