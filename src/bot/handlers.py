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
            await message.answer("Шаг 1 из 7: Введите ФИО (отчество - при наличии)")
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
            await message.answer("Шаг 1 из 7: Введите ФИО (отчество - при наличии)")

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
    """Step 2: Parse number of adults and children using AI with Python fallback"""
    # Guard clause: ignore commands
    if message.text and message.text.startswith("/"):
        return

    parsing_prompt = """
Extract the number of adults and children from the message.
Return JSON with: {"adults": integer, "children": integer}
CRITICAL RULES:
- If only total number is given (e.g., "нас будет трое"), assume all are adults.
- If children are NOT mentioned at all, ALWAYS set children to 0 (never null or undefined).
- Examples: "два взрослых" -> {"adults": 2, "children": 0}, "двое" -> {"adults": 2, "children": 0}
"""

    adults = 0
    children = 0

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
        
        # Ensure children is never None
        if children is None:
            children = 0

    except Exception as e:
        logger.exception(f"AI guest count parsing error: {e}, using Python fallback")
        # Python fallback with regex patterns
        text_lower = message.text.lower()
        
        # Pattern matching for common phrases
        import re
        
        # Match "два взрослых", "2 взрослых", "двое", etc.
        if re.search(r'два\s+взрослых|2\s+взрослых|двое|двух\s+взрослых', text_lower):
            adults = 2
            children = 0
        elif re.search(r'три\s+взрослых|3\s+взрослых|трое|трех\s+взрослых', text_lower):
            adults = 3
            children = 0
        elif re.search(r'четыре\s+взрослых|4\s+взрослых|четверо|четырех\s+взрослых', text_lower):
            adults = 4
            children = 0
        elif re.search(r'один\s+взрослый|1\s+взрослый|один|сам', text_lower):
            adults = 1
            children = 0
        else:
            # Try to extract any number as adults count
            numbers = re.findall(r'\d+', text_lower)
            if numbers:
                adults = int(numbers[0])
                children = 0
            else:
                await message.answer("Не удалось распознать количество гостей. Пожалуйста, укажите число взрослых и детей (например: '2 взрослых' или 'нас будет трое').")
                return

    # Validate adults count
    if adults <= 0:
        await message.answer("Пожалуйста, укажите корректное количество взрослых (минимум 1).")
        return

    # Ensure children is always an integer
    if children is None:
        children = 0

    await state.update_data(adults=adults, children=children)
    await state.set_state(CheckInStates.step_3_time)
    await message.answer("Шаг 3 из 7: Во сколько вы планируете прибыть? (например: 'в 2 часа дня' или '14:00')")

