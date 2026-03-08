"""Notification dispatchers: Discord, Email (SMTP), NTFY."""

import logging
import smtplib
import os
from email.mime.text import MIMEText

import httpx

logger = logging.getLogger(__name__)


async def send_discord(webhook_url: str, order_number: str, status: str) -> None:
    message = (
        f"📦 **Ayntec Order Update**\n"
        f"Order **#{order_number}** has shipped!\n"
        f"Status: `{status}`"
    )
    payload = {"content": message}
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.post(webhook_url, json=payload)
            resp.raise_for_status()
            logger.info("Discord notification sent for order %s", order_number)
        except Exception as exc:
            logger.error("Discord notification failed: %s", exc)


async def send_ntfy(ntfy_url: str, order_number: str, status: str) -> None:
    title = f"Ayntec Order #{order_number} Shipped!"
    body = f"Your order has shipped. Status: {status}"
    headers = {
        "Title": title,
        "Priority": "high",
        "Tags": "package,shipping",
    }
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.post(ntfy_url, data=body.encode(), headers=headers)
            resp.raise_for_status()
            logger.info("NTFY notification sent for order %s", order_number)
        except Exception as exc:
            logger.error("NTFY notification failed: %s", exc)


def send_email(to_address: str, order_number: str, status: str) -> None:
    smtp_host = os.getenv("SMTP_HOST", "")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASS", "")
    from_address = os.getenv("SMTP_FROM", smtp_user)

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

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            if smtp_user and smtp_pass:
                server.login(smtp_user, smtp_pass)
            server.sendmail(from_address, [to_address], msg.as_string())
        logger.info("Email notification sent for order %s to %s", order_number, to_address)
    except Exception as exc:
        logger.error("Email notification failed: %s", exc)
