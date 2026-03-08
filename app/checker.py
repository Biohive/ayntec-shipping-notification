"""Ayntec order status checker.

This module queries the Ayntec website for a given order number and determines
whether the order has shipped.  Because Ayntec does not publish a public API,
we fetch the order status page and look for known shipping-related keywords.

If the Ayntec website changes its HTML structure this function may need to be
updated.  The URL template is configurable via AYNTEC_ORDER_URL in .env so
that operators can adapt without code changes.
"""

import logging
import httpx
from app.config import settings

logger = logging.getLogger(__name__)

# Keywords that indicate an order has shipped (case-insensitive)
SHIPPED_KEYWORDS = [
    "shipped",
    "dispatched",
    "out for delivery",
    "in transit",
    "on the way",
    "delivered",
]


async def fetch_order_status(order_number: str) -> tuple[str, bool]:
    """Return (status_text, is_shipped) for the given order number.

    Fetches the Ayntec order page and searches for shipping keywords.
    Returns a tuple of (status_string, shipped_bool).

    If the page cannot be fetched, returns ("unknown", False).
    """
    url = settings.ayntec_order_url.format(order_id=order_number)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; AyntecShippingNotifier/1.0; "
            "+https://github.com/Biohive/ayntec-shipping-notification)"
        )
    }
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            response = await client.get(url, headers=headers)

        if response.status_code == 200:
            text = response.text.lower()

            # Try to extract a meaningful status line (best-effort)
            status_text = _extract_status(response.text) or "pending"

            is_shipped = any(kw in text for kw in SHIPPED_KEYWORDS)
            return status_text, is_shipped

        logger.warning(
            "Ayntec order page for %s returned HTTP %s", order_number, response.status_code
        )
        return "unavailable", False

    except httpx.RequestError as exc:
        logger.error("Failed to fetch order status for %s: %s", order_number, exc)
        return "error", False


def _extract_status(html: str) -> str | None:
    """Best-effort extraction of a human-readable status string from the page."""
    import re

    # Look for common patterns like "Status: Shipped" or "Order Status: Processing"
    patterns = [
        r"(?:order\s+)?status[:\s]+([A-Za-z ]+)",
        r"(?:shipment|shipping)\s+status[:\s]+([A-Za-z ]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            return match.group(1).strip()[:80]
    return None
