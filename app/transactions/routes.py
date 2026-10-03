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
    DonationRequest, DonationRequestStatus, Review, Dispute,
    NotificationType,
)
from app.utils import generate_transaction_reference, notify_user, calculate_service_fee
from app.transactions.payment_gateway import get_gateway, mask_card_number, PaymentError


# ---------------------------------------------------------------------------
# Buy flow: reserve -> checkout -> pay -> pickup -> complete
# ---------------------------------------------------------------------------

@transactions_bp.route("/listing/<int:listing_id>/buy", methods=["POST"])
@login_required
def start_purchase(listing_id):
    listing = Listing.query.get_or_404(listing_id)
    listing.release_reservation_if_expired()

    if listing.seller_id == current_user.id:
        flash("You can't buy your own listing.", "warning")
        return redirect(url_for("marketplace.listing_detail", listing_id=listing.id))

    if listing.listing_type != ListingType.SELL:
        flash("This item isn't listed for direct sale. Try a swap or donation request instead.", "warning")
        return redirect(url_for("marketplace.listing_detail", listing_id=listing.id))

    if listing.status not in (ListingStatus.ACTIVE,):
        flash("Sorry, this item is no longer available.", "danger")
        return redirect(url_for("marketplace.listing_detail", listing_id=listing.id))

    # Temporarily reserve the item so two students can't both pay for it.
    listing.status = ListingStatus.RESERVED
    listing.reserved_by_id = current_user.id
    listing.reserved_until = datetime.utcnow() + timedelta(
        minutes=current_app.config["RESERVATION_TIMEOUT_MINUTES"]
    )

    # Server calculates price + fee - the client never supplies these.
    item_price = Decimal(listing.price)
    service_fee = Decimal(str(calculate_service_fee(item_price)))

    transaction = Transaction(
        reference=generate_transaction_reference(),
        listing_id=listing.id,
        buyer_id=current_user.id,
        seller_id=listing.seller_id,
        transaction_type=TransactionType.PURCHASE,
        item_price=item_price,
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

    if listing.reserved_until and listing.reserved_until < datetime.utcnow():
        transaction.status = TransactionStatus.CANCELLED
        listing.status = ListingStatus.ACTIVE
        listing.reserved_by_id = None
        listing.reserved_until = None
        db.session.commit()
        flash("Your reservation expired. Please start the purchase again.", "warning")
        return redirect(url_for("marketplace.listing_detail", listing_id=listing.id))

    form = CheckoutForm()
    if form.validate_on_submit():
        # Recompute the total server-side one more time right before
        # charging - never trust any amount posted from the browser.
        item_price = Decimal(listing.price)
        service_fee = Decimal(str(calculate_service_fee(item_price)))
        transaction.item_price = item_price
        transaction.service_fee = service_fee
        transaction.total_amount = item_price + service_fee
        transaction.payment_method = PaymentMethod(form.payment_method.data)
        transaction.pickup_location = form.pickup_location.data
        transaction.status = TransactionStatus.PAYMENT_PROCESSING
        db.session.commit()

        gateway = get_gateway()
        try:
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
            listing.status = ListingStatus.SOLD
            db.session.commit()

            notify_user(
                listing.seller_id, NotificationType.SALE,
                title="You made a sale!",
                body=f"{current_user.full_name} paid for '{listing.title}'. Prepare it for pickup.",
                link=url_for("transactions.sale_detail", transaction_id=transaction.id),
            )
            flash("Payment successful! Your transaction ID is " + transaction.reference, "success")
            return redirect(url_for("transactions.receipt", transaction_id=transaction.id))
        else:
            transaction.status = TransactionStatus.PAYMENT_FAILED
            listing.status = ListingStatus.ACTIVE
            listing.reserved_by_id = None
            listing.reserved_until = None
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
        transaction.status = TransactionStatus.CANCELLED
        listing = transaction.listing
        if listing.status == ListingStatus.RESERVED:
            listing.status = ListingStatus.ACTIVE
            listing.reserved_by_id = None
            listing.reserved_until = None
        db.session.commit()
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
    transaction = Transaction.query.get_or_404(transaction_id)
    if current_user.id not in (transaction.buyer_id, transaction.seller_id):
        abort(403)
    if transaction.status in (TransactionStatus.PAID, TransactionStatus.READY_FOR_PICKUP):
        transaction.status = TransactionStatus.COMPLETED
        transaction.completed_at = datetime.utcnow()
        db.session.commit()
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

@transactions_bp.route("/listing/<int:listing_id>/request-donation", methods=["POST"])
@login_required
def request_donation(listing_id):
    listing = Listing.query.get_or_404(listing_id)
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
        flash("You've already requested this item - the donor will be in touch.", "info")
        return redirect(url_for("marketplace.listing_detail", listing_id=listing.id))

    donation_request = DonationRequest(
        listing_id=listing.id,
        requester_id=current_user.id,
        message=request.form.get("message", ""),
    )
    db.session.add(donation_request)
    db.session.commit()

    notify_user(
        listing.seller_id, NotificationType.DONATION_REQUEST,
        title="New donation request",
        body=f"{current_user.full_name} would like your donated '{listing.title}'.",
        link=url_for("transactions.manage_donation", request_id=donation_request.id),
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

    if action == "approve" and donation_request.status == DonationRequestStatus.PENDING:
        donation_request.status = DonationRequestStatus.APPROVED
        listing.status = ListingStatus.DONATED

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
    elif action == "decline":
        donation_request.status = DonationRequestStatus.DECLINED
        db.session.commit()
        notify_user(
            donation_request.requester_id, NotificationType.DONATION_REQUEST,
            title="Donation request declined",
            body=f"Your request for '{listing.title}' was declined.",
        )
        flash("Request declined.", "info")

    return redirect(url_for("marketplace.listing_detail", listing_id=listing.id))


# ---------------------------------------------------------------------------
# Swaps
# ---------------------------------------------------------------------------

@transactions_bp.route("/listing/<int:listing_id>/swap", methods=["GET", "POST"])
@login_required
def propose_swap(listing_id):
    target = Listing.query.get_or_404(listing_id)
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
        swap_request = SwapRequest(
            requester_id=current_user.id,
            target_listing_id=target.id,
            offered_listing_id=form.offered_listing_id.data,
            top_up_amount=form.top_up_amount.data or 0,
            message=form.message.data,
        )
        db.session.add(swap_request)
        db.session.commit()

        notify_user(
            target.seller_id, NotificationType.SWAP,
            title="New swap offer",
            body=f"{current_user.full_name} wants to swap for '{target.title}'.",
            link=url_for("transactions.manage_swap", swap_id=swap_request.id),
        )
        flash("Swap offer sent!", "success")
        return redirect(url_for("marketplace.listing_detail", listing_id=target.id))

    return render_template("transactions/propose_swap.html", target=target, form=form)


@transactions_bp.route("/swap/<int:swap_id>/<action>", methods=["POST"])
@login_required
def manage_swap(swap_id, action):
    swap_request = SwapRequest.query.get_or_404(swap_id)
    target = swap_request.target_listing
    if target.seller_id != current_user.id:
        abort(403)

    if action == "accept" and swap_request.status == SwapRequestStatus.PENDING:
        swap_request.status = SwapRequestStatus.ACCEPTED
        swap_request.responded_at = datetime.utcnow()
        target.status = ListingStatus.SWAPPED
        swap_request.offered_listing.status = ListingStatus.SWAPPED

        transaction = Transaction(
            reference=generate_transaction_reference(),
            listing_id=target.id,
            buyer_id=swap_request.requester_id,
            seller_id=target.seller_id,
            transaction_type=(
                TransactionType.SWAP_WITH_TOP_UP if swap_request.top_up_amount and swap_request.top_up_amount > 0
                else TransactionType.SWAP
            ),
            item_price=swap_request.top_up_amount or 0,
            service_fee=0,
            total_amount=swap_request.top_up_amount or 0,
            payment_method=PaymentMethod.NONE if not swap_request.top_up_amount else PaymentMethod.CARD,
            status=TransactionStatus.COMPLETED if not swap_request.top_up_amount else TransactionStatus.PENDING,
            pickup_location=current_app.config["SAFE_PICKUP_POINTS"][0],
        )
        db.session.add(transaction)
        db.session.commit()

        notify_user(
            swap_request.requester_id, NotificationType.SWAP,
            title="Your swap was accepted!",
            body=f"'{target.title}' swap accepted. Arrange a safe campus pickup.",
            link=url_for("transactions.receipt", transaction_id=transaction.id),
        )
        flash("Swap accepted!", "success")
        if swap_request.top_up_amount and swap_request.top_up_amount > 0:
            flash(f"A top-up payment of R{swap_request.top_up_amount} is required to finalise the swap.", "info")
            return redirect(url_for("transactions.checkout", transaction_id=transaction.id))

    elif action == "decline":
        swap_request.status = SwapRequestStatus.DECLINED
        swap_request.responded_at = datetime.utcnow()
        db.session.commit()
        notify_user(
            swap_request.requester_id, NotificationType.SWAP,
            title="Swap declined",
            body=f"Your swap offer for '{target.title}' was declined.",
        )
        flash("Swap declined.", "info")

    return redirect(url_for("marketplace.listing_detail", listing_id=target.id))


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