@router.message(CheckInStates.step_3_time)
async def process_step_3_time(message: types.Message, state: FSMContext):
    """Step 3: Convert arrival time to HH:MM format using AI with Python fallback"""
    # Guard clause: ignore commands
    if message.text and message.text.startswith("/"):
        return

    parsing_prompt = """
Convert the arrival time to HH:MM format (24-hour).
CRITICAL RULES:
- Convert ANY Russian time expression to HH:MM format
- Examples: "2 часа дня" -> "14:00", "в два дня" -> "14:00", "18:00" -> "18:00", "в 14" -> "14:00"
- Handle word-based expressions: "в час дня" -> "13:00", "в час" -> "13:00", "час дня" -> "13:00"
- Handle approximate times: "около двух дня" -> "14:00", "примерно в 3" -> "15:00"
- Handle noon/midnight: "в полдень" -> "12:00", "в полночь" -> "00:00"
- Handle "первый час" (1 o'clock) -> "13:00" if PM context, "01:00" if AM context
- ALWAYS return ONLY the time string in HH:MM format, no extra text
- Default to :00 minutes if not specified
Return JSON with: {"time": string in HH:MM format}
"""

    time_str = ""

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

    except Exception as e:
        logger.exception(f"AI time parsing error: {e}, using Python fallback")
        # Python fallback for time parsing with enhanced natural language support
        import re
        text_lower = message.text.lower()
        
        # Handle word-based time expressions
        if re.search(r'в\s+час\s+дня|час\s+дня|в\s+час', text_lower):
            time_str = "13:00"  # "в час дня" = 1 PM = 13:00
        elif re.search(r'в\s+полдень|полдень', text_lower):
            time_str = "12:00"  # noon
        elif re.search(r'в\s+полночь|полночь', text_lower):
            time_str = "00:00"  # midnight
        elif re.search(r'первый\s+час|один\s+час', text_lower):
            # Check if PM context
            if any(keyword in text_lower for keyword in ['дня', 'вечера', 'pm']):
                time_str = "13:00"  # 1 PM
            else:
                time_str = "01:00"  # 1 AM (default)
        elif re.search(r'второй\s+час|два\s+часа|два', text_lower):
            # Check if PM context
            if any(keyword in text_lower for keyword in ['дня', 'вечера', 'pm']):
                time_str = "14:00"  # 2 PM
            else:
                time_str = "02:00"  # 2 AM (default)
        else:
            # Try to extract hour number
            hour_match = re.search(r'(\d{1,2})', text_lower)
            if hour_match:
                hour = int(hour_match.group(1))
                
                # Check for PM indicators (дня, вечера, после полудня)
                if any(keyword in text_lower for keyword in ['дня', 'вечера', 'после полудня', 'pm']):
                    if hour < 12:
                        hour += 12
                
                # Check for AM indicators (утра, ночи, до полудня)
                elif any(keyword in text_lower for keyword in ['утра', 'ночи', 'до полудня', 'am']):
                    if hour == 12:
                        hour = 0
                
                # Clamp to valid range
                hour = max(0, min(23, hour))
                time_str = f"{hour:02d}:00"
            else:
                await message.answer("Не удалось распознать время. Пожалуйста, укажите время в формате ЧЧ:ММ (например: '14:00' или 'в 2 часа дня').")
                return

    # Clean and validate time format
    # Apply the same cleaning logic as in business_logic.validate_time_format
    time_str = time_str.strip()
    import re
    time_str = re.sub(r'[\[\(].*?[\]\)]$', '', time_str).strip()
    time_str = re.sub(r'\s*[-–]\s*[^\d:]+$', '', time_str).strip()
    time_str = re.sub(r'[^\d:]', '', time_str)
    
    if not business_logic.validate_time_format(time_str):
        await message.answer("Пожалуйста, укажите время в корректном формате (например: '14:00' или 'в 2 часа дня').")
        return

    await state.update_data(arrival_time=time_str)
    await state.set_state(CheckInStates.step_4_car)
    await message.answer("Шаг 4 из 7: Будете ли вы на автомобиле? Если да, укажите госномер.")

@router.message(CheckInStates.step_4_car)
async def process_step_4_car(message: types.Message, state: FSMContext):
    """Step 4: Check for car and parse license plates with strict validation"""
    # Guard clause: ignore commands
    if message.text and message.text.startswith("/"):
        return

    parsing_prompt = """
Determine if the guest has a car and extract license plates.
Return JSON with: {"has_car": boolean, "car_plates": array of strings}
If guest says "без машины" or similar, set has_car to false and car_plates to empty array.
If guest says "да" or "машина есть" but no plate, set has_car to true and car_plates to empty array.
"""

    has_car = False
    car_plates = []

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

    except Exception as e:
        logger.exception(f"AI car parsing error: {e}, using Python fallback")
        # Python fallback
        text_lower = message.text.lower()
        
        # Check if user says they don't have a car
        no_car_keywords = ["без машины", "нет машины", "без авто", "не будет", "не приеду", "не будет машины"]
        if any(keyword in text_lower for keyword in no_car_keywords):
            has_car = False
            car_plates = []
        else:
            # Assume they have a car
            has_car = True
            # Try to extract plates from text
            extracted_plates = business_logic.extract_car_plate_from_text(message.text)
            if extracted_plates:
                car_plates = extracted_plates
            else:
                # If user just said "да" or similar without plate, leave empty to prompt for it
                car_plates = []

    # Check if guest has car but didn't provide plate
    if has_car and not car_plates:
        await message.answer("Вы указали, что приедете на автомобиле. Пожалуйста, введите госномер вашей машины.")
        return

    # Validate and sanitize car plates if provided
    if has_car and car_plates:
        sanitized_plate = business_logic.sanitize_car_plate(car_plates[0])
        
        # Russian plate pattern: 1 letter, 3 digits, 2 letters, 2-3 digits
        import re
        russian_pattern = r'^[А-Яа-яA-Za-z]\d{3}[А-Яа-яA-Za-z]{2}\d{2,3}$'
        
        if re.match(russian_pattern, sanitized_plate):
            # Valid Russian plate
            car_plates[0] = sanitized_plate
        else:
            # Check if it looks like a foreign plate (contains letters and digits but doesn't match Russian pattern)
            has_letters = bool(re.search(r'[A-Za-zА-Яа-я]', sanitized_plate))
            has_digits = bool(re.search(r'\d', sanitized_plate))
            
            if has_letters and has_digits:
                # Accept as foreign plate (save as-is)
                car_plates[0] = sanitized_plate
            else:
                # Invalid plate format
                await message.answer("Неверный формат госномера. Пожалуйста, введите корректный номер (например: с999аа34 для российского номера или любой другой формат для иностранного).")
                return

    await state.update_data(has_car=has_car, car_plates=car_plates if has_car else [])
    await state.set_state(CheckInStates.step_5_pet)
    await message.answer("Шаг 5 из 7: Будете ли вы с питомцем?")

