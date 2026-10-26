"""
Parents and guardians of learners (under 18).

How it works:
  1. A learner signs up with their date of birth and a parent's email. Their account stays
     locked (the "waiting" page) until a parent confirms.
  2. The parent opens the emailed link, reads what is involved and confirms. No account or
     password is needed for that.
  3. To keep an eye on the account, the parent asks for a one-time sign-in link by email and
     enters the parent portal: they can read their child's chats, listings and purchases, pause
     the account, allow or stop buying and selling, or close the account.
"""

import time
from datetime import date, datetime
from functools import wraps

from flask import (
    render_template, redirect, url_for, flash, request, current_app, session, abort,
)
from flask_login import login_required, current_user

from app import ratelimit as rl
from app.accounts import (
    log_event, add_guardian, send_guardian_confirmation, send_guardian_signin, guardian_children,
    confirmed_guardian, pending_guardian, open_work, close_account, browser_summary, EVENT_LABELS,
)
from app.extensions import db
from app.forms import (
    AgeGateForm, GuardianContactForm, GuardianConfirmForm, GuardianSignInForm,
)
from app.models import (
    Guardian, GuardianSignIn, Listing, Transaction, Conversation, Message, SecurityEvent,
    NotificationType,
)
from app.parents import parents_bp
from app.ratelimit_rules import minutes_text
from app.security import hash_token, mask_email
from app.age_rules import side_of
from app.utils import notify_user


# ---------------------------------------------------------------------------
# Learner side: date of birth, waiting for a guardian, paused
# ---------------------------------------------------------------------------

@parents_bp.route("/age", methods=["GET", "POST"])
@login_required
def age_gate():
    """Asked once of an account that has no date of birth yet. It cannot be changed afterwards
    by the person (only an administrator can correct it)."""
    if current_user.date_of_birth is not None:
        return redirect(url_for("main.dashboard"))
    form = AgeGateForm()
    if form.validate_on_submit():
        current_user.date_of_birth = form.date_of_birth.data
        db.session.commit()
        if current_user.is_minor:
            add_guardian(current_user, form.guardian_name.data, form.guardian_email.data)
            flash("Thank you. We emailed your parent or guardian to confirm your account.", "info")
            return redirect(url_for("parents.waiting"))
        flash("Thank you. Your date of birth is saved.", "success")
        return redirect(url_for("main.dashboard"))
    return render_template("parents/age_gate.html", form=form)


@parents_bp.route("/waiting", methods=["GET"])
@login_required
def waiting():
    if not current_user.is_minor or confirmed_guardian(current_user.id):
        return redirect(url_for("main.dashboard"))
    pending = pending_guardian(current_user.id)
    return render_template("parents/waiting.html", pending=pending,
                           masked=mask_email(pending.guardian_email) if pending else None,
                           form=GuardianContactForm())


@parents_bp.route("/waiting/resend", methods=["POST"])
@login_required
def resend_guardian():
    pending = pending_guardian(current_user.id)
    if not current_user.is_minor or not pending:
        return redirect(url_for("parents.waiting"))
    account = str(current_user.id)
    allowed, wait = rl.check("guardian", account)
    if not allowed:
        flash(f"Please wait {minutes_text(wait)} before asking for another email.", "info")
    else:
        rl.hit("guardian", account)
        send_guardian_confirmation(pending)
        flash("We sent the email again.", "success")
    return redirect(url_for("parents.waiting"))


@parents_bp.route("/waiting/change", methods=["POST"])
@login_required
def change_guardian():
    if not current_user.is_minor or confirmed_guardian(current_user.id):
        return redirect(url_for("main.dashboard"))
    form = GuardianContactForm()
    if form.validate_on_submit():
        email = form.guardian_email.data.lower().strip()
        allowed, wait = rl.check("guardian", str(current_user.id))
        if email == current_user.school_email:
            flash("Your parent or guardian needs their own email address.", "danger")
        elif not allowed:
            flash(f"Please wait {minutes_text(wait)} before trying again.", "info")
        else:
            rl.hit("guardian", str(current_user.id))
            add_guardian(current_user, form.guardian_name.data, email)
            flash("We emailed that address.", "success")
    else:
        flash("Enter your parent or guardian's name and a valid email address.", "danger")
    return redirect(url_for("parents.waiting"))


