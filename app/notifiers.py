"""Notification dispatchers: Discord, Email (SMTP), NTFY."""

import logging
import smtplib
from email.mime.text import MIMEText

import httpx

from app.config import settings
from app.security import validate_webhook_url

logger = logging.getLogger(__name__)


def _build_summary_body(shipped_orders: list, pending_orders: list, check_count: int) -> tuple[str, bool]:
    """Build a plain-text daily summary body shared across all notification channels.

    Returns ``(body_text, all_shipped)`` so callers can customise the subject line
    without recomputing the shipped state.
    """
    all_shipped = not pending_orders and bool(shipped_orders)
    lines: list[str] = []

    if all_shipped:
        lines.append("🎉 All your Ayntec orders have shipped!")
    elif shipped_orders:
        lines.append("📦 Here is your Ayntec daily shipment update:")
    else:
        lines.append("📦 Ayntec Daily Summary")
        lines.append(f"No new shipments detected today. Service checked {check_count} time(s) in the last 24 hours.")
        lines.append(f"Tracking {len(pending_orders)} pending order(s).")
        return "\n".join(lines), all_shipped

    lines.append("")
    for order in shipped_orders:
        label = f" ({order.label})" if order.label else ""
        status = order.last_status or "Shipped"
        lines.append(f"  ✅ Order #{order.order_number}{label}: {status}")
    for order in pending_orders:
        label = f" ({order.label})" if order.label else ""
        lines.append(f"  ⏳ Order #{order.order_number}{label}: Not yet shipped")

    lines.append("")
    lines.append(f"Service checked {check_count} time(s) in the last 24 hours.")
    return "\n".join(lines), all_shipped


async def send_discord(webhook_url: str, order_number: str, status: str) -> None:
    validate_webhook_url(webhook_url, label="Discord webhook URL")
    message = (
        f"📦 **Ayntec Order Update**\n"
        f"Order **#{order_number}** has shipped!\n"
        f"Status: `{status}`"
    )
    payload = {"content": message}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(webhook_url, json=payload)
            resp.raise_for_status()
            logger.info("Discord notification sent for order %s", order_number)
    except httpx.RequestError as exc:
        logger.error("Discord notification failed for order %s: %s", order_number, exc)
        raise


async def send_discord_summary(
    webhook_url: str, shipped_orders: list, pending_orders: list, check_count: int
) -> None:
    validate_webhook_url(webhook_url, label="Discord webhook URL")
    body, _ = _build_summary_body(shipped_orders, pending_orders, check_count)
    payload = {"content": body}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(webhook_url, json=payload)
            resp.raise_for_status()
            logger.info("Discord daily summary sent")
    except httpx.RequestError as exc:
        logger.error("Discord daily summary failed: %s", exc)
        raise


async def send_ntfy(ntfy_url: str, order_number: str, status: str) -> None:
    validate_webhook_url(ntfy_url, label="NTFY URL")
    title = f"Ayntec Order #{order_number} Shipped!"
    body = f"Your order has shipped. Status: {status}"
    headers = {
        "Title": title,
        "Priority": "high",
        "Tags": "package,shipping",
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(ntfy_url, data=body.encode(), headers=headers)
            resp.raise_for_status()
            logger.info("NTFY notification sent for order %s", order_number)
    except httpx.RequestError as exc:
        logger.error("NTFY notification failed for order %s: %s", order_number, exc)
        raise


async def send_ntfy_summary(
    ntfy_url: str, shipped_orders: list, pending_orders: list, check_count: int
) -> None:
    validate_webhook_url(ntfy_url, label="NTFY URL")
    body, _ = _build_summary_body(shipped_orders, pending_orders, check_count)
    headers = {
        "Title": "Ayntec Daily Summary",
        "Priority": "default",
        "Tags": "package,shipping",
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(ntfy_url, data=body.encode(), headers=headers)
            resp.raise_for_status()
            logger.info("NTFY daily summary sent")
    except httpx.RequestError as exc:
        logger.error("NTFY daily summary failed: %s", exc)
        raise


def send_email(to_address: str, order_number: str, status: str) -> None:
    smtp_host = settings.smtp_host
    smtp_port = settings.smtp_port
    smtp_user = settings.smtp_user
    smtp_pass = settings.smtp_pass
    from_address = settings.smtp_from or smtp_user

    if not smtp_host:
        logger.warning("SMTP not configured – skipping email notification")
        return

    subject = f"Ayntec Order #{order_number} Has Shipped!"
    body = (
        f"Good news! Your Ayntec order #{order_number} has shipped.\n\n"
        f"Status: {status}\n\n"
        f"-- Ayntec Shipping Notifier"
    )

    msg = MIMEText(body, "plain")
    msg["Subject"] = subject
    msg["From"] = from_address
    msg["To"] = to_address

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        if smtp_user and smtp_pass:
            server.login(smtp_user, smtp_pass)
        server.sendmail(from_address, [to_address], msg.as_string())
    logger.info("Email notification sent for order %s to %s", order_number, to_address)


def send_email_summary(
    to_address: str, shipped_orders: list, pending_orders: list, check_count: int
) -> None:
    smtp_host = settings.smtp_host
    smtp_port = settings.smtp_port
    smtp_user = settings.smtp_user
    smtp_pass = settings.smtp_pass
    from_address = settings.smtp_from or smtp_user

    if not smtp_host:
        logger.warning("SMTP not configured – skipping summary email")
        return

    body, all_shipped = _build_summary_body(shipped_orders, pending_orders, check_count)
    subject = (
        "Ayntec Daily Summary – All Orders Shipped! 🎉"
        if all_shipped
        else "Ayntec Daily Summary"
    )
    body += "\n\n-- Ayntec Shipping Notifier"

    msg = MIMEText(body, "plain")
    msg["Subject"] = subject
    msg["From"] = from_address
    msg["To"] = to_address

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        if smtp_user and smtp_pass:
            server.login(smtp_user, smtp_pass)
        server.sendmail(from_address, [to_address], msg.as_string())
    logger.info("Summary email sent to %s", to_address)
