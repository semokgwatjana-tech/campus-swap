"""
Reserving items and finishing trades safely.

The important rule: when two students press Buy at the same moment, exactly one of
them gets the item. The reservation is a single database UPDATE that only succeeds
if the item is still available, so there is no gap for a second buyer to slip into.
"""

from datetime import datetime, timedelta

from flask import current_app

from app.extensions import db
from app.models import (
    Listing, ListingStatus, TransactionStatus, TransactionType, SwapRequest, SwapRequestStatus,
)


def reserve_listing(listing_id, buyer_id, minutes=None):
    """Reserve an available item for one buyer. True only for the one who wins."""
    minutes = minutes or current_app.config["RESERVATION_TIMEOUT_MINUTES"]
    until = datetime.utcnow() + timedelta(minutes=minutes)
    changed = (Listing.query
               .filter(Listing.id == listing_id, Listing.status == ListingStatus.ACTIVE)
               .update({"status": ListingStatus.RESERVED, "reserved_by_id": buyer_id, "reserved_until": until},
                       synchronize_session=False))
    db.session.commit()
    return changed == 1


def release_expired_reservations(now=None):
    """Put every item whose reservation time has run out back on sale."""
    now = now or datetime.utcnow()
    (Listing.query
     .filter(Listing.status == ListingStatus.RESERVED, Listing.reserved_until.isnot(None),
             Listing.reserved_until <= now)
     .update({"status": ListingStatus.ACTIVE, "reserved_by_id": None, "reserved_until": None},
             synchronize_session=False))
    db.session.commit()


def reservation_is_valid(transaction, listing, now=None):
    """Is this buyer still the one the item is held for, and has the time not run out?"""
    now = now or datetime.utcnow()
    return (listing.status == ListingStatus.RESERVED and listing.reserved_by_id == transaction.buyer_id
            and listing.reserved_until is not None and listing.reserved_until > now)


def swap_request_for(transaction):
    """The accepted swap offer a top-up payment belongs to."""
    return (SwapRequest.query
            .filter(SwapRequest.target_listing_id == transaction.listing_id,
                    SwapRequest.requester_id == transaction.buyer_id,
                    SwapRequest.status == SwapRequestStatus.ACCEPTED)
            .order_by(SwapRequest.responded_at.desc()).first())


def _put_back(listing, buyer_id=None):
    if listing is not None and listing.status == ListingStatus.RESERVED \
            and (buyer_id is None or listing.reserved_by_id == buyer_id):
        listing.status = ListingStatus.ACTIVE
        listing.reserved_by_id = None
        listing.reserved_until = None


def cancel_reservation(transaction):
    """The buyer cancelled, time ran out or the item is gone: put everything back."""
    if transaction.status in (TransactionStatus.RESERVED, TransactionStatus.PAYMENT_FAILED):
        transaction.status = TransactionStatus.CANCELLED
    if transaction.transaction_type == TransactionType.SWAP_WITH_TOP_UP:
        swap = swap_request_for(transaction)
        if swap is not None:
            swap.status = SwapRequestStatus.CANCELLED
            _put_back(swap.offered_listing)
    _put_back(transaction.listing, transaction.buyer_id)
    db.session.commit()


def finish_after_payment(transaction):
    """Mark the items as finished once payment has gone through."""
    listing = transaction.listing
    if transaction.transaction_type == TransactionType.SWAP_WITH_TOP_UP:
        swap = swap_request_for(transaction)
        listing.status = ListingStatus.SWAPPED
        if swap is not None and swap.offered_listing is not None:
            swap.offered_listing.status = ListingStatus.SWAPPED
            swap.offered_listing.reserved_by_id = swap.offered_listing.reserved_until = None
    else:
        listing.status = ListingStatus.SOLD
    listing.reserved_by_id = listing.reserved_until = None
