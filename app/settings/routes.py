"""
Settings: account, privacy, appearance, accessibility, lists, chats, storage,
invitations, help, updates and account deletion.

Every setting on these pages is stored in the database and has an effect in
the app. Notifications is not built yet and appears on the Settings home page
marked "Coming soon" without a link.
"""

import json
import os
import re
import secrets
from datetime import datetime, timedelta

from flask import (
    render_template, redirect, url_for, flash, request, current_app,
    session, abort, Response,
)
from flask_login import login_required, current_user, login_user, logout_user

from app import ratelimit as rl
from app.accounts import (
    log_event, security_alert, open_work, close_account, browser_summary, confirmed_guardian,
    pending_guardian, EVENT_LABELS,
)
from app.extensions import db
from app.mailer import send_email, mail_is_configured
from app.models import (
    User, UserSettings, Feedback, THEMES, LIST_GROUPS,
    Conversation, Message, Listing, ListingImage, ListingStatus, ListingType,
    NotificationType, SecurityEvent,
)
from app.releases import RELEASES
from app.ratelimit_rules import minutes_text
from app.security import (
    clean_username, clean_phone, new_totp_secret, verify_totp, totp_uri,
    new_recovery_codes, recovery_codes_left, password_problem, email_typo_hint, mask_email,
    new_token, hash_token,
)
from app.settings import settings_bp
from app.utils import notify_user


def _settings():
    return UserSettings.for_user(current_user.id)


def _password_ok():
    """Checks the 'current password' typed on a Settings form. Wrong tries are counted:
    after 5 in 15 minutes this refuses even the right password for a while."""
    account = str(current_user.id)
    allowed, wait = rl.check("password_check", account)
    if not allowed:
        flash(f"Too many wrong passwords. Please wait {minutes_text(wait)} before trying again.", "danger")
        return False
    if current_user.check_password(request.form.get("current_password", "")):
        rl.clear("password_check", account)
        return True
    rl.hit("password_check", account)
    return False


_security_alert = security_alert        # kept under the old name used below


def _resign_in():
    """After the session version changes, keep THIS device signed in; every other one is out."""
    login_user(current_user._get_current_object())


# ---------------------------------------------------------------------------
# Home
# ---------------------------------------------------------------------------

SECTIONS = [
    ("account", "Account", "Login security, username, phone, email", "bi-person-gear", "settings.account"),
    ("privacy", "Privacy", "Who can see your profile, About you", "bi-shield-lock", "settings.privacy"),
    ("lists", "Lists", "Order of your listings", "bi-list-ol", "settings.lists"),
    ("chats", "Chats", "Download a backup of your chats", "bi-chat-dots", "settings.chats"),
    ("appearance", "Appearance", "Light, Dark, Blue and Velvet", "bi-palette", "settings.appearance"),
    ("notifications", "Notifications", "Sounds, reminders, previews", "bi-bell", None),
    ("storage", "Storage and data", "What you use, free up space", "bi-hdd", "settings.storage"),
    ("parental", "Parental control", "Supervision for under 18s", "bi-people", "settings.parental"),
    ("accessibility", "Accessibility", "Contrast and animation", "bi-universal-access", "settings.accessibility"),
    ("help", "Help and feedback", "Help centre, contact, report a problem", "bi-question-circle", "settings.help"),
    ("invite", "Invite a friend", "Your invite link", "bi-link-45deg", "settings.invite"),
    ("updates", "App updates", "Version and release notes", "bi-arrow-repeat", "settings.updates"),
    ("delete", "Delete account", "Permanently close your account", "bi-trash3", "settings.delete_account"),
]


@settings_bp.route("/settings")
@login_required
def home():
    return render_template("settings/home.html", sections=SECTIONS)


# ---------------------------------------------------------------------------
# Account
# ---------------------------------------------------------------------------