@router.message(CheckInStates.step_5_pet)
async def process_step_5_pet(message: types.Message, state: FSMContext):
    """Step 5: Check for pets with Python fallback"""
    # Guard clause: ignore commands
    if message.text and message.text.startswith("/"):
        return

    parsing_prompt = """
Determine if the guest has a pet.
Return JSON with: {"has_pet": boolean}
"""

    has_pet = False

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

    except Exception as e:
        logger.exception(f"AI pet parsing error: {e}, using Python fallback")
        # Python fallback with keyword matching
        text_lower = message.text.lower()
        pet_keywords = ["да", "собака", "кот", "кошка", "питомец", "с животным", "с собакой", "с котом", "с кошкой", "животное"]
        no_pet_keywords = ["нет", "без", "не будет", "никаких", "без питомца", "без животного"]
        
        if any(keyword in text_lower for keyword in pet_keywords):
            has_pet = True
        elif any(keyword in text_lower for keyword in no_pet_keywords):
            has_pet = False
        else:
            # If unclear, assume no pet
            has_pet = False

    await state.update_data(has_pet=has_pet)
    await state.set_state(CheckInStates.step_6_services)
    await message.answer("Шаг 6 из 7: Нужны ли дополнительные услуги? (дополнительное место, ранний заезд, завтрак)")

@router.message(CheckInStates.step_6_services)
async def process_step_6_services(message: types.Message, state: FSMContext):
    """Step 6: Parse additional services with Python fallback"""
    # Guard clause: ignore commands
    if message.text and message.text.startswith("/"):
        return

    parsing_prompt = """
Extract which additional services are requested.
Return JSON with: {"extra_bed": boolean, "early_arrival": boolean, "breakfast": boolean}
"""

    extra_bed = False
    early_arrival = False
    breakfast = False

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

        extra_bed = parsed.get("extra_bed", False)
        early_arrival = parsed.get("early_arrival", False)
        breakfast = parsed.get("breakfast", False)

    except Exception as e:
        logger.exception(f"AI services parsing error: {e}, using Python fallback")
        # Python fallback with keyword matching
        text_lower = message.text.lower()
        
        # Extra bed keywords
        extra_bed_keywords = ["дополнительное место", "доп место", "extra bed", "лишнее место"]
        extra_bed = any(keyword in text_lower for keyword in extra_bed_keywords)
        
        # Early arrival keywords
        early_arrival_keywords = ["ранний заезд", "раннее прибытие", "early arrival", "заранее"]
        early_arrival = any(keyword in text_lower for keyword in early_arrival_keywords)
        
        # Breakfast keywords
        breakfast_keywords = ["завтрак", "breakfast", "питание", "еда"]
        breakfast = any(keyword in text_lower for keyword in breakfast_keywords)

    await state.update_data(
        extra_bed_requested=extra_bed,
        early_arrival_requested=early_arrival,
        breakfast_requested=breakfast
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

@router.message(CheckInStates.step_7_rules)
async def process_step_7_rules(message: types.Message, state: FSMContext):
    """Step 7: Accept rules and complete the card with Python fallback"""
    # Guard clause: ignore commands
    if message.text and message.text.startswith("/"):
        return

    parsing_prompt = """
Determine if the guest accepts the rules.
Return JSON with: {"rules_accepted": boolean}
"""

    rules_accepted = False

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

    except Exception as e:
        logger.exception(f"AI rules parsing error: {e}, using Python fallback")
        # Python fallback with keyword matching
        text_lower = message.text.lower()
        accept_keywords = ["да", "принимаю", "согласен", "согласна", "ок", "yes", "принято"]
        reject_keywords = ["нет", "не принимаю", "не согласен", "не согласна", "no", "отказываюсь"]
        
        if any(keyword in text_lower for keyword in accept_keywords):
            rules_accepted = True
        elif any(keyword in text_lower for keyword in reject_keywords):
            rules_accepted = False
        else:
            # If unclear, ask for clarification
            await message.answer("Пожалуйста, уточните: принимаете ли вы правила? (Ответьте 'да' или 'нет')")
            return

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

    try:
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