@parents_bp.route("/paused")
@login_required
def paused():
    if not current_user.is_minor or not current_user.parent_paused:
        return redirect(url_for("main.dashboard"))
    return render_template("parents/paused.html")


# ---------------------------------------------------------------------------
# Guardian confirmation (public link from the email)
# ---------------------------------------------------------------------------

def _guardian_for_token(token):
    guardian = Guardian.query.filter_by(token_hash=hash_token(token), status="pending").first()
    if (not guardian or not guardian.token_expires or guardian.token_expires < datetime.utcnow()
            or not guardian.learner or guardian.learner.deleted_at):
        return None
    return guardian


@parents_bp.route("/confirm/<token>", methods=["GET", "POST"])
def confirm(token):
    guardian = _guardian_for_token(token)
    if guardian is None:
        return render_template("parents/confirm_invalid.html"), 404
    form = GuardianConfirmForm()
    if request.method == "GET":
        form.guardian_name.data = guardian.guardian_name
    if form.validate_on_submit():
        allowed, wait = rl.check("guardian")
        if not allowed:
            flash(f"Too many tries. Please wait {minutes_text(wait)}.", "danger")
        else:
            rl.hit("guardian")
            learner = guardian.learner
            guardian.status = "confirmed"
            guardian.guardian_name = form.guardian_name.data.strip()
            guardian.confirmed_at = datetime.utcnow()
            guardian.token_hash = guardian.token_expires = None
            db.session.commit()
            log_event(learner.id, "guardian_confirmed")
            notify_user(learner.id, NotificationType.SYSTEM, "Your parent or guardian confirmed your account",
                        "You can use Campus Swap now.", url_for("main.dashboard"))
            return render_template("parents/confirmed.html", learner=learner)
    return render_template("parents/confirm.html", guardian=guardian, learner=guardian.learner, form=form)


# ---------------------------------------------------------------------------
# Parent portal (one-time email link, separate from the learner's sign-in)
# ---------------------------------------------------------------------------

def guardian_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        email = session.get("guardian_email")
        started = session.get("guardian_at", 0)
        limit = current_app.config["GUARDIAN_SESSION_HOURS"] * 3600
        if not email or time.time() - started > limit:
            session.pop("guardian_email", None)
            session.pop("guardian_at", None)
            flash("Please sign in to the parent portal.", "info")
            return redirect(url_for("parents.sign_in"))
        return view(*args, **kwargs)
    return wrapped


def _child_or_404(learner_id):
    for child in guardian_children(session["guardian_email"]):
        if child.id == learner_id:
            return child
    abort(404)


@parents_bp.route("/sign-in", methods=["GET", "POST"])
def sign_in():
    form = GuardianSignInForm()
    if form.validate_on_submit():
        email = form.email.data.lower().strip()
        allowed, _wait = rl.check("guardian", email)
        if allowed:
            rl.hit("guardian", email)
            send_guardian_signin(email)
        # Same answer whether or not the address is a guardian, so this cannot be used to find out.
        flash("If that email belongs to a parent or guardian on Campus Swap, we sent a sign-in link. "
              "It works once and expires soon.", "info")
        return redirect(url_for("parents.sign_in"))
    return render_template("parents/sign_in.html", form=form)


@parents_bp.route("/enter/<token>")
def enter(token):
    row = GuardianSignIn.query.filter_by(token_hash=hash_token(token)).first()
    if not row or row.used_at or row.expires_at < datetime.utcnow():
        flash("That sign-in link is invalid or has expired. Ask for a new one.", "danger")
        return redirect(url_for("parents.sign_in"))
    row.used_at = datetime.utcnow()
    db.session.commit()
    session["guardian_email"] = row.email
    session["guardian_at"] = time.time()
    return redirect(url_for("parents.home"))


