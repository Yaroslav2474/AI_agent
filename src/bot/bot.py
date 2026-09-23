import asyncio
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from src.bot.handlers import router
from src.utils.config import settings
from src.db.database import init_db
from src.services.reminder_service import ReminderService

async def main():
    # Create bot
    bot = Bot(token=settings.bot_token)
    dp = Dispatcher(storage=MemoryStorage())

    # Register handlers
    dp.include_router(router)

    # Initialize reminder service with bot
    reminder_service = ReminderService(bot)

    # Start reminder service in background
    asyncio.create_task(reminder_service.start_reminder_loop())

    # Start polling
    print("Start polling")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
