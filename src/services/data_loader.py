import json
import os
from typing import Dict, List, Any

class DataLoader:
    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        self._cache = {}

    def load_json(self, filename: str) -> Dict[str, Any]:
        """Load JSON file and cache it"""
        if filename in self._cache:
            return self._cache[filename]

        filepath = os.path.join(self.data_dir, filename)
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            self._cache[filename] = data
            return data

    def get_bookings(self) -> List[Dict[str, Any]]:
        """Load bookings data"""
        return self.load_json("bookings.json")

    def get_booking_by_token(self, token: str) -> Dict[str, Any]:
        """Find booking by start_token"""
        bookings = self.get_bookings()
        for booking in bookings:
            if booking.get("start_token") == token:
                return booking
        return None

    def get_booking_by_id(self, booking_id: str) -> Dict[str, Any]:
        """Find booking by booking_id"""
        bookings = self.get_bookings()
        for booking in bookings:
            if booking.get("booking_id") == booking_id:
                return booking
        return None

    def get_rules(self) -> Dict[str, Any]:
        """Load rules data"""
        return self.load_json("rules.json")

    def get_prices(self) -> Dict[str, Any]:
        """Load prices data"""
        return self.load_json("prices.json")

    def get_faq(self) -> List[Dict[str, Any]]:
        """Load FAQ data"""
        return self.load_json("faq.json")

    def get_price_by_id(self, price_id: str) -> Dict[str, Any]:
        """Find price item by ID"""
        prices = self.get_prices()
        for item in prices.get("items", []):
            if item.get("id") == price_id:
                return item
        return None

# Global instance
data_loader = DataLoader()
