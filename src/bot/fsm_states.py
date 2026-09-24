from aiogram.fsm.state import State, StatesGroup

class CheckInStates(StatesGroup):
    waiting_for_start = State()
    step_1_name = State()  # ФИО гостя
    step_2_guests = State()  # Количество взрослых и детей
    step_3_time = State()  # Время прибытия
    step_4_car = State()  # Наличие автомобиля и госномер
    step_5_pet = State()  # Наличие питомцев
    step_6_services = State()  # Дополнительные услуги
    step_7_rules = State()  # Принятие правил
    ready = State()
    needs_human = State()
