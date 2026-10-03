from flask import render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user

from app.messaging import messaging_bp
from app.extensions import db
from app.forms import MessageForm
from app.models import Conversation, Message, Listing, NotificationType
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
    return render_template("messaging/inbox.html", conversations=conversations)


@messaging_bp.route("/messages/start/<int:listing_id>", methods=["POST"])
@login_required
def start_conversation(listing_id):
    listing = Listing.query.get_or_404(listing_id)
    if listing.seller_id == current_user.id:
        flash("This is your own listing.", "info")
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

    form = MessageForm()
    if form.validate_on_submit():
        image_filename = save_uploaded_image(form.image.data, subfolder="messages")
        message = Message(
            conversation_id=convo.id,
            sender_id=current_user.id,
            body=form.body.data,
            image_filename=image_filename,
            offer_price=form.offer_price.data,
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

    other_id = convo.other_participant(current_user.id)
    from app.models import User
    other_user = User.query.get(other_id)

    return render_template(
        "messaging/conversation.html",
        conversation=convo,
        form=form,
        other_user=other_user,
    )
