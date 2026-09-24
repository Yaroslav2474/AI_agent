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
from src.services.pdf_service import pdf_service
from src.utils.config import settings
import logging

logger = logging.getLogger(__name__)

router = Router()

# Constants
SECURITY_ERROR = "Ошибка доступа. Бронь не найдена или токен недействителен. Обратитесь к администратору"
ESCALATION_MESSAGE = "Данный вопрос находится вне моей компетенции. Передаю запрос администратору. Телефон службы бронирования: +7 (844) 255-38-43"
PAYMENT_NOTICE = "Оплата производится строго на ресепшене при заселении"

# Admin command to simulate time travel (moved to top to avoid routing conflicts)
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

# /start command handler (must be before state handlers to catch /start in any state)
@router.message(F.text.startswith("/start"))
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
            # Resume existing session - determine which step to resume from
            await state.update_data(booking_id=booking_id, telegram_id=str(message.from_user.id))
            await state.set_state(CheckInStates.step_1_name)
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
            await state.set_state(CheckInStates.step_1_name)

            # Send welcome message
            rules = data_loader.get_rules()
            welcome_text = f"""
Добро пожаловать, {booking['guest_name']}!

Ваша бронь: {booking_id}
Домик: {booking['house_id']}
Заезд: {booking['arrival_date']} с {rules['checkin']}
Выезд: {booking['departure_date']} до {rules['checkout']}

Давайте заполним карточку регистрации по шагам.
"""
            await message.answer(welcome_text)
            await message.answer("Шаг 1 из 7: Пожалуйста, представьтесь (ФИО)")

@router.message(CheckInStates.step_1_name)
async def process_step_1_name(message: types.Message, state: FSMContext):
    """Step 1: Validate guest name using AI"""
    # Guard clause: ignore commands
    if message.text and message.text.startswith("/"):
        return

    # Use AI to validate that this is a real name
    validation_prompt = """
Validate if the following text is a real person's name (in Russian or English).
Return JSON with: {"is_valid_name": boolean, "reason": string}
If it's not a name (e.g., time, random text, numbers), set is_valid_name to false and explain why.
"""

    try:
        response = await llm_service.client.chat.completions.create(
            model="openrouter/free",
            messages=[
                {"role": "system", "content": validation_prompt},
                {"role": "user", "content": message.text}
            ],
            temperature=0.1
        )

        content = response.choices[0].message.content
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        import json
        validation_result = json.loads(content)

        if not validation_result.get("is_valid_name"):
            await message.answer(f"Пожалуйста, введите корректное ФИО. {validation_result.get('reason', '')}")
            return

    except Exception as e:
        logger.exception(f"Name validation error: {e}")
        # Fallback: basic validation
        if len(message.text) < 2 or message.text.isdigit():
            await message.answer("Пожалуйста, введите корректное ФИО.")
            return

    # Save the name
    await state.update_data(guest_name=message.text)
    await state.set_state(CheckInStates.step_2_guests)
    await message.answer("Шаг 2 из 7: Сколько взрослых и детей приедет? (например: '2 взрослых, 1 ребенок' или 'нас будет трое')")

@router.message(CheckInStates.step_2_guests)
async def process_step_2_guests(message: types.Message, state: FSMContext):
    """Step 2: Parse number of adults and children using AI"""
    # Guard clause: ignore commands
    if message.text and message.text.startswith("/"):
        return

    parsing_prompt = """
Extract the number of adults and children from the message.
Return JSON with: {"adults": integer, "children": integer}
If only total number is given (e.g., "нас будет трое"), assume all are adults.
Set children to 0 if not mentioned.
"""

    try:
        response = await llm_service.client.chat.completions.create(
            model="openrouter/free",
            messages=[
                {"role": "system", "content": parsing_prompt},
                {"role": "user", "content": message.text}
            ],
            temperature=0.1
        )

        content = response.choices[0].message.content
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        import json
        parsed = json.loads(content)

        adults = parsed.get("adults", 0)
        children = parsed.get("children", 0)

        if adults <= 0:
            await message.answer("Пожалуйста, укажите корректное количество взрослых (минимум 1).")
            return

        await state.update_data(adults=adults, children=children)
        await state.set_state(CheckInStates.step_3_time)
        await message.answer("Шаг 3 из 7: Во сколько вы планируете прибыть? (например: 'в 2 часа дня' или '14:00')")

    except Exception as e:
        logger.exception(f"Guest count parsing error: {e}")
        await message.answer("Не удалось распознать количество гостей. Пожалуйста, укажите число взрослых и детей.")