@settings_bp.route("/settings/account")
@login_required
def account():
    return render_template("settings/account.html", s=_settings(),
                           mail_ready=mail_is_configured(),
                           codes_left=recovery_codes_left(current_user.recovery_codes))


@settings_bp.route("/settings/account/username", methods=["POST"])
@login_required
def change_username():
    name = clean_username(request.form.get("username"))
    if not name:
        flash("Use 3 to 30 letters, numbers, dots or underscores. Some names are reserved.", "danger")
    elif User.query.filter(User.username == name, User.id != current_user.id).first():
        flash("That username is taken.", "danger")
    else:
        current_user.username = name
        db.session.commit()
        flash(f"Your username is now @{name}.", "success")
    return redirect(url_for("settings.account"))


@settings_bp.route("/settings/account/phone", methods=["POST"])
@login_required
def change_phone():
    if current_user.is_minor:
        flash("Phone numbers are not available on accounts under 18.", "info")
        return redirect(url_for("settings.account"))
    raw = request.form.get("phone_number", "").strip()
    if raw == "":
        current_user.phone_number = None
        flash("Phone number removed.", "success")
    else:
        phone = clean_phone(raw)
        if not phone:
            flash("Enter a phone number with 9 to 15 digits, for example 081 737 0210 or +27 81 737 0210.", "danger")
            return redirect(url_for("settings.account"))
        current_user.phone_number = phone
        flash("Phone number saved. It is not verified by SMS and is not shown to other students.", "success")
    db.session.commit()
    log_event(current_user.id, "phone_changed")
    security_alert(current_user, "Phone number changed", "The phone number on your account was changed.")
    return redirect(url_for("settings.account"))


@settings_bp.route("/settings/account/email", methods=["POST"])
@login_required
def change_email():
    new_email = request.form.get("new_email", "").lower().strip()
    domains = current_app.config.get("ALLOWED_SCHOOL_EMAIL_DOMAINS") or []
    hint = email_typo_hint(new_email)
    if not _password_ok():
        flash("Your current password was not correct.", "danger")
    elif not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", new_email) or len(new_email) > 160:
        flash("Enter a valid email address.", "danger")
    elif hint:
        flash(f"Check the spelling of the email address. {hint}", "danger")
    elif new_email == current_user.school_email:
        flash("That is already your email address.", "info")
    elif domains and not any(new_email.endswith(d) for d in domains):
        flash("Please use a valid school email address.", "danger")
    elif User.query.filter(User.school_email == new_email).first():
        flash("That email address is already used by another account.", "danger")
    elif not mail_is_configured():
        flash("Email sending is not set up on this server yet, so a confirmation link cannot be sent. "
              "Your email address was not changed.", "danger")
    else:
        token = new_token()
        current_user.pending_email = new_email
        current_user.pending_email_token = hash_token(token)        # only the hash is stored
        current_user.pending_email_expires = datetime.utcnow() + timedelta(hours=1)
        db.session.commit()
        link = url_for("settings.confirm_email", token=token, _external=True)
        sent = send_email(new_email, "Confirm your new Campus Swap email",
                          f"Hi {current_user.full_name.split(' ')[0]},\n\nConfirm this address for your "
                          f"Campus Swap account within 1 hour:\n\n{link}\n\n"
                          "If you did not ask for this, ignore this email and nothing will change.\n\nCampus Swap")
        flash(f"We sent a confirmation link to {mask_email(new_email)}." if sent else
              "The confirmation email could not be sent. Please try again later.", "info" if sent else "danger")
    return redirect(url_for("settings.account"))


