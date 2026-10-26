from datetime import datetime
from decimal import Decimal

from flask import render_template, redirect, url_for, flash, request, abort, current_app
from flask_login import login_required, current_user

from app.messaging import messaging_bp
from app.extensions import db
from app.forms import MessageForm
from app.models import Conversation, Message, Listing, ListingStatus, ListingType, NotificationType, User
from app.pricing import message_offer_state, find_accepted_offer
from app.pricing_rules import offer_error, money
from app.sides import can_view_listing, same_side
from app.utils import save_uploaded_image, notify_user


@messaging_bp.route("/messages")
@login_required
def inbox():
    conversations = (
        Conversation.query.filter(
            db.or_(Conversation.participant_one_id == current_user.id,
                   Conversation.participant_two_id == current_user.id)
        )
        .order_by(Conversation.created_at.desc())
        .all()
    )
    # Chats that are closed (other person closed or suspended, or on the other side) are not listed.
    open_chats = []
    for convo in conversations:
        other = db.session.get(User, convo.other_participant(current_user.id))
        if other and not other.deleted_at and other.is_active_account and same_side(current_user, other):
            open_chats.append(convo)
    return render_template("messaging/inbox.html", conversations=open_chats)


@messaging_bp.route("/messages/start/<int:listing_id>", methods=["POST"])
@login_required
def start_conversation(listing_id):
    listing = Listing.query.get_or_404(listing_id)
    # Learners and adults never message each other, and removed or hidden listings cannot be opened.
    if not can_view_listing(current_user, listing):
        abort(404)
    if listing.seller_id == current_user.id:
        flash("This is your own listing.", "info")
        return redirect(url_for("marketplace.listing_detail", listing_id=listing.id))
    if listing.status not in (ListingStatus.ACTIVE, ListingStatus.RESERVED):
        flash("This item is no longer available, so a new chat cannot be started.", "info")
        return redirect(url_for("marketplace.listing_detail", listing_id=listing.id))

    existing = Conversation.query.filter(
        Conversation.listing_id == listing.id,
        db.or_(
            db.and_(Conversation.participant_one_id == current_user.id,
                    Conversation.participant_two_id == listing.seller_id),
            db.and_(Conversation.participant_one_id == listing.seller_id,
                    Conversation.participant_two_id == current_user.id),
        ),
    ).first()

    if not existing:
        existing = Conversation(
            listing_id=listing.id,
            participant_one_id=current_user.id,
            participant_two_id=listing.seller_id,
        )
        db.session.add(existing)
        db.session.commit()

    return redirect(url_for("messaging.conversation", conversation_id=existing.id))


