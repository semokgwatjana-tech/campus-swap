from datetime import datetime, timedelta
from decimal import Decimal

from flask import render_template, redirect, url_for, flash, request, current_app, abort
from flask_login import login_required, current_user

from app.transactions import transactions_bp
from app.extensions import db
from app.forms import CheckoutForm, SwapOfferForm, ReviewForm, DisputeForm
from app.models import (
    Listing, ListingStatus, ListingType, Transaction, TransactionStatus,
    TransactionType, PaymentMethod, SwapRequest, SwapRequestStatus,
    DonationRequest, DonationRequestStatus, Review, Dispute, ReportStatus,
    NotificationType,
)
from app.utils import generate_transaction_reference, notify_user, calculate_service_fee
from app.pricing import resolve_price, price_for_transaction
from app.models import Message, User
from app.pricing_rules import money
from app.sides import can_view_listing, same_side
from app.trades import (
    reserve_listing, release_expired_reservations, reservation_is_valid, cancel_reservation,
    finish_after_payment,
)
from app.transactions.payment_gateway import get_gateway, mask_card_number, PaymentError


# ---------------------------------------------------------------------------
# Buy flow: reserve -> checkout -> pay -> pickup -> complete
# ---------------------------------------------------------------------------

@transactions_bp.route("/listing/<int:listing_id>/buy", methods=["POST"])
@login_required
def start_purchase(listing_id):
    listing = Listing.query.get_or_404(listing_id)
    if not can_view_listing(current_user, listing):
        abort(404)
    release_expired_reservations()
    db.session.refresh(listing)

    if listing.seller_id == current_user.id:
        flash("You can't buy your own listing.", "warning")
        return redirect(url_for("marketplace.listing_detail", listing_id=listing.id))

    if listing.listing_type != ListingType.SELL:
        flash("This item isn't listed for direct sale. Try a swap or donation request instead.", "warning")
        return redirect(url_for("marketplace.listing_detail", listing_id=listing.id))

    if current_user.is_minor and not current_user.allow_paid_trades:
        flash("Buying needs your parent or guardian's permission. You can still swap and ask for donations.", "info")
        return redirect(url_for("marketplace.listing_detail", listing_id=listing.id))

    # Already holding this item? Carry on with that purchase instead of starting another.
    mine = Transaction.query.filter_by(listing_id=listing.id, buyer_id=current_user.id,
                                       status=TransactionStatus.RESERVED,
                                       transaction_type=TransactionType.PURCHASE).first()
    if mine and reservation_is_valid(mine, listing):
        return redirect(url_for("transactions.checkout", transaction_id=mine.id))

    # Reserve in one step that only one buyer can win, so two students can't both pay.
    if not reserve_listing(listing.id, current_user.id):
        flash("Sorry, this item is no longer available.", "danger")
        return redirect(url_for("marketplace.listing_detail", listing_id=listing.id))
    db.session.refresh(listing)

    # The server decides the price: the listing price, or a chat offer the other
    # person accepted. The browser never supplies a price or a fee.
    item_price, price_source, offer = resolve_price(listing, current_user.id)
    service_fee = Decimal(str(calculate_service_fee(item_price)))

    transaction = Transaction(
        reference=generate_transaction_reference(),
        listing_id=listing.id,
        buyer_id=current_user.id,
        seller_id=listing.seller_id,
        transaction_type=TransactionType.PURCHASE,
        item_price=item_price,
        listed_price=Decimal(listing.price),
        price_source=price_source,
        offer_message_id=offer.id if offer else None,
        offer_accepted_at=offer.offer_responded_at if offer else None,
        service_fee=service_fee,
        total_amount=item_price + service_fee,
        status=TransactionStatus.RESERVED,
    )
    db.session.add(transaction)
    db.session.commit()

    return redirect(url_for("transactions.checkout", transaction_id=transaction.id))