@settings_bp.route("/settings/account/email/confirm/<token>")
@login_required
def confirm_email(token):
    u = current_user
    if (not u.pending_email or not u.pending_email_token
            or not secrets.compare_digest(u.pending_email_token, hash_token(token))
            or not u.pending_email_expires or u.pending_email_expires < datetime.utcnow()):
        flash("That confirmation link is invalid or has expired.", "danger")
    elif User.query.filter(User.school_email == u.pending_email).first():
        flash("That email address is already used by another account.", "danger")
    else:
        old = u.school_email
        u.school_email = u.pending_email
        u.email_confirmed = True
        u.pending_email = u.pending_email_token = u.pending_email_expires = None
        db.session.commit()
        if mail_is_configured():
            send_email(old, "Your Campus Swap email was changed",
                       f"The email address on your Campus Swap account was changed to {u.school_email}.\n"
                       f"If this was not you, contact {current_app.config['SUPPORT_EMAIL']} straight away.\n\nCampus Swap")
        log_event(u.id, "email_changed")
        notify_user(u.id, NotificationType.SYSTEM, "Email address changed",
                    "Your login email was updated.", url_for("settings.account"))
        flash("Your email address has been changed. Use it the next time you log in.", "success")
    return redirect(url_for("settings.account"))


@settings_bp.route("/settings/account/password", methods=["POST"])
@login_required
def change_password():
    new = request.form.get("new_password", "")
    if not _password_ok():
        flash("Your current password was not correct.", "danger")
        return redirect(url_for("settings.account"))
    problem = password_problem(new, current_user.school_email, current_user.full_name)
    if problem:
        flash(problem, "danger")
    elif new != request.form.get("confirm_password", ""):
        flash("The new passwords do not match.", "danger")
    elif current_user.check_password(new):
        flash("That is already your password. Choose a different one.", "danger")
    else:
        current_user.set_password(new)
        current_user.password_reset_token = None
        current_user.password_reset_expires = None
        current_user.session_version = (current_user.session_version or 0) + 1   # signs out other devices
        db.session.commit()
        _resign_in()
        log_event(current_user.id, "password_changed")
        security_alert(current_user, "Password changed", "The password on your account was changed.")
        flash("Password changed. Any other device was signed out.", "success")
    return redirect(url_for("settings.account"))


@settings_bp.route("/settings/account/logout-everywhere", methods=["POST"])
@login_required
def logout_everywhere():
    current_user.session_version = (current_user.session_version or 0) + 1
    db.session.commit()
    _resign_in()
    log_event(current_user.id, "logout_everywhere")
    flash("Every other device has been signed out. This one stays signed in.", "success")
    return redirect(url_for("settings.account"))


@settings_bp.route("/settings/account/activity")
@login_required
def activity():
    events = (SecurityEvent.query.filter_by(user_id=current_user.id)
              .order_by(SecurityEvent.created_at.desc()).limit(30).all())
    return render_template("settings/activity.html", events=events, labels=EVENT_LABELS,
                           browser_summary=browser_summary)


@settings_bp.route("/settings/account/security-alerts", methods=["POST"])
@login_required
def security_alerts():
    s = _settings()
    s.security_alerts = bool(request.form.get("security_alerts"))
    db.session.commit()
    flash("Security notifications are on." if s.security_alerts else
          "Security emails are off. You will still see in-app notices.", "success")
    return redirect(url_for("settings.account"))


