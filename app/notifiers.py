"""Notification dispatchers: Discord, Email (SMTP), NTFY."""

import logging
import smtplib
from email.mime.text import MIMEText

import httpx

from app.config import settings
from app.security import validate_webhook_url

logger = logging.getLogger(__name__)


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