@transactions_bp.route("/checkout/<int:transaction_id>", methods=["GET", "POST"])
@login_required
def checkout(transaction_id):
    transaction = Transaction.query.get_or_404(transaction_id)
    if transaction.buyer_id != current_user.id:
        abort(403)

    listing = transaction.listing
    if transaction.status not in (TransactionStatus.RESERVED, TransactionStatus.PAYMENT_FAILED):
        # Already paid, cancelled, or expired - send them somewhere sensible.
        return redirect(url_for("transactions.receipt", transaction_id=transaction.id))

    # The item must still be held for THIS buyer, with time left. Otherwise someone
    # else may have it now, and paying would sell it twice.
    if not reservation_is_valid(transaction, listing):
        cancel_reservation(transaction)
        flash("Your reservation expired or the item is no longer held for you. Please start again.", "warning")
        if transaction.transaction_type == TransactionType.PURCHASE:
            return redirect(url_for("marketplace.listing_detail", listing_id=listing.id))
        return redirect(url_for("transactions.my_requests"))

    form = CheckoutForm()
    if form.validate_on_submit():
        # Work out the amount on the server one more time right before charging -
        # never trust any amount that came from the browser.
        if transaction.transaction_type == TransactionType.PURCHASE:
            item_price, price_source, offer = price_for_transaction(transaction, listing)
            service_fee = Decimal(str(calculate_service_fee(item_price)))
            transaction.listed_price = Decimal(listing.price)
            transaction.price_source = price_source
            if offer is None:
                transaction.offer_message_id = transaction.offer_accepted_at = None
        else:                                    # a swap top-up: the amount was fixed when it was accepted
            item_price, service_fee = Decimal(transaction.item_price), Decimal(transaction.service_fee or 0)

        # If the price moved since the page was shown, do NOT charge the new amount quietly.
        if money(item_price + service_fee) != money(transaction.total_amount):
            transaction.item_price, transaction.service_fee = item_price, service_fee
            transaction.total_amount = item_price + service_fee
            db.session.commit()
            flash(f"The price changed to {current_app.config['CURRENCY_SYMBOL']}{transaction.total_amount:.2f}. "
                  "Please check it and pay again if you are happy.", "warning")
            return redirect(url_for("transactions.checkout", transaction_id=transaction.id))

        transaction.payment_method = PaymentMethod(form.payment_method.data)
        transaction.pickup_location = form.pickup_location.data
        transaction.status = TransactionStatus.PAYMENT_PROCESSING
        db.session.commit()

        try:
            gateway = get_gateway()
            result = gateway.charge(
                amount=float(transaction.total_amount),
                method=transaction.payment_method.value,
                payment_details={
                    "card_number": form.card_number.data,
                    "card_expiry": form.card_expiry.data,
                    "card_cvv": form.card_cvv.data,
                },
            )
        except PaymentError as exc:
            transaction.status = TransactionStatus.PAYMENT_FAILED
            db.session.commit()
            flash(f"Payment could not be processed: {exc}", "danger")
            return redirect(url_for("transactions.checkout", transaction_id=transaction.id))

        transaction.gateway_reference = result.gateway_reference

        if result.success:
            transaction.status = TransactionStatus.PAID
            transaction.paid_at = datetime.utcnow()
            finish_after_payment(transaction)
            if transaction.offer_message_id:      # an offer can only be paid for once
                used = db.session.get(Message, transaction.offer_message_id)
                if used is not None and used.offer_status == "accepted":
                    used.offer_status = "used"
            db.session.commit()

            notify_user(
                transaction.seller_id, NotificationType.SALE,
                title="You made a sale!" if transaction.transaction_type == TransactionType.PURCHASE
                else "Top-up paid for your swap",
                body=f"{current_user.full_name} paid for '{listing.title}'. Prepare it for pickup.",
                link=url_for("transactions.sale_detail", transaction_id=transaction.id),
            )
            flash("Payment successful! Your transaction ID is " + transaction.reference, "success")
            return redirect(url_for("transactions.receipt", transaction_id=transaction.id))

        # Declined: the item stays held for this buyer until the time runs out, so a retry is safe.
        transaction.status = TransactionStatus.PAYMENT_FAILED
        db.session.commit()
        flash(f"Payment failed: {result.message}", "danger")
        return redirect(url_for("transactions.checkout", transaction_id=transaction.id))

    return render_template(
        "transactions/checkout.html",
        transaction=transaction,
        listing=listing,
        form=form,
        pickup_points=current_app.config["SAFE_PICKUP_POINTS"],
    )


