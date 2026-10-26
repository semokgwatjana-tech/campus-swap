"""
Account helpers shared by sign-in, settings, the parent portal and admin:
the activity log, email confirmation, guardian emails and closing an account.
"""

import random
import re
import secrets
from datetime import datetime, timedelta

from flask import current_app, request, url_for
from werkzeug.security import generate_password_hash

from app.extensions import db
from app.mailer import send_email
from app.models import (
    User, Listing, ListingStatus, Wishlist, Transaction, TransactionStatus, Dispute, ReportStatus,
    SecurityEvent, Guardian, GuardianSignIn, UserSettings,
)
from app.ratelimit import ip_hash
from app.security import new_token, hash_token

EVENT_LABELS = {
    "login": "Signed in", "login_failed": "Wrong password entered", "login_locked": "Sign-in locked after too many tries",
    "twofa_failed": "Wrong two-step code entered", "logout_everywhere": "Signed out of all devices",
    "password_changed": "Password changed", "password_reset": "Password reset by email",
    "email_changed": "Email address changed", "phone_changed": "Phone number changed",
    "twofa_on": "Two-step verification turned on", "twofa_off": "Two-step verification turned off",
    "email_confirmed": "Email address confirmed",
    "guardian_confirmed": "A parent or guardian confirmed this account",
    "guardian_paused": "Account paused by a parent or guardian", "guardian_resumed": "Account resumed by a parent or guardian",
    "guardian_paid_on": "Buying and selling allowed by a parent or guardian",
    "guardian_paid_off": "Buying and selling switched off by a parent or guardian",
    "aged_out": "Moved to the adult side on turning 18", "registered": "Account created",
    "admin_action": "Administrator action",
}


def log_event(user_id, kind, detail=None):
    """Record something that happened on an account. Commits straight away."""
    db.session.add(SecurityEvent(user_id=user_id, kind=kind, detail=(detail or None),
                                 ip_hash=ip_hash(), user_agent=(request.user_agent.string or "")[:200]))
    db.session.commit()
    if random.random() < 0.02:
        SecurityEvent.query.filter(SecurityEvent.created_at < datetime.utcnow() - timedelta(days=90)).delete()
        db.session.commit()


def security_alert(user, subject, line):
    """In-app notice, plus an email when the person has security emails on and email works.
    A failed email never blocks the action itself."""
    from app.mailer import mail_is_configured
    from app.models import NotificationType
    from app.utils import notify_user
    try:
        link = url_for("settings.account")
    except RuntimeError:
        link = None
    notify_user(user.id, NotificationType.SYSTEM, subject, line, link)
    if UserSettings.for_user(user.id).security_alerts and mail_is_configured():
        send_email(user.school_email, f"Campus Swap security alert: {subject}",
                   f"Hi {first_name(user)},\n\n{line}\n\nIf this was not you, reset your password straight away "
                   f"and contact {current_app.config['SUPPORT_EMAIL']}.\n\nCampus Swap")


def browser_summary(user_agent):
    ua = user_agent or ""
    browser = next((n for k, n in (("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox/", "Firefox"),
                                    ("Chrome/", "Chrome"), ("Safari/", "Safari")) if k in ua), "A browser")
    system = next((n for k, n in (("Windows", "Windows"), ("Android", "Android"), ("iPhone", "iPhone"),
                                   ("iPad", "iPad"), ("Mac OS", "Mac"), ("Linux", "Linux")) if k in ua), "")
    return f"{browser} on {system}" if system else browser


def first_name(user):
    return (user.full_name or "there").split(" ")[0]


# ---------------------------------------------------------------- email confirmation

def start_email_verification(user):
    """Create a fresh link, store only its hash, and email it. Returns True if sent."""
    token = new_token()
    user.email_token_hash = hash_token(token)
    user.email_token_sent_at = datetime.utcnow()
    user.email_token_expires = datetime.utcnow() + timedelta(hours=current_app.config["EMAIL_VERIFY_HOURS"])
    db.session.commit()
    link = url_for("auth.verify_email", token=token, _external=True)
    return send_email(
        user.school_email, "Confirm your Campus Swap email",
        f"Hi {first_name(user)},\n\nPlease confirm this email address to finish creating your "
        f"Campus Swap account. The link works for {current_app.config['EMAIL_VERIFY_HOURS']} hours:\n\n{link}\n\n"
        "If you did not create an account, ignore this email and nothing will happen.\n\nCampus Swap")


# ---------------------------------------------------------------- guardians

def confirmed_guardian(learner_id):
    return Guardian.query.filter_by(learner_id=learner_id, status="confirmed").first()


def pending_guardian(learner_id):
    return (Guardian.query.filter_by(learner_id=learner_id, status="pending")
            .order_by(Guardian.created_at.desc()).first())


