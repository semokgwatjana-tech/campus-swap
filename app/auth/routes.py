import time
from datetime import date, datetime, timedelta

from flask import render_template, redirect, url_for, flash, request, current_app, session
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash

from app import ratelimit as rl
from app.accounts import (
    log_event, security_alert, start_email_verification, add_guardian, first_name,
)
from app.auth import auth_bp
from app.extensions import db
from app.forms import (
    RegistrationForm, LoginForm, ForgotPasswordForm, ResetPasswordForm, ResendVerificationForm,
)
from app.mailer import send_email, mail_is_configured
from app.models import User, Profile
from app.ratelimit_rules import minutes_text
from app.security import (
    verify_totp, use_recovery_code, password_problem, new_token, hash_token, mask_email,
)
from app.utils import save_uploaded_image

# Checked against when an email is unknown, so a wrong email takes as long as a wrong
# password and the page does not reveal which emails have accounts.
_DUMMY_HASH = generate_password_hash("not-a-real-password-just-for-timing")
_TWOFA_KEYS = ("2fa_user_id", "2fa_remember", "2fa_next", "2fa_started")


def _portal(mode, login_form, signup_form):
    """One card holds both Sign in and Create account. `mode` is the side shown first."""
    return render_template("auth/portal.html", mode=mode, login_form=login_form, signup_form=signup_form)


def _safe_next(target):
    """Only follow redirects to a path on this site, never to another domain."""
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return None


def _too_many(wait):
    flash(f"Too many tries. Please wait {minutes_text(wait)} and try again, or reset your password.", "danger")


def _can_sign_up_by_email():
    """Sign-ups need working email so every account's address is confirmed. Only on
    a developer's own computer or in tests can that be skipped."""
    return mail_is_configured() or current_app.debug or current_app.testing


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------

@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    ref = (request.args.get("ref") or "").strip().lower()[:16]
    if ref:
        session["invite_ref"] = ref
    form = RegistrationForm(prefix="signup")

    if request.method == "POST":
        allowed, wait = rl.check("register")
        if not allowed:
            _too_many(wait)
            return _portal("signup", LoginForm(prefix="login"), form)

    if form.validate_on_submit():
        if not _can_sign_up_by_email():
            current_app.logger.error("Sign-up refused: email sending is not configured.")
            flash("Sign-ups are temporarily unavailable. Please try again later.", "danger")
            return _portal("signup", LoginForm(prefix="login"), form)

        email = form.school_email.data.lower().strip()
        allowed_domains = current_app.config.get("ALLOWED_SCHOOL_EMAIL_DOMAINS") or []
        if allowed_domains and not any(email.endswith(d) for d in allowed_domains):
            flash("Please register with a valid school email address.", "danger")
            return _portal("signup", LoginForm(prefix="login"), form)

        rl.hit("register")
        email_works = mail_is_configured()
        user = User(
            full_name=form.full_name.data.strip(),
            student_number=form.student_number.data.strip(),
            school_email=email,
            date_of_birth=form.date_of_birth.data,
            email_confirmed=not email_works,        # only ever true here on a developer's computer
        )
        user.set_password(form.password.data)
        inviter = User.query.filter_by(invite_code=session.pop("invite_ref", None)).first() \
            if session.get("invite_ref") else None
        if inviter:
            user.referred_by_id = inviter.id
        db.session.add(user)
        db.session.flush()

        # Under 18: profile photos are not allowed, so the default picture is used.
        picture = None if user.is_minor else save_uploaded_image(form.profile_picture.data, subfolder="profiles")
        db.session.add(Profile(
            user_id=user.id, course=form.course.data, year_of_study=form.year_of_study.data,
            campus=form.campus.data, profile_picture=picture or "default_avatar.png"))
        db.session.commit()
        log_event(user.id, "registered")

        dev_links = []
        if user.is_minor:
            guardian, sent = add_guardian(user, form.guardian_name.data, form.guardian_email.data)
            if not sent:
                current_app.logger.warning("Guardian email could not be sent for learner %s", user.id)
        if email_works:
            start_email_verification(user)
        elif current_app.debug:
            dev_links.append("Development mode: email is not set up, so your address was marked confirmed.")

        session["pending_email_notice"] = email
        for note in dev_links:
            flash(note, "info")
        return redirect(url_for("auth.check_email"))

    return _portal("signup", LoginForm(prefix="login"), form)