@transactions_bp.route("/checkout/<int:transaction_id>/cancel", methods=["POST"])
@login_required
def cancel_checkout(transaction_id):
    transaction = Transaction.query.get_or_404(transaction_id)
    if transaction.buyer_id != current_user.id:
        abort(403)
    if transaction.status in (TransactionStatus.RESERVED, TransactionStatus.PAYMENT_FAILED):
        cancel_reservation(transaction)
        flash("Purchase cancelled.", "info")
    return redirect(url_for("marketplace.listing_detail", listing_id=transaction.listing_id))


@transactions_bp.route("/receipt/<int:transaction_id>")
@login_required
def receipt(transaction_id):
    transaction = Transaction.query.get_or_404(transaction_id)
    if current_user.id not in (transaction.buyer_id, transaction.seller_id) and not current_user.is_admin:
        abort(403)
    return render_template("transactions/receipt.html", transaction=transaction)


# ---------------------------------------------------------------------------
# Pickup / completion
# ---------------------------------------------------------------------------

@transactions_bp.route("/transaction/<int:transaction_id>/ready-for-pickup", methods=["POST"])
@login_required
def mark_ready_for_pickup(transaction_id):
    transaction = Transaction.query.get_or_404(transaction_id)
    if transaction.seller_id != current_user.id:
        abort(403)
    if transaction.status == TransactionStatus.PAID:
        transaction.status = TransactionStatus.READY_FOR_PICKUP
        db.session.commit()
        notify_user(
            transaction.buyer_id, NotificationType.SALE,
            title="Your item is ready for pickup",
            body=f"'{transaction.listing.title}' is ready at {transaction.pickup_location}.",
            link=url_for("transactions.receipt", transaction_id=transaction.id),
        )
        flash("Buyer notified that the item is ready for pickup.", "success")
    return redirect(url_for("transactions.sale_detail", transaction_id=transaction.id))


@transactions_bp.route("/transaction/<int:transaction_id>/complete", methods=["POST"])
@login_required
def complete_transaction(transaction_id):
    """Only the BUYER confirms the hand-over. A seller cannot close a transaction on their own."""
    transaction = Transaction.query.get_or_404(transaction_id)
    if current_user.id != transaction.buyer_id:
        abort(403)
    if transaction.status in (TransactionStatus.PAID, TransactionStatus.READY_FOR_PICKUP):
        transaction.status = TransactionStatus.COMPLETED
        transaction.completed_at = datetime.utcnow()
        db.session.commit()
        notify_user(transaction.seller_id, NotificationType.SALE, "Hand-over confirmed",
                    f"{current_user.full_name} confirmed they received '{transaction.listing.title}'.",
                    url_for("transactions.sale_detail", transaction_id=transaction.id))
        flash("Transaction marked as completed. You can now leave a review!", "success")
    return redirect(url_for("transactions.receipt", transaction_id=transaction.id))


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

@transactions_bp.route("/my-purchases")
@login_required
def my_purchases():
    purchases = (
        Transaction.query.filter_by(buyer_id=current_user.id)
        .order_by(Transaction.created_at.desc())
        .all()
    )
    return render_template("transactions/my_purchases.html", purchases=purchases)


@transactions_bp.route("/my-sales")
@login_required
def my_sales():
    sales = (
        Transaction.query.filter_by(seller_id=current_user.id)
        .order_by(Transaction.created_at.desc())
        .all()
    )
    return render_template("transactions/my_sales.html", sales=sales)


@transactions_bp.route("/sale/<int:transaction_id>")
@login_required
def sale_detail(transaction_id):
    transaction = Transaction.query.get_or_404(transaction_id)
    if current_user.id not in (transaction.buyer_id, transaction.seller_id) and not current_user.is_admin:
        abort(403)
    return render_template("transactions/sale_detail.html", transaction=transaction)


# ---------------------------------------------------------------------------
# Donations
# ---------------------------------------------------------------------------

def _decline_others(model, listing_field, listing_id, keep_id, pending, declined, note_title, note_body, kind):
    """When one request is accepted, the other waiting ones are declined and told."""
    others = model.query.filter(listing_field == listing_id, model.id != keep_id, model.status == pending).all()
    for other in others:
        other.status = declined
        notify_user(other.requester_id, kind, note_title, note_body, url_for("transactions.my_requests"))


