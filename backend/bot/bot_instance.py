from aiogram import Bot, Dispatcher

from backend.bot.handlers import chat, context, start
from backend.bot.middleware import UserActionLogMiddleware
from config import settings

bot = Bot(token=settings.bot_token.get_secret_value())
dp = Dispatcher()
dp.message.middleware(UserActionLogMiddleware())
dp.callback_query.middleware(UserActionLogMiddleware())
dp.include_router(start.router)
dp.include_router(context.router)
dp.include_router(chat.router)
