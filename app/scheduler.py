"""Background scheduler that polls Ayntec for order status every N seconds."""

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import Order, NotificationSetting
from app.checker import fetch_shipped_ranges, check_order_shipped
from app.notifiers import send_discord, send_email, send_ntfy

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def check_all_orders() -> None:
    """Poll the Ayntec dashboard and check every active, non-notified order."""
    db: Session = SessionLocal()
    try:
        orders = (
            db.query(Order)
            .filter(Order.active == True, Order.notified == False)  # noqa: E712
            .all()
        )

        if not orders:
            return

        logger.info("Checking %d active order(s)…", len(orders))

        # Fetch the shipping dashboard once for all orders
        shipped_ranges = await fetch_shipped_ranges()
        if not shipped_ranges:
            logger.warning("No shipped ranges found on dashboard – skipping this cycle")
            return

        for order in orders:
            await _check_order(db, order, shipped_ranges)

    finally:
        db.close()


async def _check_order(db: Session, order: Order, shipped_ranges: list) -> None:
    status_text, is_shipped = check_order_shipped(order.order_number, shipped_ranges)

    order.last_status = status_text

    if is_shipped and not order.notified:
        order.shipped = True
        order.notified = True
        db.commit()
        logger.info("Order %s shipped – sending notifications", order.order_number)
        await _dispatch_notifications(db, order, status_text)
    else:
        db.commit()


async def _dispatch_notifications(db: Session, order: Order, status_text: str) -> None:
    settings_row: NotificationSetting | None = (
        db.query(NotificationSetting)
        .filter(NotificationSetting.user_id == order.user_id)
        .first()
    )

    if not settings_row:
        return

    tasks = []
    if settings_row.discord_enabled and settings_row.discord_webhook_url:
        tasks.append(send_discord(settings_row.discord_webhook_url, order.order_number, status_text))

    if settings_row.ntfy_enabled and settings_row.ntfy_url:
        tasks.append(send_ntfy(settings_row.ntfy_url, order.order_number, status_text))

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

    # Email is synchronous
    if settings_row.email_enabled and settings_row.email_address:
        try:
            send_email(settings_row.email_address, order.order_number, status_text)
        except Exception as exc:
            logger.error("Email notification failed for order %s: %s", order.order_number, exc)


def start_scheduler() -> None:
    scheduler.add_job(
        check_all_orders,
        trigger=IntervalTrigger(seconds=settings.poll_interval_seconds),
        id="check_orders",
        replace_existing=True,
        misfire_grace_time=60,
    )
    scheduler.start()
    logger.info(
        "Scheduler started – polling every %d seconds", settings.poll_interval_seconds
    )


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