@transactions_bp.route("/requests")
@login_required
def my_requests():
    """Requests to you (donations and swaps, with Accept and Decline) and the ones you sent."""
    release_expired_reservations()
    incoming_donations = (DonationRequest.query.join(Listing, DonationRequest.listing_id == Listing.id)
                          .filter(Listing.seller_id == current_user.id,
                                  DonationRequest.status == DonationRequestStatus.PENDING)
                          .order_by(DonationRequest.created_at.desc()).all())
    incoming_swaps = (SwapRequest.query.join(Listing, SwapRequest.target_listing_id == Listing.id)
                      .filter(Listing.seller_id == current_user.id, SwapRequest.status == SwapRequestStatus.PENDING)
                      .order_by(SwapRequest.created_at.desc()).all())
    sent_donations = (DonationRequest.query.filter_by(requester_id=current_user.id)
                      .order_by(DonationRequest.created_at.desc()).limit(30).all())
    sent_swaps = (SwapRequest.query.filter_by(requester_id=current_user.id)
                  .order_by(SwapRequest.created_at.desc()).limit(30).all())
    topups = {}
    for sw in sent_swaps:
        if sw.status == SwapRequestStatus.ACCEPTED and sw.top_up_amount and sw.top_up_amount > 0:
            topups[sw.id] = Transaction.query.filter_by(
                listing_id=sw.target_listing_id, buyer_id=current_user.id,
                transaction_type=TransactionType.SWAP_WITH_TOP_UP,
                status=TransactionStatus.RESERVED).first()
    return render_template("transactions/requests.html", incoming_donations=incoming_donations,
                           incoming_swaps=incoming_swaps, sent_donations=sent_donations,
                           sent_swaps=sent_swaps, topups=topups)


@transactions_bp.route("/listing/<int:listing_id>/request-donation", methods=["POST"])
@login_required
def request_donation(listing_id):
    listing = Listing.query.get_or_404(listing_id)
    if not can_view_listing(current_user, listing):
        abort(404)
    if listing.listing_type != ListingType.DONATE or listing.status != ListingStatus.ACTIVE:
        flash("This item isn't available for donation requests.", "warning")
        return redirect(url_for("marketplace.listing_detail", listing_id=listing.id))
    if listing.seller_id == current_user.id:
        flash("You can't request your own donation.", "warning")
        return redirect(url_for("marketplace.listing_detail", listing_id=listing.id))

    existing = DonationRequest.query.filter_by(
        listing_id=listing.id, requester_id=current_user.id, status=DonationRequestStatus.PENDING
    ).first()
    if existing:
        flash("You have already asked for this item. The donor will answer soon.", "info")
        return redirect(url_for("marketplace.listing_detail", listing_id=listing.id))

    donation_request = DonationRequest(
        listing_id=listing.id,
        requester_id=current_user.id,
        message=request.form.get("message", "").strip()[:500],
    )
    db.session.add(donation_request)
    db.session.commit()

    notify_user(
        listing.seller_id, NotificationType.DONATION_REQUEST,
        title="New donation request",
        body=f"{current_user.full_name} would like your donated '{listing.title}'.",
        link=url_for("transactions.my_requests"),
    )
    flash("Request sent to the donor. You'll be notified if it's approved.", "success")
    return redirect(url_for("marketplace.listing_detail", listing_id=listing.id))


