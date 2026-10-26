"""
Price guide for the sell page. Uses only real Campus Swap prices:

1. what similar items actually sold for (the agreed price on paid transactions), or
2. what similar items for sale right now are asking.

It says nothing at all until at least 3 real prices exist, so it never shows
an invented number.
"""

from app.extensions import db
from app.models import (
    Listing, ListingStatus, ListingType, ListingCondition,
    Transaction, TransactionStatus, TransactionType,
)
from app.pricing_rules import summarise_prices

SOLD_STATUSES = (TransactionStatus.PAID, TransactionStatus.READY_FOR_PICKUP, TransactionStatus.COMPLETED)
NOT_ENOUGH = ("Not enough similar items on Campus Swap yet. The guide appears once at least 3 similar "
              "items have sold or are listed for sale.")


def _sold(category_id, condition):
    q = (db.session.query(Transaction.item_price).join(Listing, Transaction.listing_id == Listing.id)
         .filter(Listing.category_id == category_id, Transaction.transaction_type == TransactionType.PURCHASE,
                 Transaction.status.in_(SOLD_STATUSES)))
    if condition is not None:
        q = q.filter(Listing.condition == condition)
    return [row[0] for row in q.all()]


def _asking(category_id, condition):
    q = db.session.query(Listing.price).filter(
        Listing.category_id == category_id, Listing.listing_type == ListingType.SELL,
        Listing.status == ListingStatus.ACTIVE)
    if condition is not None:
        q = q.filter(Listing.condition == condition)
    return [row[0] for row in q.all()]


def price_guide(category_id, condition_value=None):
    try:
        condition = ListingCondition(condition_value) if condition_value else None
    except ValueError:
        condition = None

    attempts = []
    for source, getter, noun in (("sold", _sold, "completed sales"),
                                 ("asking", _asking, "items for sale now")):
        if condition is not None:
            attempts.append((getter, condition, noun, f"in the same condition ({condition.value})"))
        attempts.append((getter, None, noun, "in this category"))

    for getter, cond, noun, scope in attempts:
        summary = summarise_prices(getter(category_id, cond))
        if summary:
            return {"available": True, "low": float(summary["low"]), "median": float(summary["median"]),
                    "high": float(summary["high"]), "count": summary["count"],
                    "basis": f"{summary['count']} {noun} {scope}"}
    return {"available": False, "message": NOT_ENOUGH}
