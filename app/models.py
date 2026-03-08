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


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    order_number = Column(String, nullable=False)
    label = Column(String, nullable=True)  # optional friendly label
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
