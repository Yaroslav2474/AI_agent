from fastapi import FastAPI, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from src.db.database import get_session
from src.models.database import Booking, GuestCard
from datetime import datetime, timezone

app = FastAPI(title="Речка и Песок Admin Panel")
templates = Jinja2Templates(directory="src/api/templates")

@app.get("/", response_class=HTMLResponse)
async def admin_panel(request: Request):
    """Main admin panel with guest cards table"""
    async for session in get_session():
        result = await session.execute(
            select(Booking, GuestCard)
            .outerjoin(GuestCard, Booking.booking_id == GuestCard.booking_id)
            .order_by(Booking.arrival_date)
        )
        bookings_cards = result.all()

    bookings_data = []
    for booking, guest_card in bookings_cards:
        bookings_data.append({
            "booking_id": booking.booking_id,
            "guest_name": booking.guest_name,
            "arrival_date": booking.arrival_date,
            "arrival_time": booking.arrival_time,
            "house_id": booking.house_id,
            "adults": booking.guest_adults or booking.adults,
            "children": booking.guest_children or booking.children,
            "has_car": booking.has_car,
            "car_plates": booking.car_plates,
            "has_pet": booking.has_pet,
            "status": booking.status,
            "kpp_string": guest_card.kpp_string if guest_card else None,
            "estimated_cost": guest_card.estimated_cost if guest_card else None,
            "telegram_id": guest_card.telegram_id if guest_card else None,
            "updated_at": booking.updated_at.strftime("%Y-%m-%d %H:%M") if booking.updated_at else None
        })

    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "bookings": bookings_data,
            "now": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        }
    )

@app.post("/confirm/{booking_id}")
async def confirm_checkin(booking_id: str):
    """Confirm guest check-in"""
    async for session in get_session():
        result = await session.execute(
            select(Booking).where(Booking.booking_id == booking_id)
        )
        booking = result.scalar_one_or_none()

        if booking:
            booking.status = "confirmed"
            await session.commit()

    return {"status": "success", "booking_id": booking_id}

@app.post("/escalate/{booking_id}")
async def escalate_booking(booking_id: str):
    """Escalate booking to human attention"""
    async for session in get_session():
        result = await session.execute(
            select(Booking).where(Booking.booking_id == booking_id)
        )
        booking = result.scalar_one_or_none()

        if booking:
            booking.status = "needs_human"
            await session.commit()

    return {"status": "success", "booking_id": booking_id}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
