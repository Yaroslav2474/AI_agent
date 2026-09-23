import asyncio
from src.db.database import init_db, get_session
from src.services.data_loader import data_loader
from src.models.database import Booking
from sqlalchemy import select

async def initialize_bookings():
    """Initialize bookings from JSON file into database"""
    await init_db()

    async for session in get_session():
        # Check if bookings already exist
        result = await session.execute(select(Booking).limit(1))
        existing = result.scalar_one_or_none()

        if existing:
            print("Bookings already initialized")
            return

        # Load bookings from JSON
        bookings = data_loader.get_bookings()

        for booking_data in bookings:
            booking = Booking(
                booking_id=booking_data["booking_id"],
                arrival_date=booking_data["arrival_date"],
                departure_date=booking_data["departure_date"],
                category=booking_data["category"],
                house_id=booking_data["house_id"],
                guest_name=booking_data["guest_name"],
                phone=booking_data.get("phone"),
                adults=booking_data["adults"],
                children=booking_data["children"],
                payment_status=booking_data["payment_status"],
                group_id=booking_data.get("group_id"),
                start_token=booking_data["start_token"],
                note=booking_data.get("note")
            )
            session.add(booking)

        await session.commit()
        print(f"Initialized {len(bookings)} bookings")

if __name__ == "__main__":
    from src.db.database import get_session
    asyncio.run(initialize_bookings())
