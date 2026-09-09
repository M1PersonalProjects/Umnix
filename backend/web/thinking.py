import asyncio
from contextlib import suppress


def format_elapsed(seconds: int) -> str:
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


class TelegramThinkingIndicator:
    """
    Класс для отображения индикатора "ИИ думает" в Telegram.
    """
    def __init__(self, message, label: str = "ИИ думает"):
        self.message = message
        self.label = label
        self.status_message = None
        self._task = None

    async def start(self):
        """
        Запускает индикатор "ИИ думает" и отображает сообщение о процессе.
        """
        self.status_message = await self.message.answer(f"🧠 {self.label}… (Осталось совсем немного...)")
        self._task = asyncio.create_task(self._run())
        return self

    async def _run(self):
        """
        Фоновая задача для обновления индикатора времени.
        """
        elapsed = 0
        while True:
            await asyncio.sleep(5)
            elapsed += 5
            with suppress(Exception):
                await self.message.bot.send_chat_action(self.message.chat.id, "typing")
                await self.status_message.edit_text(
                    f"🧠 {self.label}… ({format_elapsed(elapsed)})"
                )

    async def stop(self, delete: bool = True):
        """
        Останавливает индикатор "ИИ думает" и опционально удаляет сообщение о процессе.
        """
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
        if self.status_message and delete:
            with suppress(Exception):
                await self.status_message.delete()
