"""
Finds the price a purchase should use. The browser never supplies a price:
it comes from the saved listing, or from a saved chat offer that the other
person accepted.
"""

from datetime import datetime

from flask import current_app

from app.extensions import db
from app.models import Conversation, Message
from app.pricing_rules import offer_state, choose_price


def message_offer_state(message, now=None):
    return offer_state(message.offer_status, message.sent_at, message.offer_responded_at,
                       now or datetime.utcnow(), current_app.config["OFFER_VALID_HOURS"])


def find_accepted_offer(listing, buyer_id, now=None):
    """The newest accepted, still valid offer between this buyer and the
    listing's seller that is genuinely lower than the listed price."""
    now = now or datetime.utcnow()
    rows = (Message.query.join(Conversation, Message.conversation_id == Conversation.id)
            .filter(Conversation.listing_id == listing.id,
                    db.or_(db.and_(Conversation.participant_one_id == buyer_id,
                                   Conversation.participant_two_id == listing.seller_id),
                           db.and_(Conversation.participant_two_id == buyer_id,
                                   Conversation.participant_one_id == listing.seller_id)),
                    Message.offer_status == "accepted", Message.offer_price.isnot(None))
            .order_by(Message.offer_responded_at.desc()).all())
    for message in rows:
        if message_offer_state(message, now) == "accepted" \
                and choose_price(listing.price, message.offer_price)[1] == "chat_offer":
            return message
    return None


def resolve_price(listing, buyer_id, now=None):
    """Used when a purchase starts. Returns (price, source, offer_message_or_None)."""
    offer = find_accepted_offer(listing, buyer_id, now)
    price, source = choose_price(listing.price, offer.offer_price if offer else None)
    return price, source, (offer if source == "chat_offer" else None)


def price_for_transaction(transaction, listing):
    """Used again right before charging. If this purchase was started from an
    accepted offer, read that saved offer again; otherwise use the listing."""
    offer = db.session.get(Message, transaction.offer_message_id) if transaction.offer_message_id else None
    if offer is not None and offer.offer_status in ("accepted", "used") and offer.offer_price is not None:
        price, source = choose_price(listing.price, offer.offer_price)
        return price, source, (offer if source == "chat_offer" else None)
    price, source = choose_price(listing.price, None)
    return price, source, None