@settings_bp.route("/settings/account/two-step", methods=["GET", "POST"])
@login_required
def two_step():
    u = current_user
    if request.method == "POST":
        action = request.form.get("action")
        if action == "enable":
            secret = session.get("setup_2fa_secret")
            allowed, wait = rl.check("twofa", str(u.id))
            if not allowed:
                flash(f"Too many wrong codes. Please wait {minutes_text(wait)}.", "danger")
            elif secret and verify_totp(secret, request.form.get("code")):
                plain, stored = new_recovery_codes()
                u.two_factor_secret, u.two_factor_enabled, u.recovery_codes = secret, True, stored
                u.session_version = (u.session_version or 0) + 1
                db.session.commit()
                session.pop("setup_2fa_secret", None)
                _resign_in()
                log_event(u.id, "twofa_on")
                security_alert(u, "Two-step verification turned on",
                               "Two-step verification was turned on for your account.")
                return render_template("settings/two_step.html", enabled=True, new_codes=plain,
                                       codes_left=len(plain))
            else:
                rl.hit("twofa", str(u.id))
                flash("That code was not correct. Check the code in your authenticator app and try again.", "danger")
        elif action in ("disable", "regenerate"):
            if not _password_ok():
                flash("Your current password was not correct.", "danger")
            elif action == "disable":
                if u.is_admin and current_app.config.get("REQUIRE_ADMIN_2FA"):
                    flash("Administrators must keep two-step verification on.", "danger")
                else:
                    u.two_factor_enabled, u.two_factor_secret, u.recovery_codes = False, None, None
                    u.session_version = (u.session_version or 0) + 1
                    db.session.commit()
                    _resign_in()
                    log_event(u.id, "twofa_off")
                    security_alert(u, "Two-step verification turned off",
                                   "Two-step verification was turned off for your account.")
                    flash("Two-step verification is off.", "success")
            else:
                plain, stored = new_recovery_codes()
                u.recovery_codes = stored
                db.session.commit()
                return render_template("settings/two_step.html", enabled=True, new_codes=plain,
                                       codes_left=len(plain))
        return redirect(url_for("settings.two_step"))

    if u.two_factor_enabled:
        return render_template("settings/two_step.html", enabled=True, new_codes=None,
                               codes_left=recovery_codes_left(u.recovery_codes))
    secret = session.get("setup_2fa_secret") or new_totp_secret()
    session["setup_2fa_secret"] = secret
    return render_template("settings/two_step.html", enabled=False, new_codes=None, secret=secret,
                           uri=totp_uri(secret, u.school_email))


# ---------------------------------------------------------------------------
# Privacy, lists, appearance, accessibility
# ---------------------------------------------------------------------------

@settings_bp.route("/settings/privacy", methods=["GET", "POST"])
@login_required
def privacy():
    s = _settings()
    minor = current_user.is_minor
    if minor and s.profile_visibility != "private":
        s.profile_visibility = "private"          # under 18: the profile is always private
        db.session.commit()
    if request.method == "POST":
        vis = request.form.get("profile_visibility")
        if not minor and vis in ("public", "private"):
            s.profile_visibility = vis
        about = request.form.get("about", "").strip()
        current_user.profile.bio = about[:500] or None
        db.session.commit()
        flash("Privacy settings saved.", "success")
        return redirect(url_for("settings.privacy"))
    return render_template("settings/privacy.html", s=s, is_minor=minor)


@settings_bp.route("/settings/parental")
@login_required
def parental():
    guardian = confirmed_guardian(current_user.id) if current_user.is_minor else None
    pending = pending_guardian(current_user.id) if current_user.is_minor else None
    return render_template("settings/parental.html", guardian=guardian, pending=pending,
                           masked=mask_email((guardian or pending).guardian_email) if (guardian or pending) else None)


@settings_bp.route("/settings/lists", methods=["GET", "POST"])
@login_required
def lists():
    s = _settings()
    if request.method == "POST":
        try:
            ranks = {g: int(request.form.get(f"rank_{g}", "")) for g in LIST_GROUPS}
        except ValueError:
            ranks = {}
        if sorted(ranks.values()) != [1, 2, 3]:
            flash("Give each list a different position: top, middle or bottom.", "danger")
        else:
            s.list_order = ",".join(sorted(LIST_GROUPS, key=lambda g: ranks[g]))
            db.session.commit()
            flash("List order saved.", "success")
        return redirect(url_for("settings.lists"))
    order = s.ordered_groups()
    return render_template("settings/lists.html", order=order,
                           labels={"sell": "For sale", "swap": "For swap", "donate": "Donations"})


