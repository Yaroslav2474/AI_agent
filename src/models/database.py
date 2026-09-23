from sqlalchemy import Column, String, Integer, Boolean, DateTime, Text, JSON, ForeignKey, Numeric
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime

Base = declarative_base()

class Booking(Base):
    __tablename__ = "bookings"

    booking_id = Column(String, primary_key=True)
    arrival_date = Column(String, nullable=False)
    departure_date = Column(String, nullable=False)
    category = Column(String, nullable=False)
    house_id = Column(String, nullable=False)
    guest_name = Column(String, nullable=False)
    phone = Column(String, nullable=True)
    adults = Column(Integer, nullable=False)
    children = Column(Integer, nullable=False)
    payment_status = Column(String, nullable=False)
    group_id = Column(String, nullable=True)
    start_token = Column(String, nullable=False, unique=True)
    note = Column(Text, nullable=True)

    # Guest responses
    guest_adults = Column(Integer, nullable=True)
    guest_children = Column(Integer, nullable=True)
    arrival_time = Column(String, nullable=True)
    has_car = Column(Boolean, nullable=True)
    car_plates = Column(JSON, nullable=True, default=list)
    has_pet = Column(Boolean, nullable=True)
    extra_bed_requested = Column(Boolean, nullable=True)
    early_arrival_requested = Column(Boolean, nullable=True)
    breakfast_requested = Column(Boolean, nullable=True)
    rules_accepted = Column(Boolean, nullable=True)
    rules_version = Column(String, nullable=True)
    rules_accepted_at = Column(DateTime, nullable=True)

    # Status
    status = Column(String, default="incomplete")  # ready, incomplete, needs_human
    last_reminder_sent = Column(DateTime, nullable=True)
    reminder_count = Column(Integer, default=0)

    # Additional requests
    human_requests = Column(JSON, nullable=True, default=list)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship with guest card
    guest_card = relationship("GuestCard", back_populates="booking", uselist=False)

class GuestCard(Base):
    __tablename__ = "guest_cards"

    id = Column(Integer, primary_key=True, autoincrement=True)
    booking_id = Column(String, ForeignKey("bookings.booking_id"), unique=True)
    telegram_id = Column(String, nullable=True)
    status = Column(String, default="incomplete")
    additional_info = Column(JSON, nullable=True, default=dict)
    kpp_string = Column(String, nullable=True)
    estimated_cost = Column(JSON, nullable=True, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    booking = relationship("Booking", back_populates="guest_card")

class AdminLog(Base):
    __tablename__ = "admin_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    action = Column(String, nullable=False)
    booking_id = Column(String, nullable=True)
    details = Column(JSON, nullable=True)
    admin_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class TimeSimulation(Base):
    __tablename__ = "time_simulation"

    id = Column(Integer, primary_key=True, autoincrement=True)
    hours_offset = Column(Integer, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow)
