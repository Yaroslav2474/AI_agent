from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from src.services.data_loader import data_loader
import re

class BusinessLogicService:
    def __init__(self):
        self.rules = data_loader.get_rules()
        self.prices = data_loader.get_prices()
        self.faq = data_loader.get_faq()

    def validate_time_format(self, time_str: str) -> bool:
        """Validate time format HH:MM"""
        if not time_str:
            return False
        pattern = r'^([01]?[0-9]|2[0-3]):[0-5][0-9]$'
        return bool(re.match(pattern, time_str))

    def validate_car_plate(self, plate: str) -> bool:
        """Validate car plate format (basic validation)"""
        if not plate:
            return False
        # Basic validation - should be at least 6 characters
        return len(plate) >= 6

    def calculate_nights(self, arrival_date: str, departure_date: str) -> int:
        """Calculate number of nights between dates"""
        try:
            arrival = datetime.strptime(arrival_date, "%Y-%m-%d")
            departure = datetime.strptime(departure_date, "%Y-%m-%d")
            return (departure - arrival).days
        except (ValueError, TypeError):
            return 0

    def calculate_pet_cost(self, nights: int) -> int:
        """Calculate pet cost based on prices.json"""
        pet_price = self.get_price_item("PET")
        if pet_price and pet_price.get("price"):
            return pet_price["price"] * nights
        return 0

    def calculate_coal_cost(self, quantity: int) -> int:
        """Calculate coal cost based on prices.json"""
        coal_price = self.get_price_item("COAL")
        if coal_price and coal_price.get("price"):
            return coal_price["price"] * quantity
        return 0

    def get_price_item(self, item_id: str) -> Optional[Dict[str, Any]]:
        """Get price item by ID"""
        for item in self.prices.get("items", []):
            if item.get("id") == item_id:
                return item
        return None

    def calculate_total_cost(self, booking_data: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate total estimated cost based on guest preferences"""
        costs = {}
        nights = self.calculate_nights(
            booking_data.get("arrival_date"),
            booking_data.get("departure_date")
        )

        # Pet cost
        if booking_data.get("has_pet"):
            pet_cost = self.calculate_pet_cost(nights)
            if pet_cost > 0:
                costs["pet"] = {
                    "item": "Питомец",
                    "price_per_night": self.get_price_item("PET").get("price"),
                    "nights": nights,
                    "total": pet_cost,
                    "requires_confirmation": True
                }

        # Coal cost (if requested)
        coal_quantity = booking_data.get("coal_quantity", 0)
        if coal_quantity > 0:
            coal_cost = self.calculate_coal_cost(coal_quantity)
            if coal_cost > 0:
                costs["coal"] = {
                    "item": "Уголь",
                    "price_per_unit": self.get_price_item("COAL").get("price"),
                    "quantity": coal_quantity,
                    "total": coal_cost,
                    "requires_confirmation": True
                }

        # Early arrival - price unknown
        if booking_data.get("early_arrival_requested"):
            costs["early_arrival"] = {
                "item": "Ранний заезд",
                "price": None,
                "requires_confirmation": True,
                "note": "Цена не указана, требуется подтверждение администратора"
            }

        return costs

    def generate_kpp_string(self, booking_data: Dict[str, Any]) -> Optional[str]:
        """Generate KPP string if has_car=true"""
        if not booking_data.get("has_car"):
            return None

        car_plates = booking_data.get("car_plates", [])
        if not car_plates:
            return None

        # Format: booking_id, arrival_date, arrival_time, house_id, car_plate
        kpp_parts = [
            booking_data.get("booking_id"),
            booking_data.get("arrival_date"),
            booking_data.get("arrival_time"),
            booking_data.get("house_id"),
            car_plates[0] if car_plates else ""
        ]

        return ", ".join(str(part) for part in kpp_parts)

    def check_card_ready(self, booking_data: Dict[str, Any]) -> tuple[bool, List[str]]:
        """Check if guest card is ready for check-in"""
        missing_fields = []
        required_fields = self.rules.get("required_fields", [])

        for field in required_fields:
            value = booking_data.get(field)
            if value is None:
                missing_fields.append(field)

        # Check conditional fields
        conditional_fields = self.rules.get("conditional_fields", {})
        if booking_data.get("has_car") and not booking_data.get("car_plates"):
            missing_fields.append("car_plates")

        # Rules must be accepted
        if not booking_data.get("rules_accepted"):
            missing_fields.append("rules_accepted")

        return len(missing_fields) == 0, missing_fields

    def find_faq_answer(self, question: str) -> Optional[str]:
        """Find FAQ answer by keyword matching"""
        question_lower = question.lower()
        for faq_item in self.faq:
            faq_question = faq_item.get("question", "").lower()
            if any(word in faq_question for word in question_lower.split()):
                return faq_item.get("answer")
        return None

    def is_security_question(self, message: str) -> bool:
        """Check if message contains security-sensitive questions"""
        security_keywords = [
            "фейерверк", "штраф", "правила", "запрет", "наказание",
            "изменить", "перенести", "отменить", "дату"
        ]
        message_lower = message.lower()
        return any(keyword in message_lower for keyword in security_keywords)

    def get_escalation_message(self) -> str:
        """Get standard escalation message"""
        return "Данный вопрос находится вне моей компетенции. Передаю запрос администратору. Телефон службы бронирования: +7 (844) 255-38-43"

# Global instance
business_logic = BusinessLogicService()