@settings_bp.route("/settings/appearance", methods=["GET", "POST"])
@login_required
def appearance():
    s = _settings()
    if request.method == "POST":
        theme = request.form.get("theme")
        if theme in THEMES:
            s.theme = theme
            db.session.commit()
            flash("Appearance updated.", "success")
        return redirect(url_for("settings.appearance"))
    return render_template("settings/appearance.html", s=s)


@settings_bp.route("/settings/accessibility", methods=["GET", "POST"])
@login_required
def accessibility():
    s = _settings()
    if request.method == "POST":
        s.increase_contrast = bool(request.form.get("increase_contrast"))
        s.animations_enabled = bool(request.form.get("animations_enabled"))
        db.session.commit()
        flash("Accessibility settings saved.", "success")
        return redirect(url_for("settings.accessibility"))
    return render_template("settings/accessibility.html", s=s)


# ---------------------------------------------------------------------------
# Chats and storage
# ---------------------------------------------------------------------------

def _my_conversations():
    return (Conversation.query.filter(db.or_(Conversation.participant_one_id == current_user.id,
                                              Conversation.participant_two_id == current_user.id))
            .order_by(Conversation.created_at.asc()).all())


@settings_bp.route("/settings/chats")
@login_required
def chats():
    convos = _my_conversations()
    ids = [c.id for c in convos]
    total = Message.query.filter(Message.conversation_id.in_(ids)).count() if ids else 0
    return render_template("settings/chats.html", conversations=len(convos), messages=total)


@settings_bp.route("/settings/chats/backup.<fmt>")
@login_required
def chat_backup(fmt):
    if fmt not in ("json", "txt"):
        abort(404)
    names = {}

    def name_of(uid):
        if uid not in names:
            u = db.session.get(User, uid)
            names[uid] = "You" if uid == current_user.id else (u.full_name if u else "Unknown")
        return names[uid]

    export = []
    for c in _my_conversations():
        other_id = c.participant_two_id if c.participant_one_id == current_user.id else c.participant_one_id
        msgs = Message.query.filter_by(conversation_id=c.id).order_by(Message.sent_at.asc()).all()
        export.append({
            "with": name_of(other_id),
            "about_listing": c.listing_id,
            "started": c.created_at.isoformat() if c.created_at else None,
            "messages": [{
                "sent_at": m.sent_at.isoformat() if m.sent_at else None,
                "from": name_of(m.sender_id),
                "text": m.body,
                "offer_price": str(m.offer_price) if m.offer_price is not None else None,
                "proposed_pickup": m.proposed_pickup,
                "image": m.image_filename,
            } for m in msgs],
        })
    stamp = datetime.utcnow().strftime("%Y%m%d")
    if fmt == "json":
        body, mime = json.dumps({"exported_at": datetime.utcnow().isoformat() + "Z", "chats": export}, indent=2), "application/json"
    else:
        lines = [f"Campus Swap chat backup, {datetime.utcnow():%d %B %Y}", ""]
        for chat in export:
            lines += [f"Chat with {chat['with']}", "-" * 40]
            for m in chat["messages"]:
                extra = "".join([f" [offer R{m['offer_price']}]" if m["offer_price"] else "",
                                 f" [pickup: {m['proposed_pickup']}]" if m["proposed_pickup"] else "",
                                 " [image]" if m["image"] else ""])
                lines.append(f"{(m['sent_at'] or '')[:16].replace('T', ' ')}  {m['from']}: {m['text'] or ''}{extra}")
            lines.append("")
        body, mime = "\n".join(lines), "text/plain"
    return Response(body, mimetype=mime + "; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename=campus-swap-chats-{stamp}.{fmt}"})


def _file_size(relative):
    if not relative:
        return 0
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], relative.replace("/", os.sep))
    try:
        return os.path.getsize(path) if os.path.isfile(path) else 0
    except OSError:
        return 0