@messaging_bp.route("/messages/<int:conversation_id>", methods=["GET", "POST"])
@login_required
def conversation(conversation_id):
    convo = Conversation.query.get_or_404(conversation_id)
    if current_user.id not in (convo.participant_one_id, convo.participant_two_id):
        abort(403)

    other_user = db.session.get(User, convo.other_participant(current_user.id))
    # A chat closes if the other person was closed or suspended, or is now on the other side
    # (for example one of you turned 18). It is not shown, and nothing can be sent into it.
    if (other_user is None or other_user.deleted_at or not other_user.is_active_account
            or not same_side(current_user, other_user)):
        flash("This chat is closed.", "info")
        return redirect(url_for("messaging.inbox"))

    form = MessageForm()
    if form.validate_on_submit():
        offer_amount, offer_status = form.offer_price.data, None
        if offer_amount is not None:
            listing = convo.listing
            symbol = current_app.config["CURRENCY_SYMBOL"]
            if current_user.is_minor and not current_user.allow_paid_trades:
                problem = "Offers need your parent or guardian's permission. You can still swap and donate."
            elif not listing or listing.listing_type != ListingType.SELL:
                problem = "Offers can only be made on items listed for sale."
            elif listing.status != ListingStatus.ACTIVE:
                problem = "This item is no longer open for offers."
            else:
                problem = offer_error(listing.price, offer_amount, symbol)
            if problem:
                flash(problem, "danger")
                return redirect(url_for("messaging.conversation", conversation_id=convo.id))
            offer_amount, offer_status = money(offer_amount), "pending"
            for earlier in convo.messages:     # a new offer replaces this person's earlier waiting offer
                if earlier.sender_id == current_user.id and earlier.offer_status == "pending":
                    earlier.offer_status = "withdrawn"

        image_filename = save_uploaded_image(form.image.data, subfolder="messages")
        message = Message(
            conversation_id=convo.id,
            sender_id=current_user.id,
            body=form.body.data,
            image_filename=image_filename,
            offer_price=offer_amount,
            offer_status=offer_status,
            proposed_pickup=form.proposed_pickup.data or None,
        )
        db.session.add(message)
        db.session.commit()

        other_id = convo.other_participant(current_user.id)
        notify_user(
            other_id, NotificationType.MESSAGE,
            title=f"New message from {current_user.full_name}",
            body=(form.body.data or "Sent an offer/attachment")[:120],
            link=url_for("messaging.conversation", conversation_id=convo.id),
        )
        return redirect(url_for("messaging.conversation", conversation_id=convo.id))

    # Mark incoming messages as read (simple read-receipt implementation)
    unread = [m for m in convo.messages if m.sender_id != current_user.id and not m.is_read]
    for m in unread:
        m.is_read = True
    if unread:
        db.session.commit()

    now = datetime.utcnow()
    offer_states = {m.id: message_offer_state(m, now) for m in convo.messages if m.offer_price is not None}
    pay_offer = None
    if convo.listing and current_user.id != convo.listing.seller_id and convo.listing.status == ListingStatus.ACTIVE:
        pay_offer = find_accepted_offer(convo.listing, current_user.id, now)

    return render_template(
        "messaging/conversation.html",
        conversation=convo,
        form=form,
        other_user=other_user,
        offer_states=offer_states,
        pay_offer=pay_offer,
        offer_hours=current_app.config["OFFER_VALID_HOURS"],
        watched=current_user.is_minor,
    )


@messaging_bp.route("/messages/<int:conversation_id>/offer/<int:message_id>/<action>", methods=["POST"])
@login_required
def respond_to_offer(conversation_id, message_id, action):
    """Accept or decline someone else's offer, or withdraw your own. Only an
    accepted offer can ever become the price on a receipt."""
    convo = Conversation.query.get_or_404(conversation_id)
    if current_user.id not in (convo.participant_one_id, convo.participant_two_id):
        abort(403)
    if action not in ("accept", "decline", "withdraw"):
        abort(404)
    message = Message.query.get_or_404(message_id)
    if message.conversation_id != convo.id or message.offer_price is None:
        abort(404)

    back = redirect(url_for("messaging.conversation", conversation_id=convo.id))
    now = datetime.utcnow()
    if message_offer_state(message, now) != "pending":
        flash("This offer can no longer be changed.", "info")
        return back

    symbol = current_app.config["CURRENCY_SYMBOL"]
    amount = f"{symbol}{Decimal(message.offer_price):.2f}"
    if action == "withdraw":
        if message.sender_id != current_user.id:
            abort(403)
        message.offer_status = "withdrawn"
        db.session.commit()
        flash("Offer withdrawn.", "info")
        return back

    if message.sender_id == current_user.id:
        abort(403)          # you cannot accept or decline your own offer
    if action == "accept":
        listing = convo.listing
        if (not listing or listing.listing_type != ListingType.SELL or listing.status != ListingStatus.ACTIVE
                or offer_error(listing.price, message.offer_price, symbol)):
            flash("This offer no longer applies to the listing, so it cannot be accepted.", "danger")
            return back
        for other in convo.messages:       # only one agreed price at a time in a chat
            if other.id != message.id and other.offer_status in ("pending", "accepted"):
                other.offer_status = "withdrawn"
        message.offer_status, message.offer_responded_at = "accepted", now
        verb, flash_text = "accepted", f"You accepted the offer of {amount}."
    else:
        message.offer_status, message.offer_responded_at = "declined", now
        verb, flash_text = "declined", f"You declined the offer of {amount}."
    db.session.commit()

    notify_user(
        message.sender_id, NotificationType.OFFER,
        title=f"Your offer was {verb}",
        body=f"{current_user.full_name} {verb} your offer of {amount}"
             + (f" for '{convo.listing.title}'." if convo.listing else "."),
        link=url_for("messaging.conversation", conversation_id=convo.id),
    )
    flash(flash_text, "success")
    return back
