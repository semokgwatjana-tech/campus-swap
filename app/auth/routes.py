import secrets
from datetime import datetime, timedelta

from flask import render_template, redirect, url_for, flash, request, current_app
from flask_login import login_user, logout_user, login_required, current_user

from app.auth import auth_bp
from app.extensions import db
from app.forms import RegistrationForm, LoginForm, ForgotPasswordForm, ResetPasswordForm
from app.models import User, Profile
from app.utils import save_uploaded_image


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    form = RegistrationForm()
    if form.validate_on_submit():
        allowed_domains = current_app.config.get("ALLOWED_SCHOOL_EMAIL_DOMAINS") or []
        email = form.school_email.data.lower().strip()
        if allowed_domains and not any(email.endswith(d) for d in allowed_domains):
            flash("Please register with a valid school email address.", "danger")
            return render_template("auth/register.html", form=form)

        user = User(
            full_name=form.full_name.data.strip(),
            student_number=form.student_number.data.strip(),
            school_email=email,
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.flush()  # get user.id before commit

        picture_filename = save_uploaded_image(form.profile_picture.data, subfolder="profiles")
        profile = Profile(
            user_id=user.id,
            course=form.course.data,
            year_of_study=form.year_of_study.data,
            campus=form.campus.data,
            profile_picture=picture_filename or "default_avatar.png",
        )
        db.session.add(profile)
        db.session.commit()

        flash(
            "Welcome to Campus Swap! Your account was created. "
            "A verification badge will appear once your student status is confirmed by an admin.",
            "success",
        )
        login_user(user)
        return redirect(url_for("main.dashboard"))

    return render_template("auth/register.html", form=form)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    form = LoginForm()
    if form.validate_on_submit():
        email = form.school_email.data.lower().strip()
        user = User.query.filter_by(school_email=email).first()

        if user is None or not user.check_password(form.password.data):
            flash("Incorrect email or password.", "danger")
        elif not user.is_active_account:
            flash("This account has been suspended. Please contact Campus Swap support.", "danger")
        else:
            login_user(user, remember=form.remember_me.data)
            next_page = request.args.get("next")
            flash(f"Welcome back, {user.full_name.split(' ')[0]}!", "success")
            return redirect(next_page or url_for("main.dashboard"))

    return render_template("auth/login.html", form=form)


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out. See you soon!", "info")
    return redirect(url_for("main.landing"))


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    form = ForgotPasswordForm()
    if form.validate_on_submit():
        email = form.school_email.data.lower().strip()
        user = User.query.filter_by(school_email=email).first()
        if user:
            token = secrets.token_urlsafe(32)
            user.password_reset_token = token
            user.password_reset_expires = datetime.utcnow() + timedelta(hours=1)
            db.session.commit()
            reset_link = url_for("auth.reset_password", token=token, _external=True)
            # In production this would be emailed via an email-verification
            # service. For the prototype we surface the link directly so the
            # reset flow can be demonstrated end-to-end without an SMTP setup.
            flash(
                "If an account exists for that email, a password reset link has been generated. "
                f"(Demo mode - link: {reset_link})",
                "info",
            )
        else:
            flash("If an account exists for that email, a password reset link has been generated.", "info")
        return redirect(url_for("auth.login"))

    return render_template("auth/forgot_password.html", form=form)


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    user = User.query.filter_by(password_reset_token=token).first()
    if not user or not user.password_reset_expires or user.password_reset_expires < datetime.utcnow():
        flash("That password reset link is invalid or has expired.", "danger")
        return redirect(url_for("auth.forgot_password"))

    form = ResetPasswordForm(token=token)
    if form.validate_on_submit():
        user.set_password(form.password.data)
        user.password_reset_token = None
        user.password_reset_expires = None
        db.session.commit()
        flash("Your password has been reset. Please log in.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/reset_password.html", form=form, token=token)