@settings_bp.route("/settings/storage")
@login_required
def storage():
    uid = current_user.id
    listing_bytes = sum(_file_size(i.filename) for i in ListingImage.query.join(Listing)
                        .filter(Listing.seller_id == uid).all())
    pic = current_user.profile.profile_picture
    profile_bytes = 0 if pic == "default_avatar.png" else _file_size(f"profiles/{pic}" if "/" not in pic else pic)
    chat_bytes = sum(_file_size(m.image_filename) for m in
                     Message.query.filter(Message.sender_id == uid, Message.image_filename.isnot(None)).all())
    return render_template("settings/storage.html", listing_bytes=listing_bytes, profile_bytes=profile_bytes,
                           chat_bytes=chat_bytes, total=listing_bytes + profile_bytes + chat_bytes)


# ---------------------------------------------------------------------------
# Help, invite, updates
# ---------------------------------------------------------------------------

@settings_bp.route("/settings/help", endpoint="help")
@login_required
def help_centre():
    return render_template("settings/help.html")


@settings_bp.route("/settings/help/send", methods=["GET", "POST"])
@login_required
def send_feedback():
    kind = request.values.get("kind", "feedback")
    if kind not in ("feedback", "issue", "contact"):
        kind = "feedback"
    if request.method == "POST":
        subject = request.form.get("subject", "").strip()[:160]
        message = request.form.get("message", "").strip()[:4000]
        if not subject or len(message) < 10:
            flash("Add a subject and a message of at least 10 characters.", "danger")
        else:
            db.session.add(Feedback(user_id=current_user.id, kind=kind, subject=subject, message=message,
                                    app_version=current_app.config["APP_VERSION"]))
            db.session.commit()
            if mail_is_configured():
                send_email(current_app.config["SUPPORT_EMAIL"], f"[Campus Swap {kind}] {subject}",
                           f"From: {current_user.full_name} <{current_user.school_email}>\n"
                           f"Version: {current_app.config['APP_VERSION']}\n\n{message}")
            flash("Thank you. Your message was sent to the Campus Swap team.", "success")
            return redirect(url_for("settings.help"))
    return render_template("settings/send_feedback.html", kind=kind)


@settings_bp.route("/settings/invite")
@login_required
def invite():
    if not current_user.invite_code:
        for _ in range(5):
            code = secrets.token_urlsafe(6).replace("-", "a").replace("_", "b")[:8].lower()
            if not User.query.filter_by(invite_code=code).first():
                current_user.invite_code = code
                db.session.commit()
                break
    link = url_for("auth.register", ref=current_user.invite_code, _external=True)
    joined = User.query.filter_by(referred_by_id=current_user.id).count()
    return render_template("settings/invite.html", link=link, joined=joined)


@settings_bp.route("/settings/updates")
@login_required
def updates():
    return render_template("settings/updates.html", releases=RELEASES,
                           version=current_app.config["APP_VERSION"],
                           grace=current_app.config["UPDATE_GRACE_DAYS"])


# ---------------------------------------------------------------------------
# Delete account
# ---------------------------------------------------------------------------

@settings_bp.route("/settings/delete", methods=["GET", "POST"])
@login_required
def delete_account():
    u = current_user
    open_tx, open_disputes = open_work(u)
    blocked = open_tx > 0 or open_disputes > 0 or u.is_admin

    if request.method == "POST":
        if blocked:
            flash("This account cannot be deleted yet. See the reason on this page.", "danger")
        elif not _password_ok() or request.form.get("confirm_text", "").strip() != "DELETE":
            flash("Enter your password and type DELETE to confirm.", "danger")
        else:
            user = u._get_current_object()
            close_account(user)
            logout_user()
            flash("Your account has been deleted.", "info")
            return redirect(url_for("main.landing"))
        return redirect(url_for("settings.delete_account"))

    return render_template("settings/delete.html", open_tx=open_tx, open_disputes=open_disputes,
                           is_admin=u.is_admin, blocked=blocked)
