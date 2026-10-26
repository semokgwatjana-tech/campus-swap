from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from functools import wraps

from flask import render_template, redirect, url_for, flash, request, abort, current_app
from flask_login import login_required, current_user

from app.accounts import log_event, confirmed_guardian
from app.admin import admin_bp
from app.age_rules import dob_problem
from app.extensions import db
from app.models import (
    User, Listing, ListingStatus, Report, ReportStatus, Dispute,
    Transaction, TransactionStatus, PlatformSetting,
)


def admin_required(view_func):
    """Only administrators, and only with two-step verification switched on, because an
    admin account can reach every student's information."""
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        if current_app.config.get("REQUIRE_ADMIN_2FA") and not current_user.two_factor_enabled:
            flash("Administrators must turn on two-step verification before using the admin area.", "warning")
            return redirect(url_for("settings.two_step"))
        return view_func(*args, **kwargs)
    return wrapped


def _record(detail):
    """Every admin action is written to the admin's own activity log."""
    log_event(current_user.id, "admin_action", detail[:190])


def _live_users():
    return User.query.filter(User.deleted_at.is_(None))


@admin_bp.route("/")
@login_required
@admin_required
def dashboard():
    completed = Transaction.query.filter_by(status=TransactionStatus.COMPLETED).all()
    stats = {
        "total_users": _live_users().count(),
        "verified_users": _live_users().filter_by(is_verified=True).count(),
        # waiting for an admin: email confirmed, not yet verified, not suspended
        "pending_verification": _live_users().filter_by(is_verified=False, is_active_account=True,
                                                        email_confirmed=True).count(),
        "active_listings": Listing.query.filter_by(status=ListingStatus.ACTIVE).count(),
        "open_reports": Report.query.filter_by(status=ReportStatus.OPEN).count(),
        "open_disputes": Dispute.query.filter_by(status=ReportStatus.OPEN).count(),
        "completed_transactions": len(completed),
        "gross_transaction_value": sum(float(t.total_amount) for t in completed),
    }
    return render_template("admin/dashboard.html", stats=stats)


@admin_bp.route("/users")
@login_required
@admin_required
def manage_users():
    users = _live_users().order_by(User.created_at.desc()).all()
    return render_template("admin/users.html", users=users)


@admin_bp.route("/users/<int:user_id>/verify", methods=["POST"])
@login_required
@admin_required
def verify_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.deleted_at or not user.is_active_account:
        flash("This account is closed or suspended.", "danger")
    elif not user.email_confirmed:
        flash("This person has not confirmed their email address yet.", "danger")
    elif user.is_minor and not confirmed_guardian(user.id):
        flash("This learner's parent or guardian has not confirmed yet. Verify only after they do.", "danger")
    else:
        user.is_verified = True
        db.session.commit()
        _record(f"verified user #{user.id}")
        flash(f"{user.full_name} is now a verified student.", "success")
    return redirect(url_for("admin.manage_users"))


@admin_bp.route("/users/<int:user_id>/suspend", methods=["POST"])
@login_required
@admin_required
def suspend_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id or user.is_admin:
        flash("An administrator account cannot be suspended here. Remove the admin role first.", "danger")
        return redirect(url_for("admin.manage_users"))
    user.is_active_account = not user.is_active_account
    if not user.is_active_account:
        user.session_version = (user.session_version or 0) + 1      # signs them out everywhere now
    db.session.commit()
    action = "reinstated" if user.is_active_account else "suspended"
    _record(f"{action} user #{user.id}")
    flash(f"Account for {user.full_name} has been {action}.", "info")
    return redirect(url_for("admin.manage_users"))


@admin_bp.route("/users/<int:user_id>/date-of-birth", methods=["POST"])
@login_required
@admin_required
def set_date_of_birth(user_id):
    """A date of birth cannot be changed by the person, so a genuine mistake is fixed here,
    with a reason that is written to the activity log."""
    user = User.query.get_or_404(user_id)
    reason = request.form.get("reason", "").strip()
    try:
        dob = datetime.strptime(request.form.get("date_of_birth", ""), "%Y-%m-%d").date()
    except ValueError:
        dob = None
    problem = dob_problem(dob, date.today())
    if user.deleted_at:
        flash("This account is closed.", "danger")
    elif problem:
        flash(problem, "danger")
    elif len(reason) < 5:
        flash("Write the reason for the change (at least 5 characters).", "danger")
    else:
        user.date_of_birth = dob
        db.session.commit()
        log_event(user.id, "admin_action", f"date of birth corrected by admin #{current_user.id}: {reason[:120]}")
        _record(f"corrected date of birth of user #{user.id}")
        flash("Date of birth updated.", "success")
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
    if listing.status not in (ListingStatus.PENDING_APPROVAL, ListingStatus.REMOVED):
        flash("Only a listing that is waiting for approval or was removed can be approved.", "info")
    else:
        listing.status = ListingStatus.ACTIVE
        db.session.commit()
        _record(f"approved listing #{listing.id}")
        flash("Listing approved and now live.", "success")
    return redirect(url_for("admin.manage_listings"))