@transactions_bp.route("/donation-request/<int:request_id>/<action>", methods=["POST"])
@login_required
def manage_donation(request_id, action):
    donation_request = DonationRequest.query.get_or_404(request_id)
    listing = donation_request.listing
    if listing.seller_id != current_user.id:
        abort(403)
    if action not in ("approve", "decline"):
        abort(404)
    back = redirect(url_for("transactions.my_requests"))
    if donation_request.status != DonationRequestStatus.PENDING:
        flash("You already answered this request.", "info")
        return back

    if action == "approve":
        requester = donation_request.requester
        if listing.status != ListingStatus.ACTIVE:
            flash("This item is no longer available to donate.", "danger")
            return back
        if not requester.is_active_account or requester.deleted_at or not same_side(current_user, requester):
            flash("This request can no longer be approved.", "danger")
            return back

        donation_request.status = DonationRequestStatus.APPROVED
        listing.status = ListingStatus.DONATED
        _decline_others(DonationRequest, DonationRequest.listing_id, listing.id, donation_request.id,
                        DonationRequestStatus.PENDING, DonationRequestStatus.DECLINED, "Donation request declined",
                        f"'{listing.title}' went to another student.", NotificationType.DONATION_REQUEST)

        transaction = Transaction(
            reference=generate_transaction_reference(),
            listing_id=listing.id,
            buyer_id=donation_request.requester_id,
            seller_id=listing.seller_id,
            transaction_type=TransactionType.DONATION,
            item_price=0,
            service_fee=0,
            total_amount=0,
            payment_method=PaymentMethod.NONE,
            status=TransactionStatus.COMPLETED,
            completed_at=datetime.utcnow(),
        )
        db.session.add(transaction)
        db.session.commit()

        notify_user(
            donation_request.requester_id, NotificationType.DONATION_REQUEST,
            title="Your donation request was approved!",
            body="You've helped another student access a resource for free. Arrange a safe campus pickup.",
            link=url_for("transactions.receipt", transaction_id=transaction.id),
        )
        flash("Donation approved. Thank you for helping another student!", "success")
    else:
        donation_request.status = DonationRequestStatus.DECLINED
        db.session.commit()
        notify_user(
            donation_request.requester_id, NotificationType.DONATION_REQUEST,
            title="Donation request declined",
            body=f"Your request for '{listing.title}' was declined.",
        )
        flash("Request declined.", "info")
    return back


# ---------------------------------------------------------------------------
# Swaps
# ---------------------------------------------------------------------------

@transactions_bp.route("/listing/<int:listing_id>/swap", methods=["GET", "POST"])
@login_required
def propose_swap(listing_id):
    target = Listing.query.get_or_404(listing_id)
    if not can_view_listing(current_user, target):
        abort(404)
    if target.listing_type != ListingType.SWAP or target.status != ListingStatus.ACTIVE:
        flash("This item isn't available for swapping.", "warning")
        return redirect(url_for("marketplace.listing_detail", listing_id=target.id))
    if target.seller_id == current_user.id:
        flash("You can't swap with yourself.", "warning")
        return redirect(url_for("marketplace.listing_detail", listing_id=target.id))

    my_listings = Listing.query.filter_by(
        seller_id=current_user.id, status=ListingStatus.ACTIVE
    ).all()

    form = SwapOfferForm()
    form.offered_listing_id.choices = [(l.id, l.title) for l in my_listings]

    if not my_listings:
        flash("Create a listing of your own first so you have something to offer in a swap.", "info")
        return redirect(url_for("marketplace.sell"))

    if form.validate_on_submit():
        top_up = money(form.top_up_amount.data or 0)
        if top_up > 0 and current_user.is_minor and not current_user.allow_paid_trades:
            flash("A cash top-up needs your parent or guardian's permission. You can offer a straight swap.", "info")
            return render_template("transactions/propose_swap.html", target=target, form=form)
        duplicate = SwapRequest.query.filter_by(
            requester_id=current_user.id, target_listing_id=target.id,
            offered_listing_id=form.offered_listing_id.data, status=SwapRequestStatus.PENDING).first()
        if duplicate:
            flash("You already offered that item for this swap. The owner will answer soon.", "info")
            return redirect(url_for("transactions.my_requests"))

        swap_request = SwapRequest(
            requester_id=current_user.id,
            target_listing_id=target.id,
            offered_listing_id=form.offered_listing_id.data,
            top_up_amount=top_up,
            message=form.message.data,
        )
        db.session.add(swap_request)
        db.session.commit()

        notify_user(
            target.seller_id, NotificationType.SWAP,
            title="New swap offer",
            body=f"{current_user.full_name} wants to swap for '{target.title}'.",
            link=url_for("transactions.my_requests"),
        )
        flash("Swap offer sent!", "success")
        return redirect(url_for("transactions.my_requests"))

    return render_template("transactions/propose_swap.html", target=target, form=form)


