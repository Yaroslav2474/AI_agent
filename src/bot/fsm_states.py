from aiogram.fsm.state import State, StatesGroup

class CheckInStates(StatesGroup):
    waiting_for_start = State()
    collecting_info = State()
    confirming_rules = State()
    ready = State()
    needs_human = State()