@router.message(CheckInStates.step_3_time)
async def process_step_3_time(message: types.Message, state: FSMContext):
    """Step 3: Convert arrival time to HH:MM format using AI"""
    # Guard clause: ignore commands
    if message.text and message.text.startswith("/"):
        return

    parsing_prompt = """
Convert the arrival time to HH:MM format (24-hour).
Examples: "2 часа дня" -> "14:00", "в два дня" -> "14:00", "18:00" -> "18:00"
Return JSON with: {"time": string in HH:MM format}
"""

    try:
        response = await llm_service.client.chat.completions.create(
            model="openrouter/free",
            messages=[
                {"role": "system", "content": parsing_prompt},
                {"role": "user", "content": message.text}
            ],
            temperature=0.1
        )

        content = response.choices[0].message.content
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        import json
        parsed = json.loads(content)
        time_str = parsed.get("time", "")

        # Validate time format
        if not business_logic.validate_time_format(time_str):
            await message.answer("Пожалуйста, укажите время в корректном формате (например: '14:00' или 'в 2 часа дня').")
            return

        await state.update_data(arrival_time=time_str)
        await state.set_state(CheckInStates.step_4_car)
        await message.answer("Шаг 4 из 7: Будете ли вы на автомобиле? Если да, укажите госномер.")

    except Exception as e:
        logger.exception(f"Time parsing error: {e}")
        await message.answer("Не удалось распознать время. Пожалуйста, укажите время в формате ЧЧ:ММ.")

@router.message(CheckInStates.step_4_car)
async def process_step_4_car(message: types.Message, state: FSMContext):
    """Step 4: Check for car and parse license plates"""
    # Guard clause: ignore commands
    if message.text and message.text.startswith("/"):
        return

    parsing_prompt = """
Determine if the guest has a car and extract license plates.
Return JSON with: {"has_car": boolean, "car_plates": array of strings}
If guest says "без машины" or similar, set has_car to false and car_plates to empty array.
"""

    try:
        response = await llm_service.client.chat.completions.create(
            model="openrouter/free",
            messages=[
                {"role": "system", "content": parsing_prompt},
                {"role": "user", "content": message.text}
            ],
            temperature=0.1
        )

        content = response.choices[0].message.content
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        import json
        parsed = json.loads(content)

        has_car = parsed.get("has_car", False)
        car_plates = parsed.get("car_plates", [])

        if has_car and car_plates:
            # Validate car plate
            if not business_logic.validate_car_plate(car_plates[0]):
                await message.answer("Пожалуйста, укажите корректный госномер (минимум 6 символов).")
                return

        await state.update_data(has_car=has_car, car_plates=car_plates if has_car else [])
        await state.set_state(CheckInStates.step_5_pet)
        await message.answer("Шаг 5 из 7: Будете ли вы с питомцем?")

    except Exception as e:
        logger.exception(f"Car parsing error: {e}")
        await message.answer("Не удалось распознать информацию об автомобиле. Пожалуйста, уточните.")

@router.message(CheckInStates.step_5_pet)
async def process_step_5_pet(message: types.Message, state: FSMContext):
    """Step 5: Check for pets"""
    # Guard clause: ignore commands
    if message.text and message.text.startswith("/"):
        return

    parsing_prompt = """
Determine if the guest has a pet.
Return JSON with: {"has_pet": boolean}
"""

    try:
        response = await llm_service.client.chat.completions.create(
            model="openrouter/free",
            messages=[
                {"role": "system", "content": parsing_prompt},
                {"role": "user", "content": message.text}
            ],
            temperature=0.1
        )

        content = response.choices[0].message.content
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        import json
        parsed = json.loads(content)
        has_pet = parsed.get("has_pet", False)

        await state.update_data(has_pet=has_pet)
        await state.set_state(CheckInStates.step_6_services)
        await message.answer("Шаг 6 из 7: Нужны ли дополнительные услуги? (дополнительное место, ранний заезд, завтрак)")

    except Exception as e:
        logger.exception(f"Pet parsing error: {e}")
        await message.answer("Не удалось распознать ответ. Пожалуйста, уточните, будет ли с вами питомец.")

@router.message(CheckInStates.step_6_services)
async def process_step_6_services(message: types.Message, state: FSMContext):
    """Step 6: Parse additional services"""
    # Guard clause: ignore commands
    if message.text and message.text.startswith("/"):
        return

    parsing_prompt = """
Extract which additional services are requested.
Return JSON with: {"extra_bed": boolean, "early_arrival": boolean, "breakfast": boolean}
"""

    try:
        response = await llm_service.client.chat.completions.create(
            model="openrouter/free",
            messages=[
                {"role": "system", "content": parsing_prompt},
                {"role": "user", "content": message.text}
            ],
            temperature=0.1
        )

        content = response.choices[0].message.content
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        import json
        parsed = json.loads(content)

        await state.update_data(
            extra_bed_requested=parsed.get("extra_bed", False),
            early_arrival_requested=parsed.get("early_arrival", False),
            breakfast_requested=parsed.get("breakfast", False)
        )
        await state.set_state(CheckInStates.step_7_rules)

        # Send rules
        rules = data_loader.get_rules()
        rules_text = f"""
Шаг 7 из 7: Пожалуйста, ознакомьтесь с правилами турбазы:

{rules.get('text', 'Правила турбазы доступны на ресепшене')}

Вы принимаете правила? (Ответьте 'да' или 'принимаю')
"""
        await message.answer(rules_text)

    except Exception as e:
        logger.exception(f"Services parsing error: {e}")
        await message.answer("Не удалось распознать ответ. Пожалуйста, уточните, какие услуги вам нужны.")