@transactions_bp.route("/swap/<int:swap_id>/<action>", methods=["POST"])
@login_required
def manage_swap(swap_id, action):
    swap_request = SwapRequest.query.get_or_404(swap_id)
    target = swap_request.target_listing
    offered = swap_request.offered_listing
    if target.seller_id != current_user.id:
        abort(403)
    if action not in ("accept", "decline"):
        abort(404)
    back = redirect(url_for("transactions.my_requests"))
    if swap_request.status != SwapRequestStatus.PENDING:
        flash("You already answered this offer.", "info")
        return back

    now = datetime.utcnow()
    if action == "decline":
        swap_request.status = SwapRequestStatus.DECLINED
        swap_request.responded_at = now
        db.session.commit()
        notify_user(
            swap_request.requester_id, NotificationType.SWAP,
            title="Swap declined",
            body=f"Your swap offer for '{target.title}' was declined.",
        )
        flash("Swap declined.", "info")
        return back

    requester = swap_request.requester
    if target.status != ListingStatus.ACTIVE:
        flash("Your item is no longer available to swap.", "danger")
        return back
    if (offered is None or offered.status != ListingStatus.ACTIVE or offered.seller_id != swap_request.requester_id
            or not requester.is_active_account or requester.deleted_at or not same_side(current_user, requester)):
        flash("The other student's item is no longer available, so this swap cannot go ahead.", "danger")
        return back

    top_up = money(swap_request.top_up_amount or 0)
    swap_request.status = SwapRequestStatus.ACCEPTED
    swap_request.responded_at = now
    _decline_others(SwapRequest, SwapRequest.target_listing_id, target.id, swap_request.id,
                    SwapRequestStatus.PENDING, SwapRequestStatus.DECLINED, "Swap declined",
                    f"'{target.title}' was swapped with another student.", NotificationType.SWAP)

    transaction = Transaction(
        reference=generate_transaction_reference(),
        listing_id=target.id,
        buyer_id=swap_request.requester_id,
        seller_id=target.seller_id,
        transaction_type=TransactionType.SWAP_WITH_TOP_UP if top_up > 0 else TransactionType.SWAP,
        item_price=top_up,
        service_fee=0,
        total_amount=top_up,
        payment_method=PaymentMethod.CARD if top_up > 0 else PaymentMethod.NONE,
        status=TransactionStatus.RESERVED if top_up > 0 else TransactionStatus.COMPLETED,
        pickup_location=current_app.config["SAFE_PICKUP_POINTS"][0],
        completed_at=None if top_up > 0 else now,
    )
    if top_up > 0:
        # Hold both items for the other student while they pay the top-up.
        until = now + timedelta(hours=current_app.config["SWAP_TOPUP_HOURS"])
        for item in (target, offered):
            item.status = ListingStatus.RESERVED
            item.reserved_by_id = swap_request.requester_id
            item.reserved_until = until
    else:
        target.status = ListingStatus.SWAPPED
        offered.status = ListingStatus.SWAPPED
    db.session.add(transaction)
    db.session.commit()

    if top_up > 0:
        notify_user(
            swap_request.requester_id, NotificationType.SWAP,
            title="Your swap was accepted: pay the top-up",
            body=f"'{target.title}' swap accepted. Pay the top-up within "
                 f"{current_app.config['SWAP_TOPUP_HOURS']} hours to finish it.",
            link=url_for("transactions.checkout", transaction_id=transaction.id),
        )
        flash("Swap accepted. The other student has been asked to pay the top-up, and both items are held for them.",
              "success")
    else:
        notify_user(
            swap_request.requester_id, NotificationType.SWAP,
            title="Your swap was accepted!",
            body=f"'{target.title}' swap accepted. Arrange a safe campus pickup.",
            link=url_for("transactions.receipt", transaction_id=transaction.id),
        )
        flash("Swap accepted!", "success")
    return back


# ---------------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------------

