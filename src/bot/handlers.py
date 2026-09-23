from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime, timedelta
from sqlalchemy import select
from src.bot.fsm_states import CheckInStates
from src.db.database import get_session
from src.models.database import Booking, GuestCard, TimeSimulation
from src.services.data_loader import data_loader
from src.services.business_logic import business_logic
from src.services.llm_service import llm_service
from src.utils.config import settings

router = Router()

# Constants
SECURITY_ERROR = "Ошибка доступа. Бронь не найдена или токен недействителен. Обратитесь к администратору"
ESCALATION_MESSAGE = "Данный вопрос находится вне моей компетенции. Передаю запрос администратору. Телефон службы бронирования: +7 (844) 255-38-43"
PAYMENT_NOTICE = "Оплата производится строго на ресепшене при заселении"

@router.message(CheckInStates.waiting_for_start)
async def process_start_command(message: types.Message, state: FSMContext):
    """Process /start <token> command"""
    text = message.text
    if not text.startswith("/start"):
        await message.answer("Пожалуйста, используйте команду /start <токен>")
        return

    parts = text.split()
    if len(parts) < 2:
        await message.answer("Пожалуйста, укажите токен после команды /start")
        return

    token = parts[1]

    # Validate token and find booking
    booking = data_loader.get_booking_by_token(token)
    if not booking:
        await message.answer(SECURITY_ERROR)
        await state.clear()
        return

    booking_id = booking["booking_id"]

    # Check if booking already has a guest card
    async for session in get_session():
        result = await session.execute(
            select(GuestCard).where(GuestCard.booking_id == booking_id)
        )
        existing_card = result.scalar_one_or_none()

        if existing_card:
            # Resume existing session
            await state.update_data(booking_id=booking_id, telegram_id=str(message.from_user.id))
            await state.set_state(CheckInStates.collecting_info)
            await message.answer(f"Добро пожаловать, {booking['guest_name']}! Продолжим заполнение данных.")
        else:
            # Create new guest card
            new_card = GuestCard(
                booking_id=booking_id,
                telegram_id=str(message.from_user.id),
                status="incomplete"
            )
            session.add(new_card)
            await session.commit()

            await state.update_data(booking_id=booking_id, telegram_id=str(message.from_user.id))
            await state.set_state(CheckInStates.collecting_info)

            # Send welcome message
            rules = data_loader.get_rules()
            welcome_text = f"""
Добро пожаловать, {booking['guest_name']}!

Ваша бронь: {booking_id}
Домик: {booking['house_id']}
Заезд: {booking['arrival_date']} с {rules['checkin']}
Выезд: {booking['departure_date']} до {rules['checkout']}

Пожалуйста, сообщите следующую информацию:
- Количество взрослых и детей
- Время прибытия (в формате ЧЧ:ММ)
- Будете ли на автомобиле (если да, укажите госномер)
- Будете ли с питомцем
- Нужны ли дополнительные услуги (доп. место, ранний заезд, завтрак)
"""
            await message.answer(welcome_text)