@router.message(CheckInStates.step_7_rules)
async def process_step_7_rules(message: types.Message, state: FSMContext):
    """Step 7: Accept rules and complete the card"""
    # Guard clause: ignore commands
    if message.text and message.text.startswith("/"):
        return

    parsing_prompt = """
Determine if the guest accepts the rules.
Return JSON with: {"rules_accepted": boolean}
"""

    try:
        response = await llm_service.client.chat.completions.create(
            model="openrouter/free",
            messages=[
                {"role": "system", "content": parsing_prompt},
                {"role": "user", "content": message.text}
            ],
            temperature=0.1
        )

        content = response.choices[0].message.content
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        import json
        parsed = json.loads(content)
        rules_accepted = parsed.get("rules_accepted", False)

        if not rules_accepted:
            # Escalate to human
            data = await state.get_data()
            booking_id = data["booking_id"]

            async for session in get_session():
                result = await session.execute(
                    select(Booking).where(Booking.booking_id == booking_id)
                )
                booking_record = result.scalar_one_or_none()

                if booking_record:
                    booking_record.status = "needs_human"
                    booking_record.rules_accepted = False
                    await session.commit()

            await message.answer("Правила не приняты. Ваш запрос передан администратору.")
            await state.set_state(CheckInStates.needs_human)
            return

        # Save all data to database
        data = await state.get_data()
        booking_id = data["booking_id"]
        guest_name = data.get("guest_name", "")

        async for session in get_session():
            result = await session.execute(
                select(Booking).where(Booking.booking_id == booking_id)
            )
            booking_record = result.scalar_one_or_none()

            if not booking_record:
                await message.answer("Ошибка при сохранении данных.")
                return

            # Update booking with collected data
            booking_record.guest_adults = data.get("adults")
            booking_record.guest_children = data.get("children")
            booking_record.arrival_time = data.get("arrival_time")
            booking_record.has_car = data.get("has_car")
            booking_record.car_plates = data.get("car_plates", [])
            booking_record.has_pet = data.get("has_pet")
            booking_record.extra_bed_requested = data.get("extra_bed_requested")
            booking_record.early_arrival_requested = data.get("early_arrival_requested")
            booking_record.breakfast_requested = data.get("breakfast_requested")
            booking_record.rules_accepted = True
            booking_record.rules_version = data_loader.get_rules().get("version")
            booking_record.rules_accepted_at = datetime.utcnow()
            booking_record.updated_at = datetime.utcnow()

            # Calculate costs
            booking_data = {
                "booking_id": booking_record.booking_id,
                "guest_name": guest_name,
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

            costs = business_logic.calculate_total_cost(booking_data)
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
                guest_card.pdf_path = f"{booking_id}_card.pdf"
                guest_card.updated_at = datetime.utcnow()
                await session.commit()

            booking_record.status = "ready"
            await session.commit()

        # Send confirmation
        booking = data_loader.get_booking_by_id(booking_id)
        confirmation_text = f"""
Спасибо! Ваша карточка готова.

📋 Ваша бронь: {booking_id}
🏠 Домик: {booking['house_id']}
📅 Заезд: {booking['arrival_date']} в {data.get('arrival_time')}
📅 Выезд: {booking['departure_date']}

👥 Гостей: {data.get('adults')} взрослых, {data.get('children')} детей
🚗 Автомобиль: {'Да' if data.get('has_car') else 'Нет'}
"""

        if data.get('has_car') and kpp_string:
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

        # Generate PDF card
        try:
            pdf_path = pdf_service.generate_guest_card(booking_id, booking_data, costs, kpp_string)
            if pdf_path:
                logger.info(f"PDF card generated: {pdf_path}")
        except Exception as e:
            logger.exception(f"Failed to generate PDF card: {e}")

    except Exception as e:
        logger.exception(f"Rules processing error: {e}")
        await message.answer("Не удалось обработать ответ. Пожалуйста, попробуйте еще раз.")

@router.message(CheckInStates.ready)
async def handle_ready_state(message: types.Message, state: FSMContext):
    """Handle messages when card is ready"""
    # Guard clause: ignore commands
    if message.text and message.text.startswith("/"):
        return

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
    # Guard clause: ignore commands
    if message.text and message.text.startswith("/"):
        return

    await message.answer("Ваш запрос обрабатывается администратором. Телефон службы бронирования: +7 (844) 255-38-43")

# Command to start check-in
@router.message()
async def handle_unknown_message(message: types.Message, state: FSMContext):
    """Handle unknown messages"""
    # Don't block /start or /travel_time commands - they have their own handlers
    if message.text and message.text.startswith("/"):
        return  # Let command handlers process these

    current_state = await state.get_state()
    if current_state is None:
        await message.answer("Пожалуйста, начните с команды /start <токен>")
        await state.set_state(CheckInStates.waiting_for_start)