@transactions_bp.route("/transaction/<int:transaction_id>/review", methods=["GET", "POST"])
@login_required
def leave_review(transaction_id):
    transaction = Transaction.query.get_or_404(transaction_id)
    if current_user.id not in (transaction.buyer_id, transaction.seller_id):
        abort(403)
    if transaction.status != TransactionStatus.COMPLETED:
        flash("You can only review completed transactions.", "warning")
        return redirect(url_for("transactions.receipt", transaction_id=transaction.id))

    reviewee_id = transaction.seller_id if current_user.id == transaction.buyer_id else transaction.buyer_id
    existing = Review.query.filter_by(transaction_id=transaction.id, reviewer_id=current_user.id).first()
    if existing:
        flash("You've already reviewed this transaction.", "info")
        return redirect(url_for("transactions.receipt", transaction_id=transaction.id))

    form = ReviewForm()
    if form.validate_on_submit():
        review = Review(
            transaction_id=transaction.id,
            reviewer_id=current_user.id,
            reviewee_id=reviewee_id,
            rating=int(form.rating.data),
            comment=form.comment.data,
        )
        db.session.add(review)
        db.session.flush()

        from app.models import User
        reviewee = User.query.get(reviewee_id)
        all_reviews = Review.query.filter_by(reviewee_id=reviewee_id).all()
        reviewee.trust_score = round(sum(r.rating for r in all_reviews) / len(all_reviews), 2)
        db.session.commit()

        notify_user(
            reviewee_id, NotificationType.NEW_REVIEW,
            title="You received a new review",
            body=f"{current_user.full_name} left you a {review.rating}-star review.",
            link=url_for("main.public_profile", user_id=reviewee_id),
        )
        flash("Thanks for your review!", "success")
        return redirect(url_for("transactions.receipt", transaction_id=transaction.id))

    return render_template("transactions/leave_review.html", transaction=transaction, form=form)


# ---------------------------------------------------------------------------
# Disputes
# ---------------------------------------------------------------------------

BUYER_DISPUTE_REASONS = [
    ("not_received", "Item was not received"),
    ("not_as_described", "Item was significantly different from the listing"),
    ("seller_cancelled", "Seller cancelled after payment"),
    ("other", "Other transaction problem"),
]
SELLER_DISPUTE_REASONS = [
    ("buyer_no_show", "Buyer did not arrive"),
    ("buyer_cancelled", "Buyer cancelled"),
    ("other", "Other transaction problem"),
]


@transactions_bp.route("/transaction/<int:transaction_id>/dispute", methods=["GET", "POST"])
@login_required
def raise_dispute(transaction_id):
    transaction = Transaction.query.get_or_404(transaction_id)
    if current_user.id not in (transaction.buyer_id, transaction.seller_id):
        abort(403)

    now = datetime.utcnow()
    allowed_states = (TransactionStatus.PAID, TransactionStatus.READY_FOR_PICKUP,
                      TransactionStatus.REFUND_REQUESTED, TransactionStatus.COMPLETED)
    if transaction.status not in allowed_states:
        flash("A problem can only be reported on a transaction that has been paid or completed.", "info")
        return redirect(url_for("transactions.receipt", transaction_id=transaction.id))
    if transaction.status == TransactionStatus.COMPLETED and transaction.completed_at \
            and now - transaction.completed_at > timedelta(days=14):
        flash("Problems must be reported within 14 days of the hand-over. Please contact support.", "info")
        return redirect(url_for("transactions.receipt", transaction_id=transaction.id))
    if Dispute.query.filter(Dispute.transaction_id == transaction.id, Dispute.raised_by_id == current_user.id,
                            Dispute.status.in_([ReportStatus.OPEN, ReportStatus.REVIEWING])).first():
        flash("You already reported a problem on this transaction. An admin is looking at it.", "info")
        return redirect(url_for("transactions.receipt", transaction_id=transaction.id))

    form = DisputeForm()
    is_buyer = current_user.id == transaction.buyer_id
    form.reason.choices = BUYER_DISPUTE_REASONS if is_buyer else SELLER_DISPUTE_REASONS

    if form.validate_on_submit():
        dispute = Dispute(
            transaction_id=transaction.id,
            raised_by_id=current_user.id,
            reason=form.reason.data,
            details=form.details.data,
        )
        transaction.status = TransactionStatus.REFUND_REQUESTED if is_buyer else transaction.status
        db.session.add(dispute)
        db.session.commit()
        flash("Your dispute has been submitted. Campus Swap admins will review it shortly.", "success")
        return redirect(url_for("transactions.receipt", transaction_id=transaction.id))

    return render_template("transactions/raise_dispute.html", transaction=transaction, form=form)
