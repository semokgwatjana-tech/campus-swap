"""
Price rules for offers and receipts. Pure functions only (no database, no
Flask), so they can be tested on their own. app/pricing.py applies them to
real listings and messages.

Rule in one line: a price from chat counts only when the other person pressed
Accept, it is lower than the listed price, and it is still inside its time window.
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal("0.01")


def money(value):
    """Round to whole cents, the way a receipt shows it."""
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def offer_error(listed_price, amount, symbol="R"):
    """Why an offer amount is not allowed, or None if it is fine."""
    try:
        amount = money(amount)
    except Exception:
        return "Enter a valid offer price."
    listed = money(listed_price)
    if amount <= 0:
        return f"An offer must be more than {symbol}0."
    if amount >= listed:
        return f"An offer must be lower than the listed price ({symbol}{listed})."
    return None


def offer_state(status, sent_at, responded_at, now, valid_hours):
    """How an offer is shown and treated right now.

    legacy    sent before offers could be accepted (no status stored)
    pending   waiting for the other person
    accepted  the other person pressed Accept and the price can be used at checkout
    declined, withdrawn, used (already paid for)
    expired   not answered, or accepted but not used, within valid_hours
    """
    if status is None:
        return "legacy"
    if status in ("declined", "withdrawn", "used"):
        return status
    window = timedelta(hours=valid_hours)
    if status == "pending":
        return "pending" if now < sent_at + window else "expired"
    if status == "accepted":
        return "accepted" if now < (responded_at or sent_at) + window else "expired"
    return "expired"


def choose_price(listed_price, offer_price):
    """Return (price, source). A chat offer is used only when it is really
    lower than the listed price; otherwise the listed price is used."""
    listed = money(listed_price)
    if offer_price is not None:
        offer = money(offer_price)
        if 0 < offer < listed:
            return offer, "chat_offer"
    return listed, "listing"


def difference(listed_price, paid_price):
    """Listed price minus the price actually used (zero or more)."""
    return money(listed_price) - money(paid_price)


def summarise_prices(prices, minimum=3):
    """Low, middle (median) and high of real prices, or None when there are too
    few to say anything honest."""
    from statistics import median
    cleaned = sorted(money(p) for p in prices if p is not None and money(p) > 0)
    if len(cleaned) < minimum:
        return None
    return {"low": cleaned[0], "median": money(median(cleaned)), "high": cleaned[-1], "count": len(cleaned)}