def send_guardian_confirmation(guardian):
    token = new_token()
    guardian.token_hash = hash_token(token)
    guardian.token_expires = datetime.utcnow() + timedelta(days=current_app.config["GUARDIAN_LINK_DAYS"])
    db.session.commit()
    learner = guardian.learner
    link = url_for("parents.confirm", token=token, _external=True)
    return send_email(
        guardian.guardian_email, f"Please confirm {first_name(learner)}'s Campus Swap account",
        f"Hello{(' ' + guardian.guardian_name) if guardian.guardian_name else ''},\n\n"
        f"{learner.full_name} has asked to use Campus Swap, a marketplace where students buy, sell, swap and "
        "donate study materials. They are under 18, so their account stays locked until a parent or legal "
        "guardian agrees.\n\n"
        f"To read what that involves and confirm, open this link within {current_app.config['GUARDIAN_LINK_DAYS']} days:\n\n"
        f"{link}\n\n"
        "If you do not know this person, or did not expect this email, ignore it and the account stays locked.\n\n"
        "Campus Swap")


def add_guardian(learner, name, email):
    """Replace any waiting guardian request with a new one and email it."""
    for old in Guardian.query.filter_by(learner_id=learner.id, status="pending").all():
        old.status = "revoked"
        old.token_hash = None
    guardian = Guardian(learner_id=learner.id, guardian_name=(name or "").strip() or None,
                        guardian_email=email.lower().strip())
    db.session.add(guardian)
    db.session.commit()
    sent = send_guardian_confirmation(guardian)
    return guardian, sent


def guardian_children(email):
    """The learners this guardian email is confirmed for."""
    rows = (Guardian.query.filter(Guardian.guardian_email == email.lower().strip(), Guardian.status == "confirmed")
            .all())
    return [g.learner for g in rows if g.learner and not g.learner.deleted_at]


def send_guardian_signin(email):
    """Email a one-time portal link if this address is a confirmed guardian. The
    caller never tells the visitor whether it was."""
    email = email.lower().strip()
    if not Guardian.query.filter_by(guardian_email=email, status="confirmed").first():
        return False
    token = new_token()
    db.session.add(GuardianSignIn(
        email=email, token_hash=hash_token(token),
        expires_at=datetime.utcnow() + timedelta(minutes=current_app.config["GUARDIAN_SIGNIN_MINUTES"])))
    db.session.commit()
    link = url_for("parents.enter", token=token, _external=True)
    return send_email(
        email, "Your Campus Swap parent portal link",
        f"Use this link to open the Campus Swap parent portal. It works once and expires in "
        f"{current_app.config['GUARDIAN_SIGNIN_MINUTES']} minutes:\n\n{link}\n\n"
        "If you did not ask for this, ignore this email.\n\nCampus Swap")


# ---------------------------------------------------------------- closing an account

OPEN_TRANSACTION_STATUSES = (
    TransactionStatus.PAYMENT_PROCESSING, TransactionStatus.PAID, TransactionStatus.RESERVED,
    TransactionStatus.READY_FOR_PICKUP, TransactionStatus.REFUND_REQUESTED,
)


def open_work(user):
    """(open transactions, open disputes). An account cannot close while either exists."""
    open_tx = Transaction.query.filter(
        db.or_(Transaction.buyer_id == user.id, Transaction.seller_id == user.id),
        Transaction.status.in_(OPEN_TRANSACTION_STATUSES)).count()
    open_disputes = (Dispute.query.join(Transaction, Dispute.transaction_id == Transaction.id)
                     .filter(db.or_(Transaction.buyer_id == user.id, Transaction.seller_id == user.id),
                             Dispute.status.in_([ReportStatus.OPEN, ReportStatus.REVIEWING])).count())
    return open_tx, open_disputes


def close_account(user):
    """Anonymise the account instead of deleting rows, so other people's receipts, chats and
    reviews keep working and records the law requires us to keep stay intact. The caller must
    already have checked open_work() and, where needed, a password."""
    now = datetime.utcnow()
    for listing in Listing.query.filter_by(seller_id=user.id).filter(
            Listing.status.in_([ListingStatus.ACTIVE, ListingStatus.PENDING_APPROVAL, ListingStatus.RESERVED])).all():
        listing.status = ListingStatus.REMOVED
    Wishlist.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    for guardian in Guardian.query.filter_by(learner_id=user.id).all():
        guardian.status, guardian.ended_at, guardian.token_hash = "ended", now, None
        guardian.guardian_name, guardian.guardian_email = None, f"closed-{guardian.id}@deleted.invalid"
    SecurityEvent.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    user.full_name = "Deleted user"
    user.student_number = f"deleted-{user.id}"
    user.school_email = f"deleted-{user.id}@deleted.invalid"
    user.password_hash = generate_password_hash(secrets.token_urlsafe(32))
    user.username = user.phone_number = None
    user.pending_email = user.pending_email_token = user.pending_email_expires = None
    user.password_reset_token = user.password_reset_expires = None
    user.email_token_hash = user.email_token_expires = None
    user.two_factor_enabled, user.two_factor_secret, user.recovery_codes = False, None, None
    user.invite_code = None
    user.date_of_birth = None
    user.session_version = (user.session_version or 0) + 1      # signs out every device
    user.is_active_account, user.is_verified, user.deleted_at = False, False, now
    if user.profile:
        user.profile.bio = user.profile.course = None
        user.profile.profile_picture = "default_avatar.png"
    db.session.commit()
