from functools import wraps

from flask import render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user

from app.admin import admin_bp
from app.extensions import db
from app.models import (
    User, Listing, ListingStatus, Report, ReportStatus, Dispute,
    Transaction, TransactionStatus, PlatformSetting,
)


def admin_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return view_func(*args, **kwargs)
    return wrapped


@admin_bp.route("/")
@login_required
@admin_required
def dashboard():
    stats = {
        "total_users": User.query.count(),
        "verified_users": User.query.filter_by(is_verified=True).count(),
        "pending_verification": User.query.filter_by(is_verified=False).count(),
        "active_listings": Listing.query.filter_by(status=ListingStatus.ACTIVE).count(),
        "open_reports": Report.query.filter_by(status=ReportStatus.OPEN).count(),
        "open_disputes": Dispute.query.filter_by(status=ReportStatus.OPEN).count(),
        "completed_transactions": Transaction.query.filter_by(status=TransactionStatus.COMPLETED).count(),
        "gross_transaction_value": sum(
            float(t.total_amount) for t in Transaction.query.filter_by(status=TransactionStatus.COMPLETED).all()
        ),
    }
    return render_template("admin/dashboard.html", stats=stats)


@admin_bp.route("/users")
@login_required
@admin_required
def manage_users():
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template("admin/users.html", users=users)


@admin_bp.route("/users/<int:user_id>/verify", methods=["POST"])
@login_required
@admin_required
def verify_user(user_id):
    user = User.query.get_or_404(user_id)
    user.is_verified = True
    db.session.commit()
    flash(f"{user.full_name} is now a verified student.", "success")
    return redirect(url_for("admin.manage_users"))


@admin_bp.route("/users/<int:user_id>/suspend", methods=["POST"])
@login_required
@admin_required
def suspend_user(user_id):
    user = User.query.get_or_404(user_id)
    user.is_active_account = not user.is_active_account
    db.session.commit()
    action = "reinstated" if user.is_active_account else "suspended"
    flash(f"Account for {user.full_name} has been {action}.", "info")
    return redirect(url_for("admin.manage_users"))


@admin_bp.route("/listings")
@login_required
@admin_required
def manage_listings():
    listings = Listing.query.order_by(Listing.posted_at.desc()).all()
    return render_template("admin/listings.html", listings=listings)


@admin_bp.route("/listings/<int:listing_id>/approve", methods=["POST"])
@login_required
@admin_required
def approve_listing(listing_id):
    listing = Listing.query.get_or_404(listing_id)
    listing.status = ListingStatus.ACTIVE
    db.session.commit()
    flash("Listing approved and now live.", "success")
    return redirect(url_for("admin.manage_listings"))


@admin_bp.route("/listings/<int:listing_id>/remove", methods=["POST"])
@login_required
@admin_required
def remove_listing(listing_id):
    listing = Listing.query.get_or_404(listing_id)
    listing.status = ListingStatus.REMOVED
    db.session.commit()
    flash("Listing removed for policy violation.", "info")
    return redirect(url_for("admin.manage_listings"))


@admin_bp.route("/reports")
@login_required
@admin_required
def reports():
    items = Report.query.order_by(Report.created_at.desc()).all()
    return render_template("admin/reports.html", reports=items)


@admin_bp.route("/reports/<int:report_id>/resolve", methods=["POST"])
@login_required
@admin_required
def resolve_report(report_id):
    report = Report.query.get_or_404(report_id)
    report.status = ReportStatus.RESOLVED
    db.session.commit()
    flash("Report marked as resolved.", "success")
    return redirect(url_for("admin.reports"))


@admin_bp.route("/disputes")
@login_required
@admin_required
def disputes():
    items = Dispute.query.order_by(Dispute.created_at.desc()).all()
    return render_template("admin/disputes.html", disputes=items)


@admin_bp.route("/disputes/<int:dispute_id>/resolve", methods=["POST"])
@login_required
@admin_required
def resolve_dispute(dispute_id):
    from datetime import datetime
    dispute = Dispute.query.get_or_404(dispute_id)
    dispute.status = ReportStatus.RESOLVED
    dispute.resolved_at = datetime.utcnow()
    dispute.admin_notes = request.form.get("admin_notes", "")

    resolution = request.form.get("resolution")
    if resolution == "refund":
        dispute.transaction.status = TransactionStatus.REFUNDED
    elif resolution == "release":
        dispute.transaction.status = TransactionStatus.COMPLETED

    db.session.commit()
    flash("Dispute resolved.", "success")
    return redirect(url_for("admin.disputes"))


@admin_bp.route("/settings", methods=["GET", "POST"])
@login_required
@admin_required
def settings():
    if request.method == "POST":
        PlatformSetting.set("service_fee_percent", request.form.get("service_fee_percent", "2.5"))
        PlatformSetting.set("service_fee_fixed", request.form.get("service_fee_fixed", "0"))
        flash("Platform settings updated.", "success")
        return redirect(url_for("admin.settings"))

    current_fee_percent = PlatformSetting.get("service_fee_percent", "2.5")
    current_fee_fixed = PlatformSetting.get("service_fee_fixed", "0")
    return render_template("admin/settings.html", fee_percent=current_fee_percent, fee_fixed=current_fee_fixed)


@admin_bp.route("/analytics")
@login_required
@admin_required
def analytics():
    from app.models import ListingType, TransactionType

    total_completed = Transaction.query.filter_by(status=TransactionStatus.COMPLETED).all()
    books_sold = len([t for t in total_completed if t.transaction_type == TransactionType.PURCHASE])
    donations = len([t for t in total_completed if t.transaction_type == TransactionType.DONATION])
    swaps = len([t for t in total_completed if t.transaction_type in
                 (TransactionType.SWAP, TransactionType.SWAP_WITH_TOP_UP)])
    money_moved = sum(float(t.total_amount) for t in total_completed)

    return render_template(
        "admin/analytics.html",
        books_sold=books_sold,
        donations=donations,
        swaps=swaps,
        money_moved=money_moved,
        total_transactions=len(total_completed),
        total_users=User.query.count(),
    )