@router.message(CheckInStates.collecting_info)
async def process_guest_info(message: types.Message, state: FSMContext):
    """Process guest information using LLM parsing"""
    data = await state.get_data()
    booking_id = data["booking_id"]
    booking = data_loader.get_booking_by_id(booking_id)

    # Get current booking state from database
    async for session in get_session():
        result = await session.execute(
            select(Booking).where(Booking.booking_id == booking_id)
        )
        booking_record = result.scalar_one_or_none()

        if not booking_record:
            await message.answer("Ошибка при загрузке данных брони.")
            return

        # Use LLM to parse the message
        context = {
            "booking": booking,
            "current_state": {
                "adults": booking_record.guest_adults,
                "children": booking_record.guest_children,
                "arrival_time": booking_record.arrival_time,
                "has_car": booking_record.has_car,
                "car_plates": booking_record.car_plates,
                "has_pet": booking_record.has_pet,
                "extra_bed_requested": booking_record.extra_bed_requested,
                "early_arrival_requested": booking_record.early_arrival_requested,
                "breakfast_requested": booking_record.breakfast_requested
            }
        }

        parsed_data = await llm_service.parse_guest_message(message.text, context)

        if "error" in parsed_data:
            await message.answer("Не удалось распознать сообщение. Пожалуйста, уточните информацию.")
            return

        # Check for security questions or change requests
        message_type = await llm_service.classify_message(message.text)

        if message_type in ["security_question", "change_request"]:
            # Escalate to human
            booking_record.status = "needs_human"
            if not booking_record.human_requests:
                booking_record.human_requests = []
            booking_record.human_requests.append({
                "type": message_type,
                "message": message.text,
                "timestamp": datetime.utcnow().isoformat()
            })
            await session.commit()
            await message.answer(ESCALATION_MESSAGE)
            await state.set_state(CheckInStates.needs_human)
            return

        # Check for human requests
        if parsed_data.get("human_request"):
            booking_record.status = "needs_human"
            if not booking_record.human_requests:
                booking_record.human_requests = []
            booking_record.human_requests.append({
                "type": "human_request",
                "message": parsed_data["human_request"],
                "timestamp": datetime.utcnow().isoformat()
            })
            await session.commit()
            await message.answer("Ваш запрос передан администратору.")
            await state.set_state(CheckInStates.needs_human)
            return

        # Validate and update fields
        updated = False
        validation_errors = []

        # Time validation
        if parsed_data.get("arrival_time"):
            if not business_logic.validate_time_format(parsed_data["arrival_time"]):
                validation_errors.append("Пожалуйста, укажите время в формате ЧЧ:ММ (например, 18:00)")
            else:
                booking_record.arrival_time = parsed_data["arrival_time"]
                updated = True

        # Car plate validation
        if parsed_data.get("has_car") is not None:
            booking_record.has_car = parsed_data["has_car"]
            updated = True

            if parsed_data.get("has_car") and parsed_data.get("car_plates"):
                car_plates = parsed_data["car_plates"]
                if car_plates and not business_logic.validate_car_plate(car_plates[0]):
                    validation_errors.append("Пожалуйста, укажите корректный госномер (минимум 6 символов)")
                else:
                    booking_record.car_plates = car_plates
                    updated = True
            elif not parsed_data.get("has_car"):
                booking_record.car_plates = []
                updated = True

        # Update other fields
        if parsed_data.get("adults") is not None:
            booking_record.guest_adults = parsed_data["adults"]
            updated = True

        if parsed_data.get("children") is not None:
            booking_record.guest_children = parsed_data["children"]
            updated = True

        if parsed_data.get("has_pet") is not None:
            booking_record.has_pet = parsed_data["has_pet"]
            updated = True

        if parsed_data.get("extra_bed_requested") is not None:
            booking_record.extra_bed_requested = parsed_data["extra_bed_requested"]
            updated = True

        if parsed_data.get("early_arrival_requested") is not None:
            booking_record.early_arrival_requested = parsed_data["early_arrival_requested"]
            updated = True

        if parsed_data.get("breakfast_requested") is not None:
            booking_record.breakfast_requested = parsed_data["breakfast_requested"]
            updated = True

        if parsed_data.get("coal_quantity") is not None:
            booking_record.human_requests = booking_record.human_requests or []
            booking_record.human_requests.append({
                "type": "coal_request",
                "quantity": parsed_data["coal_quantity"],
                "timestamp": datetime.utcnow().isoformat()
            })
            updated = True

        # Rules acceptance
        if parsed_data.get("rules_accepted") is not None:
            booking_record.rules_accepted = parsed_data["rules_accepted"]
            if parsed_data["rules_accepted"]:
                rules = data_loader.get_rules()
                booking_record.rules_version = rules["version"]
                booking_record.rules_accepted_at = datetime.utcnow()
            updated = True

        if updated:
            booking_record.updated_at = datetime.utcnow()
            await session.commit()

        # Send validation errors if any
        if validation_errors:
            await message.answer("\n".join(validation_errors))
            return

        # Check if rules were rejected
        if parsed_data.get("rules_accepted") == False:
            booking_record.status = "needs_human"
            await session.commit()
            await message.answer("Правила не приняты. Ваш запрос передан администратору.")
            await state.set_state(CheckInStates.needs_human)
            return

        # Check if card is ready
        booking_data = {
            "booking_id": booking_record.booking_id,
            "arrival_date": booking_record.arrival_date,
            "departure_date": booking_record.departure_date,
            "house_id": booking_record.house_id,
            "adults": booking_record.guest_adults,
            "children": booking_record.guest_children,
            "arrival_time": booking_record.arrival_time,
            "has_car": booking_record.has_car,
            "car_plates": booking_record.car_plates,
            "has_pet": booking_record.has_pet,
            "extra_bed_requested": booking_record.extra_bed_requested,
            "early_arrival_requested": booking_record.early_arrival_requested,
            "breakfast_requested": booking_record.breakfast_requested,
            "rules_accepted": booking_record.rules_accepted
        }

        is_ready, missing_fields = business_logic.check_card_ready(booking_data)

        if is_ready:
            # Calculate costs
            costs = business_logic.calculate_total_cost(booking_data)

            # Generate KPP string
            kpp_string = business_logic.generate_kpp_string(booking_data)

            # Update guest card
            result = await session.execute(
                select(GuestCard).where(GuestCard.booking_id == booking_id)
            )
            guest_card = result.scalar_one_or_none()
            if guest_card:
                guest_card.status = "ready"
                guest_card.kpp_string = kpp_string
                guest_card.estimated_cost = costs
                guest_card.updated_at = datetime.utcnow()
                await session.commit()

            booking_record.status = "ready"
            await session.commit()

            # Send confirmation
            confirmation_text = f"""
Спасибо! Ваша карточка готова.

📋 Ваша бронь: {booking_id}
🏠 Домик: {booking['house_id']}
📅 Заезд: {booking['arrival_date']} в {booking_record.arrival_time}
📅 Выезд: {booking['departure_date']}

👥 Гостей: {booking_record.guest_adults} взрослых, {booking_record.guest_children} детей
🚗 Автомобиль: {'Да' if booking_record.has_car else 'Нет'}
"""

            if booking_record.has_car and kpp_string:
                confirmation_text += f"🪪 Пропуск КПП: {kpp_string}\n"

            if costs:
                confirmation_text += "\n💰 Дополнительные услуги:\n"
                for key, cost in costs.items():
                    if cost.get("total"):
                        confirmation_text += f"  • {cost['item']}: {cost['total']} руб.\n"
                    else:
                        confirmation_text += f"  • {cost['item']}: цена по запросу\n"

            confirmation_text += f"\n{PAYMENT_NOTICE}"

            await message.answer(confirmation_text)
            await state.set_state(CheckInStates.ready)
        else:
            # Request missing information
            missing_text = "Пожалуйста, уточните:\n" + "\n".join(f"• {field}" for field in missing_fields)
            await message.answer(missing_text)