@admin_bp.route("/listings/<int:listing_id>/remove", methods=["POST"])
@login_required
@admin_required
def remove_listing(listing_id):
    listing = Listing.query.get_or_404(listing_id)
    if listing.status not in (ListingStatus.ACTIVE, ListingStatus.PENDING_APPROVAL):
        flash("A listing cannot be removed while it is reserved or after it has been sold, swapped or donated.", "info")
    else:
        listing.status = ListingStatus.REMOVED
        db.session.commit()
        _record(f"removed listing #{listing.id}")
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
    if report.status in (ReportStatus.OPEN, ReportStatus.REVIEWING):
        report.status = ReportStatus.RESOLVED
        db.session.commit()
        _record(f"resolved report #{report.id}")
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
    dispute = Dispute.query.get_or_404(dispute_id)
    if dispute.status not in (ReportStatus.OPEN, ReportStatus.REVIEWING):
        flash("This dispute was already resolved.", "info")
        return redirect(url_for("admin.disputes"))

    resolution = request.form.get("resolution", "")
    if resolution not in ("refund", "release", "none"):
        flash("Choose how the dispute is resolved.", "danger")
        return redirect(url_for("admin.disputes"))
    movable = (TransactionStatus.PAID, TransactionStatus.READY_FOR_PICKUP,
               TransactionStatus.REFUND_REQUESTED, TransactionStatus.COMPLETED)
    if resolution != "none" and dispute.transaction.status not in movable:
        flash("The transaction is not in a state that can be changed this way.", "danger")
        return redirect(url_for("admin.disputes"))

    dispute.status = ReportStatus.RESOLVED
    dispute.resolved_at = datetime.utcnow()
    dispute.admin_notes = request.form.get("admin_notes", "").strip()[:2000]
    if resolution == "refund":
        dispute.transaction.status = TransactionStatus.REFUNDED
    elif resolution == "release":
        dispute.transaction.status = TransactionStatus.COMPLETED
        dispute.transaction.completed_at = dispute.transaction.completed_at or datetime.utcnow()
    db.session.commit()
    _record(f"resolved dispute #{dispute.id} as {resolution}")
    flash("Dispute resolved.", "success")
    return redirect(url_for("admin.disputes"))


@admin_bp.route("/settings", methods=["GET", "POST"])
@login_required
@admin_required
def settings():
    if request.method == "POST":
        try:
            percent = Decimal(request.form.get("service_fee_percent", "").strip())
            fixed = Decimal(request.form.get("service_fee_fixed", "").strip())
        except InvalidOperation:
            percent = fixed = None
        # A bad number here would break every checkout, so only sensible values are saved.
        if percent is None or not (Decimal("0") <= percent <= Decimal("20")) \
                or not (Decimal("0") <= fixed <= Decimal("50")):
            flash("Enter a percentage from 0 to 20 and a fixed fee from R0 to R50.", "danger")
            return redirect(url_for("admin.settings"))
        PlatformSetting.set("service_fee_percent", str(percent))
        PlatformSetting.set("service_fee_fixed", str(fixed))
        _record(f"set service fee to {percent}% + R{fixed}")
        flash("Platform settings updated.", "success")
        return redirect(url_for("admin.settings"))

    current_fee_percent = PlatformSetting.get("service_fee_percent", "2.5")
    current_fee_fixed = PlatformSetting.get("service_fee_fixed", "0")
    return render_template("admin/settings.html", fee_percent=current_fee_percent, fee_fixed=current_fee_fixed)


@admin_bp.route("/analytics")
@login_required
@admin_required
def analytics():
    from app.models import TransactionType

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
        total_users=_live_users().count(),
    )


@admin_bp.route("/feedback")
@login_required
@admin_required
def feedback():
    from app.models import Feedback
    items = Feedback.query.order_by(Feedback.created_at.desc()).limit(200).all()
    return render_template("admin/feedback.html", items=items)
