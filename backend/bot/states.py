from aiogram.fsm.state import State, StatesGroup


class BookFilterStates(StatesGroup):
    """Состояния выбора учебного контекста и генерации Quest-test."""

    choosing_grade = State()
    choosing_subject = State()
    choosing_book = State()
    choosing_topic = State()
    context_ready = State()
    waiting_for_ai_question = State()
    waiting_for_quest_request = State()


class QuestStates(StatesGroup):
    """Временное состояние прохождения Quest-test в Telegram."""

    waiting_for_answer = State()
