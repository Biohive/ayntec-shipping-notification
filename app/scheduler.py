"""Background scheduler that polls Ayntec for order status every N seconds."""

import asyncio
import datetime
import logging
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import Order, NotificationSetting, CheckLog, SummaryConfig
from app.checker import fetch_shipped_ranges, check_order_shipped
from app.notifiers import send_discord, send_email, send_ntfy
from app.notifiers import send_discord_summary, send_email_summary, send_ntfy_summary

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

        # Log a check entry per unique user that has active unnotified orders
        now = datetime.datetime.utcnow()
        seen_user_ids: set[int] = set()
        for order in orders:
            if order.user_id not in seen_user_ids:
                seen_user_ids.add(order.user_id)
                db.add(CheckLog(user_id=order.user_id, checked_at=now))
        db.commit()

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


async def send_daily_summaries() -> None:
    """Send daily summary messages to users whose configured delivery time has arrived."""
    now = datetime.datetime.utcnow()
    db: Session = SessionLocal()
    try:
        configs = (
            db.query(SummaryConfig)
            .filter(SummaryConfig.enabled == True)  # noqa: E712
            .all()
        )
        for config in configs:
            await _maybe_send_summary(db, config, now)
    finally:
        db.close()


async def _maybe_send_summary(
    db: Session, config: SummaryConfig, now: datetime.datetime
) -> None:
    """Send a summary for *config* if the delivery time has arrived and it hasn't been sent today."""
    # Resolve the user's timezone; fall back to UTC on any error
    try:
        tz = ZoneInfo(config.timezone or "UTC")
    except (ZoneInfoNotFoundError, KeyError):
        logger.warning(
            "Unknown timezone %r for summary config user_id=%s – falling back to UTC",
            config.timezone, config.user_id,
        )
        tz = ZoneInfo("UTC")

    # Convert UTC now to the user's local time for comparison
    now_local = now.replace(tzinfo=datetime.timezone.utc).astimezone(tz)

    if now_local.hour != config.delivery_hour or now_local.minute != config.delivery_minute:
        return

    # Prevent sending more than once per calendar day (in the user's local timezone)
    if config.last_sent_at:
        last_local = config.last_sent_at.replace(tzinfo=datetime.timezone.utc).astimezone(tz)
        if last_local.date() == now_local.date():
            return

    # Skip if the user has no active orders at all
    orders = (
        db.query(Order)
        .filter(Order.user_id == config.user_id, Order.active == True)  # noqa: E712
        .all()
    )
    if not orders:
        return

    # Count how many times the service checked for this user in the last 24 hours
    since = now - datetime.timedelta(hours=24)
    check_count = (
        db.query(CheckLog)
        .filter(
            CheckLog.user_id == config.user_id,
            CheckLog.checked_at >= since,
        )
        .count()
    )

    shipped_orders = [o for o in orders if o.shipped]
    pending_orders = [o for o in orders if not o.shipped]

    notif: NotificationSetting | None = (
        db.query(NotificationSetting)
        .filter(NotificationSetting.user_id == config.user_id)
        .first()
    )

    await _dispatch_summary(db, config, notif, shipped_orders, pending_orders, check_count)

    config.last_sent_at = now
    db.commit()


async def _dispatch_summary(
    db: Session,
    config: SummaryConfig,
    notif: NotificationSetting | None,
    shipped_orders: list,
    pending_orders: list,
    check_count: int,
) -> None:
    if not notif:
        return

    tasks = []
    if config.use_discord and notif.discord_enabled and notif.discord_webhook_url:
        tasks.append(
            send_discord_summary(
                notif.discord_webhook_url, shipped_orders, pending_orders, check_count
            )
        )
    if config.use_ntfy and notif.ntfy_enabled and notif.ntfy_url:
        tasks.append(
            send_ntfy_summary(
                notif.ntfy_url, shipped_orders, pending_orders, check_count
            )
        )
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

    if config.use_email and notif.email_enabled and notif.email_address:
        try:
            send_email_summary(
                notif.email_address, shipped_orders, pending_orders, check_count
            )
        except Exception as exc:
            logger.error("Summary email failed for user %s: %s", config.user_id, exc)


def start_scheduler() -> None:
    scheduler.add_job(
        check_all_orders,
        trigger=IntervalTrigger(seconds=settings.poll_interval_seconds),
        id="check_orders",
        replace_existing=True,
        misfire_grace_time=60,
    )
    scheduler.add_job(
        send_daily_summaries,
        trigger=IntervalTrigger(seconds=60),
        id="daily_summaries",
        replace_existing=True,
        misfire_grace_time=30,
    )
    scheduler.start()
    logger.info(
        "Scheduler started – polling every %d seconds", settings.poll_interval_seconds
    )


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
