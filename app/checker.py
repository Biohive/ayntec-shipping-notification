"""Ayntec shipment dashboard checker.

Scrapes the Ayntec shipping dashboard page to find order-number ranges that
have been shipped, then checks whether tracked orders fall within any of
those ranges.

The dashboard lists dates followed by product/range lines such as::

    2026/3/4
    AYN Thor Black Lite: 1500xx--1633xx
    AYN Thor Black Max: 1464xx--1506xx

The ``xx`` wildcard digits are expanded into a numeric range
(e.g. 1500xx → 150 000–150 099, so the full range 1500xx--1633xx covers
150 000–163 399).

The dashboard URL is configurable via AYNTEC_DASHBOARD_URL in .env.
"""

import re
import logging
from dataclasses import dataclass

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class ShippedRange:
    """A range of shipped order numbers for a specific product and date."""

    date: str
    product: str
    range_low: int   # inclusive lower bound (e.g. 150000)
    range_high: int  # inclusive upper bound (e.g. 163399)


# Matches lines like "AYN Thor Black Lite: 1500xx--1633xx"
_RANGE_RE = re.compile(
    r"([A-Z][^:\n]+?):\s*(\d+)(x+)\s*-{1,2}\s*(\d+)(x+)",
    re.IGNORECASE,
)

# Matches date headers like "2026/3/4"
_DATE_RE = re.compile(r"\d{4}/\d{1,2}/\d{1,2}")


async def fetch_shipped_ranges() -> list[ShippedRange]:
    """Fetch the Ayntec shipping dashboard and return all shipped ranges."""
    url = settings.ayntec_dashboard_url
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; AyntecShippingNotifier/1.0; "
            "+https://github.com/Biohive/ayntec-shipping-notification)"
        )
    }
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)

        if resp.status_code != 200:
            logger.warning("Dashboard returned HTTP %s", resp.status_code)
            return []

        return _parse_dashboard(resp.text)

    except httpx.RequestError as exc:
        logger.error("Failed to fetch shipping dashboard: %s", exc)
        return []


def _parse_dashboard(html: str) -> list[ShippedRange]:
    """Parse shipped order-number ranges from the dashboard HTML."""
    # Strip HTML tags to get plain text
    text = re.sub(r"<[^>]+>", "\n", html)

    ranges: list[ShippedRange] = []
    current_date: str | None = None

    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue

        # Check for a date header
        date_match = _DATE_RE.match(line)
        if date_match:
            current_date = date_match.group(0)
            continue

        # Look for product: range entries (may be multiple per line)
        if current_date:
            for m in _RANGE_RE.finditer(line):
                product = m.group(1).strip()
                start_prefix = int(m.group(2))
                start_wc = len(m.group(3))
                end_prefix = int(m.group(4))
                end_wc = len(m.group(5))

                range_low = start_prefix * (10 ** start_wc)
                range_high = end_prefix * (10 ** end_wc) + (10 ** end_wc) - 1

                ranges.append(ShippedRange(
                    date=current_date,
                    product=product,
                    range_low=range_low,
                    range_high=range_high,
                ))

    logger.info("Parsed %d shipped ranges from dashboard", len(ranges))
    return ranges


def check_order_shipped(
    order_number: str, ranges: list[ShippedRange]
) -> tuple[str, bool]:
    """Check whether *order_number* falls within any shipped range.

    Returns ``(status_text, is_shipped)``.
    """
    cleaned = order_number.strip().lstrip("#")
    try:
        order_int = int(cleaned)
    except ValueError:
        return "invalid order number", False

    for r in ranges:
        if r.range_low <= order_int <= r.range_high:
            return f"Shipped ({r.product}, {r.date})", True

    return "Not yet shipped", False
