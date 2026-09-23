import asyncio
from datetime import datetime, timedelta
from sqlalchemy import select
from src.db.database import get_session
from src.models.database import Booking, TimeSimulation, GuestCard
from src.services.data_loader import data_loader
from src.utils.config import settings
from aiogram import Bot

class ReminderService:
    def __init__(self, bot: Bot = None):
        self.bot = bot
        self.rules = data_loader.get_rules()
        self.reminder_after_hours = self.rules.get("reminder_after_hours", 12)
        self.max_reminders = self.rules.get("max_reminders", 1)
        self.escalate_after_hours = self.rules.get("escalate_after_second_wait_hours", 12)

    async def get_current_time(self) -> datetime:
        """Get current time with simulation offset"""
        async for session in get_session():
            result = await session.execute(select(TimeSimulation).order_by(TimeSimulation.id.desc()))
            time_sim = result.scalar_one_or_none()

            if time_sim and time_sim.hours_offset > 0:
                return datetime.utcnow() + timedelta(hours=time_sim.hours_offset)

        return datetime.utcnow()

    async def check_reminders(self):
        """Check and send reminders for incomplete bookings"""
        current_time = await self.get_current_time()

        async for session in get_session():
            # Get incomplete bookings
            result = await session.execute(
                select(Booking).where(
                    Booking.status == "incomplete",
                    Booking.reminder_count < self.max_reminders
                )
            )
            incomplete_bookings = result.scalars().all()

            for booking in incomplete_bookings:
                # Calculate time since booking creation
                time_since_creation = current_time - booking.created_at
                hours_since_creation = time_since_creation.total_seconds() / 3600

                # Check if it's time to send reminder
                if hours_since_creation >= self.reminder_after_hours and not booking.last_reminder_sent:
                    # Send reminder
                    if booking.booking_id:
                        # Find telegram ID from guest card
                        from src.models.database import GuestCard
                        card_result = await session.execute(
                            select(GuestCard).where(GuestCard.booking_id == booking.booking_id)
                        )
                        guest_card = card_result.scalar_one_or_none()

                        if guest_card and guest_card.telegram_id:
                            try:
                                if self.bot:
                                    await self.bot.send_message(
                                        guest_card.telegram_id,
                                        f"Напоминание: Пожалуйста, завершите заполнение карточки заезда. Ваша бронь: {booking.booking_id}"
                                    )
                                else:
                                    print(f"REMINDER for {guest_card.telegram_id}: Пожалуйста, завершите заполнение карточки заезда. Бронь: {booking.booking_id}")

                                booking.last_reminder_sent = current_time
                                booking.reminder_count += 1
                                await session.commit()
                            except Exception as e:
                                print(f"Failed to send reminder to {guest_card.telegram_id}: {e}")

                # Check if escalation is needed (after second interval)
                if booking.reminder_count >= self.max_reminders:
                    time_since_last_reminder = current_time - booking.last_reminder_sent if booking.last_reminder_sent else timedelta(hours=0)
                    hours_since_last_reminder = time_since_last_reminder.total_seconds() / 3600

                    if hours_since_last_reminder >= self.escalate_after_hours:
                        booking.status = "needs_human"
                        await session.commit()

    async def start_reminder_loop(self):
        """Start the reminder checking loop"""
        while True:
            await self.check_reminders()
            await asyncio.sleep(300)  # Check every 5 minutes