# ---------------------------------------------------------------------------
# Email confirmation
# ---------------------------------------------------------------------------

@auth_bp.route("/check-email", methods=["GET", "POST"])
def check_email():
    """'We sent you a link' page, with a way to ask for another one."""
    form = ResendVerificationForm()
    pending = session.get("pending_email_notice")
    if form.validate_on_submit():
        email = form.school_email.data.lower().strip()
        allowed, wait = rl.check("verify_email", email)
        if allowed:
            rl.hit("verify_email", email)
            user = User.query.filter_by(school_email=email).first()
            recently = user and user.email_token_sent_at and \
                (datetime.utcnow() - user.email_token_sent_at).total_seconds() < 60
            if user and not user.email_confirmed and not user.deleted_at and not recently:
                start_email_verification(user)
        # The same answer every time, so this page cannot be used to find out who has an account.
        session["pending_email_notice"] = email
        flash("If that address has an account waiting to be confirmed, we sent a new link.", "info")
        return redirect(url_for("auth.check_email"))
    return render_template("auth/check_email.html", form=form,
                           masked=mask_email(pending) if pending else None)


@auth_bp.route("/verify/<token>")
def verify_email(token):
    user = User.query.filter_by(email_token_hash=hash_token(token)).first()
    if (not user or user.deleted_at or not user.email_token_expires
            or user.email_token_expires < datetime.utcnow()):
        flash("That confirmation link is invalid or has expired. You can ask for a new one.", "danger")
        return redirect(url_for("auth.check_email"))
    user.email_confirmed = True
    user.email_token_hash = user.email_token_expires = None
    db.session.commit()
    log_event(user.id, "email_confirmed")
    flash("Your email address is confirmed. You can sign in now.", "success")
    return redirect(url_for("auth.login"))


# ---------------------------------------------------------------------------
# Sign in
# ---------------------------------------------------------------------------

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    form = LoginForm(prefix="login")
    if form.validate_on_submit():
        email = form.school_email.data.lower().strip()

        allowed, wait = rl.check("login", email)
        if not allowed:
            _too_many(wait)
            return _portal("signin", form, RegistrationForm(prefix="signup"))

        user = User.query.filter_by(school_email=email).first()
        if user is not None:
            password_ok = user.check_password(form.password.data)
        else:
            check_password_hash(_DUMMY_HASH, form.password.data)
            password_ok = False

        if not password_ok:
            just_locked = rl.hit("login", email)
            if user:
                log_event(user.id, "login_failed")
                if just_locked:
                    log_event(user.id, "login_locked")
                    security_alert(user, "Sign-in locked for a while",
                                   "Someone entered the wrong password for your account several times, so "
                                   "sign-in is locked for 15 minutes.")
            flash("Incorrect email or password.", "danger")
        elif not user.is_active_account or user.deleted_at:
            flash("This account has been suspended. Please contact Campus Swap support.", "danger")
        elif not user.email_confirmed:
            session["pending_email_notice"] = user.school_email
            flash("Please confirm your email address first. We sent you a link when you signed up.", "info")
            return redirect(url_for("auth.check_email"))
        elif user.two_factor_enabled:
            # The password was right; the second step must pass before anyone is signed in.
            session["2fa_user_id"] = user.id
            session["2fa_remember"] = bool(form.remember_me.data)
            session["2fa_next"] = _safe_next(request.args.get("next"))
            session["2fa_started"] = time.time()
            return redirect(url_for("auth.two_step_login"))
        else:
            rl.clear("login", email)
            login_user(user, remember=form.remember_me.data)
            log_event(user.id, "login")
            flash(f"Welcome back, {first_name(user)}!", "success")
            return redirect(_safe_next(request.args.get("next")) or url_for("main.dashboard"))

    return _portal("signin", form, RegistrationForm(prefix="signup"))


