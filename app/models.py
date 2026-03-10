"""SQLAlchemy ORM models."""

import datetime
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, ForeignKey, Text
)
from sqlalchemy.orm import relationship
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    sub = Column(String, unique=True, index=True, nullable=False)  # OIDC subject
    email = Column(String, index=True, nullable=True)
    name = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    orders = relationship("Order", back_populates="user", cascade="all, delete-orphan")
    notification_settings = relationship(
        "NotificationSetting", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    check_logs = relationship("CheckLog", back_populates="user", cascade="all, delete-orphan")
    summary_config = relationship(
        "SummaryConfig", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    order_number = Column(String, nullable=False)
    label = Column(String, nullable=True)  # optional friendly label
    device_type = Column(String, nullable=True)  # full product name, e.g. "AYN Thor Black Pro"
    last_status = Column(String, nullable=True)
    shipped = Column(Boolean, default=False)
    notified = Column(Boolean, default=False)  # prevent duplicate notifications
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    user = relationship("User", back_populates="orders")


class NotificationSetting(Base):
    __tablename__ = "notification_settings"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)

    # Discord
    discord_webhook_url = Column(String, nullable=True)
    discord_enabled = Column(Boolean, default=False)

    # Email
    email_address = Column(String, nullable=True)
    email_enabled = Column(Boolean, default=False)

    # NTFY
    ntfy_url = Column(String, nullable=True)  # e.g. https://ntfy.sh/my-topic
    ntfy_enabled = Column(Boolean, default=False)

    # Track whether each channel has been successfully tested
    discord_tested = Column(Boolean, default=False)
    email_tested = Column(Boolean, default=False)
    ntfy_tested = Column(Boolean, default=False)

    user = relationship("User", back_populates="notification_settings")


class CheckLog(Base):
    """Records each time the scheduler checks a specific user's orders."""

    __tablename__ = "check_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    checked_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="check_logs")


class SummaryConfig(Base):
    """Per-user configuration for the end-of-day summary notification."""

    __tablename__ = "summary_configs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)

    enabled = Column(Boolean, default=False)

    # Delivery time stored in the user's local timezone (hour 0-23, minute 0-59)
    delivery_hour = Column(Integer, default=20)
    delivery_minute = Column(Integer, default=0)
    timezone = Column(String, default="America/New_York")

    # Which enabled notification channels to use for the summary (default off)
    use_discord = Column(Boolean, default=False)
    use_email = Column(Boolean, default=False)
    use_ntfy = Column(Boolean, default=False)

    # Prevents sending the summary more than once per day
    last_sent_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="summary_config")


class ShipmentSnapshot(Base):
    """Latest scraped shipment ranges from the Ayntec dashboard.

    Rebuilt on every successful poll so the public checker tool always
    reflects the most recent data without requiring a user login.
    """

    __tablename__ = "shipment_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    product = Column(String, nullable=False)   # e.g. "AYN Thor Black Pro"
    date = Column(String, nullable=False)       # e.g. "2026/3/4"
    range_low = Column(Integer, nullable=False)
    range_high = Column(Integer, nullable=False)
    fetched_at = Column(DateTime, nullable=False)