@parents_bp.route("/sign-out", methods=["POST"])
def sign_out():
    session.pop("guardian_email", None)
    session.pop("guardian_at", None)
    flash("You are signed out of the parent portal.", "info")
    return redirect(url_for("parents.sign_in"))


@parents_bp.route("/")
@guardian_required
def home():
    return render_template("parents/home.html", children=guardian_children(session["guardian_email"]),
                           email=session["guardian_email"])


@parents_bp.route("/child/<int:learner_id>")
@guardian_required
def child(learner_id):
    learner = _child_or_404(learner_id)
    listings = Listing.query.filter_by(seller_id=learner.id).order_by(Listing.posted_at.desc()).limit(50).all()
    transactions = (Transaction.query
                    .filter(db.or_(Transaction.buyer_id == learner.id, Transaction.seller_id == learner.id))
                    .order_by(Transaction.created_at.desc()).limit(30).all())
    conversations = (Conversation.query
                     .filter(db.or_(Conversation.participant_one_id == learner.id,
                                    Conversation.participant_two_id == learner.id))
                     .order_by(Conversation.created_at.desc()).limit(50).all())
    events = SecurityEvent.query.filter_by(user_id=learner.id).order_by(SecurityEvent.created_at.desc()).limit(15).all()
    return render_template("parents/child.html", learner=learner, listings=listings, transactions=transactions,
                           conversations=conversations, events=events, labels=EVENT_LABELS,
                           browser_summary=browser_summary)


@parents_bp.route("/child/<int:learner_id>/chat/<int:conversation_id>")
@guardian_required
def chat(learner_id, conversation_id):
    learner = _child_or_404(learner_id)
    convo = Conversation.query.get_or_404(conversation_id)
    if learner.id not in (convo.participant_one_id, convo.participant_two_id):
        abort(404)
    messages = Message.query.filter_by(conversation_id=convo.id).order_by(Message.sent_at.asc()).all()
    return render_template("parents/chat.html", learner=learner, conversation=convo, messages=messages)


@parents_bp.route("/child/<int:learner_id>/pause", methods=["POST"])
@guardian_required
def pause(learner_id):
    learner = _child_or_404(learner_id)
    learner.parent_paused = not learner.parent_paused
    db.session.commit()
    log_event(learner.id, "guardian_paused" if learner.parent_paused else "guardian_resumed")
    flash("Account paused. Your child cannot use Campus Swap until you resume it."
          if learner.parent_paused else "Account resumed.", "success")
    return redirect(url_for("parents.child", learner_id=learner.id))


@parents_bp.route("/child/<int:learner_id>/paid-trades", methods=["POST"])
@guardian_required
def paid_trades(learner_id):
    learner = _child_or_404(learner_id)
    learner.allow_paid_trades = not learner.allow_paid_trades
    db.session.commit()
    log_event(learner.id, "guardian_paid_on" if learner.allow_paid_trades else "guardian_paid_off")
    flash("Buying and selling is now allowed." if learner.allow_paid_trades
          else "Buying and selling is switched off. Swapping and donating still work.", "success")
    return redirect(url_for("parents.child", learner_id=learner.id))


@parents_bp.route("/child/<int:learner_id>/close", methods=["POST"])
@guardian_required
def close(learner_id):
    learner = _child_or_404(learner_id)
    open_tx, open_disputes = open_work(learner)
    if request.form.get("confirm_text", "").strip() != "CLOSE":
        flash("Type CLOSE to confirm.", "danger")
    elif open_tx or open_disputes:
        flash("The account cannot be closed while a purchase, sale or dispute is still open.", "danger")
    else:
        close_account(learner)
        flash("The account has been closed.", "success")
        return redirect(url_for("parents.home"))
    return redirect(url_for("parents.child", learner_id=learner.id))