@auth_bp.route("/two-step", methods=["GET", "POST"])
def two_step_login():
    user = db.session.get(User, session.get("2fa_user_id") or 0)
    if (not user or not user.two_factor_enabled or not user.is_active_account or user.deleted_at
            or time.time() - session.get("2fa_started", 0) > 600):
        for k in _TWOFA_KEYS:
            session.pop(k, None)
        flash("Please sign in again.", "info")
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        account = str(user.id)
        allowed, wait = rl.check("twofa", account)
        if not allowed:
            for k in _TWOFA_KEYS:
                session.pop(k, None)
            _too_many(wait)
            return redirect(url_for("auth.login"))

        code = request.form.get("code", "")
        ok = verify_totp(user.two_factor_secret, code)
        if not ok:
            remaining = use_recovery_code(user.recovery_codes, code)
            if remaining is not None:
                user.recovery_codes = remaining
                db.session.commit()
                flash("You used a recovery code. Get new ones in Settings when you can.", "info")
                ok = True
        if ok:
            remember, nxt = session.get("2fa_remember", False), session.get("2fa_next")
            for k in _TWOFA_KEYS:
                session.pop(k, None)
            rl.clear("twofa", account)
            rl.clear("login", user.school_email)
            login_user(user, remember=remember)
            log_event(user.id, "login", "two-step")
            return redirect(nxt or url_for("main.dashboard"))

        rl.hit("twofa", account)
        log_event(user.id, "twofa_failed")
        flash("That code was not correct.", "danger")
    return render_template("auth/two_step.html")


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You have been logged out. See you soon!", "info")
    return redirect(url_for("main.landing"))


# ---------------------------------------------------------------------------
# Forgot / reset password
# ---------------------------------------------------------------------------

@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    form = ForgotPasswordForm()
    if form.validate_on_submit():
        email = form.school_email.data.lower().strip()
        allowed, _wait = rl.check("reset", email)
        if allowed:
            rl.hit("reset", email)
            user = User.query.filter_by(school_email=email).first()
            if user and user.is_active_account and not user.deleted_at:
                token = new_token()
                user.password_reset_token = hash_token(token)       # only the hash is stored
                user.password_reset_expires = datetime.utcnow() + timedelta(hours=1)
                db.session.commit()
                reset_link = url_for("auth.reset_password", token=token, _external=True)
                body = (
                    f"Hi {first_name(user)},\n\n"
                    "Someone asked to reset the password for your Campus Swap account. "
                    "Use the link below within 1 hour to choose a new password:\n\n"
                    f"{reset_link}\n\n"
                    "If you did not ask for this, you can ignore this email. "
                    "Your password will not change.\n\n"
                    "Campus Swap"
                )
                if not send_email(user.school_email, "Reset your Campus Swap password", body):
                    current_app.logger.warning(
                        "Password reset requested for user %s but no email could be sent.", user.id)
                    # The link is only ever shown on screen on a developer's own computer.
                    # On a live site that would let anyone reset any account by typing its email.
                    if current_app.debug:
                        flash(f"Development mode only. Reset link: {reset_link}", "info")
        # The same message whether or not the address has an account, or the limit was reached.
        flash("If an account exists for that email, a password reset link has been sent.", "info")
        return redirect(url_for("auth.login"))

    return render_template("auth/forgot_password.html", form=form)


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    user = User.query.filter_by(password_reset_token=hash_token(token)).first()
    if (not user or user.deleted_at or not user.password_reset_expires
            or user.password_reset_expires < datetime.utcnow()):
        flash("That password reset link is invalid or has expired.", "danger")
        return redirect(url_for("auth.forgot_password"))

    form = ResetPasswordForm(token=token)
    if form.validate_on_submit():
        problem = password_problem(form.password.data, user.school_email, user.full_name)
        if problem:
            form.password.errors = list(form.password.errors) + [problem]
        else:
            user.set_password(form.password.data)
            user.password_reset_token = user.password_reset_expires = None
            user.session_version = (user.session_version or 0) + 1       # signs out every device
            db.session.commit()
            rl.clear("login", user.school_email)
            rl.clear("twofa", str(user.id))
            log_event(user.id, "password_reset")
            security_alert(user, "Password reset", "The password on your account was reset using an emailed link.")
            flash("Your password has been reset. Please sign in.", "success")
            return redirect(url_for("auth.login"))

    return render_template("auth/reset_password.html", form=form, token=token)
