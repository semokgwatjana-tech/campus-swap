from datetime import datetime

from flask import render_template, redirect, url_for, flash, request, send_from_directory, current_app
from flask_login import login_required, current_user

from app.main import main_bp
from app.extensions import db
from app.models import (
    Listing, ListingStatus, ListingType, Category, Notification, Wishlist,
    Message, Conversation, Transaction, User, Review, UserBadge
)


@main_bp.route("/sw.js")
def service_worker():
    # Served from the site root (not /static/sw.js) so the browser allows
    # the service worker to take scope "/" and actually control every page,
    # not just files under /static/. This is standard for Flask PWAs.
    response = send_from_directory(current_app.static_folder, "sw.js")
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-cache"
    return response


@main_bp.route("/")
def landing():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    # These are real, live counts from the database - never invented numbers.
    # On a brand-new install they will honestly show 0 until people join in.
    stats = {
        "students": User.query.filter_by(is_verified=True).count(),
        "listings": Listing.query.filter_by(status=ListingStatus.ACTIVE).count(),
        "donations": Listing.query.filter_by(listing_type=ListingType.DONATE).count(),
        "categories": Category.query.count(),
    }
    featured = (
        Listing.query.filter_by(status=ListingStatus.ACTIVE)
        .order_by(Listing.is_featured.desc(), Listing.posted_at.desc())
        .limit(6)
        .all()
    )
    return render_template("landing.html", stats=stats, featured=featured)


@main_bp.route("/dashboard")
@login_required
def dashboard():
    hour = datetime.now().hour
    greeting = "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"

    recommended = (
        Listing.query.filter(Listing.status == ListingStatus.ACTIVE, Listing.seller_id != current_user.id)
        .order_by(Listing.views_count.desc())
        .limit(4)
        .all()
    )
    latest = (
        Listing.query.filter(Listing.status == ListingStatus.ACTIVE, Listing.seller_id != current_user.id)
        .order_by(Listing.posted_at.desc())
        .limit(8)
        .all()
    )
    categories = Category.query.limit(8).all()

    conversations = (
        Conversation.query.filter(
            db.or_(Conversation.participant_one_id == current_user.id,
                   Conversation.participant_two_id == current_user.id)
        )
        .order_by(Conversation.created_at.desc())
        .limit(5)
        .all()
    )
    notifications = (
        Notification.query.filter_by(user_id=current_user.id)
        .order_by(Notification.created_at.desc())
        .limit(6)
        .all()
    )

    my_active_listings = Listing.query.filter_by(seller_id=current_user.id).count()
    my_completed_sales = Transaction.query.filter_by(seller_id=current_user.id).count()

    return render_template(
        "dashboard.html",
        greeting=greeting,
        recommended=recommended,
        latest=latest,
        categories=categories,
        conversations=conversations,
        notifications=notifications,
        my_active_listings=my_active_listings,
        my_completed_sales=my_completed_sales,
    )


@main_bp.route("/profile/<int:user_id>")
def public_profile(user_id):
    user = User.query.get_or_404(user_id)
    listings = Listing.query.filter_by(seller_id=user.id, status=ListingStatus.ACTIVE).all()
    reviews = Review.query.filter_by(reviewee_id=user.id).order_by(Review.created_at.desc()).all()
    badges = UserBadge.query.filter_by(user_id=user.id).all()
    return render_template("profile.html", profile_user=user, listings=listings, reviews=reviews, badges=badges)


@main_bp.route("/profile/edit", methods=["GET", "POST"])
@login_required
def edit_profile():
    profile = current_user.profile
    if request.method == "POST":
        profile.course = request.form.get("course", profile.course)
        profile.year_of_study = request.form.get("year_of_study", profile.year_of_study)
        profile.campus = request.form.get("campus", profile.campus)
        profile.bio = request.form.get("bio", profile.bio)

        from app.utils import save_uploaded_image
        new_pic = save_uploaded_image(request.files.get("profile_picture"), subfolder="profiles")
        if new_pic:
            profile.profile_picture = new_pic

        db.session.commit()
        flash("Profile updated successfully.", "success")
        return redirect(url_for("main.public_profile", user_id=current_user.id))

    return render_template("edit_profile.html")


@main_bp.route("/notifications")
@login_required
def notifications():
    items = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).all()
    for n in items:
        n.is_read = True
    db.session.commit()
    return render_template("notifications.html", notifications=items)


@main_bp.route("/wishlist")
@login_required
def wishlist():
    items = Wishlist.query.filter_by(user_id=current_user.id).order_by(Wishlist.added_at.desc()).all()
    return render_template("wishlist.html", items=items)


@main_bp.route("/wishlist/toggle/<int:listing_id>", methods=["POST"])
@login_required
def toggle_wishlist(listing_id):
    existing = Wishlist.query.filter_by(user_id=current_user.id, listing_id=listing_id).first()
    if existing:
        db.session.delete(existing)
        db.session.commit()
        flash("Removed from your wishlist.", "info")
    else:
        db.session.add(Wishlist(user_id=current_user.id, listing_id=listing_id))
        db.session.commit()
        flash("Added to your wishlist.", "success")
    return redirect(request.referrer or url_for("marketplace.browse"))


@main_bp.route("/impact")
@login_required
def impact_dashboard():
    """Personal activity summary: items sold, donated, earned, and spent."""
    from app.models import TransactionStatus, TransactionType

    completed = Transaction.query.filter_by(seller_id=current_user.id, status=TransactionStatus.COMPLETED).all()
    donations_made = Listing.query.filter_by(seller_id=current_user.id, listing_type=ListingType.DONATE,
                                               status=ListingStatus.DONATED).count()
    total_earned = sum(float(t.item_price) for t in completed if t.transaction_type == TransactionType.PURCHASE)

    purchases = Transaction.query.filter_by(buyer_id=current_user.id, status=TransactionStatus.COMPLETED).all()
    total_spent = sum(float(t.total_amount) for t in purchases)

    # Every number here comes directly from the user's own transaction
    # history - nothing is estimated or extrapolated.
    return render_template(
        "impact.html",
        books_sold=len(completed),
        donations_made=donations_made,
        total_earned=total_earned,
        total_spent=round(total_spent, 2),
        transactions_completed=len(completed) + len(purchases),
    )


# ---------------------------------------------------------------------
# Public legal pages. No login required - these must be readable by
# anyone before they create an account or make a purchase.
# ---------------------------------------------------------------------

@main_bp.route("/terms")
def terms():
    return render_template("legal/terms.html")


@main_bp.route("/privacy")
def privacy_policy():
    return render_template("legal/privacy_policy.html")


@main_bp.route("/refund-policy")
def refund_policy():
    return render_template("legal/refund_policy.html")