@router.message(CheckInStates.ready)
async def handle_ready_state(message: types.Message, state: FSMContext):
    """Handle messages when card is ready"""
    data = await state.get_data()
    booking_id = data["booking_id"]

    # Check for human requests
    message_type = await llm_service.classify_message(message.text)

    if message_type in ["security_question", "change_request", "escalation_needed"]:
        async for session in get_session():
            result = await session.execute(
                select(Booking).where(Booking.booking_id == booking_id)
            )
            booking_record = result.scalar_one_or_none()

            if booking_record:
                booking_record.status = "needs_human"
                if not booking_record.human_requests:
                    booking_record.human_requests = []
                booking_record.human_requests.append({
                    "type": message_type,
                    "message": message.text,
                    "timestamp": datetime.utcnow().isoformat()
                })
                await session.commit()

        await message.answer(ESCALATION_MESSAGE)
        await state.set_state(CheckInStates.needs_human)
    else:
        await message.answer("Ваша карточка уже готова. Если у вас есть дополнительные вопросы, они будут переданы администратору.")

@router.message(CheckInStates.needs_human)
async def handle_needs_human(message: types.Message, state: FSMContext):
    """Handle messages when human intervention is needed"""
    await message.answer("Ваш запрос обрабатывается администратором. Телефон службы бронирования: +7 (844) 255-38-43")

# Admin command to simulate time travel
@router.message(F.text.startswith("/travel_time"))
async def travel_time_command(message: types.Message, state: FSMContext):
    """Admin command to simulate time travel for testing"""
    # Check if user is admin
    user_id = message.from_user.id
    if user_id not in settings.admin_ids_list:
        await message.answer("Эта команда доступна только администраторам.")
        return

    try:
        parts = message.text.split()
        hours = int(parts[1])

        async for session in get_session():
            result = await session.execute(select(TimeSimulation).order_by(TimeSimulation.id.desc()))
            time_sim = result.scalar_one_or_none()

            if time_sim:
                time_sim.hours_offset += hours
                time_sim.updated_at = datetime.utcnow()
            else:
                time_sim = TimeSimulation(hours_offset=hours)
                session.add(time_sim)

            await session.commit()

            current_offset = time_sim.hours_offset

        await message.answer(f"Время сдвинуто на {hours} часов вперед. Текущее смещение: {current_offset} часов.")

    except (IndexError, ValueError):
        await message.answer("Использование: /travel_time <часы>")

# Command to start check-in
@router.message()
async def handle_unknown_message(message: types.Message, state: FSMContext):
    """Handle unknown messages"""
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("Пожалуйста, начните с команды /start <токен>")
        await state.set_state(CheckInStates.waiting_for_start)
