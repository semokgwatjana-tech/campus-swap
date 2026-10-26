"""
One check that runs before every page for a signed-in person. It keeps people on
the right side of Campus Swap and stops a locked account from reaching anything
except the page that explains what to do.

  * suspended or closed accounts are signed out
  * no date of birth yet: asked for one
  * under 18 and no parent/guardian has confirmed yet: sent to the waiting page
  * under 18 and paused by a parent/guardian: sent to the paused page
  * turned 18: the guardian link ends and the account moves to the adult side
"""

from datetime import datetime

from flask import request, redirect, url_for, flash
from flask_login import current_user, logout_user

from app.extensions import db

ALWAYS_ALLOWED = {
    "static", "main.service_worker", "main.terms", "main.privacy_policy", "main.refund_policy",
    "auth.logout", "settings.help", "settings.send_feedback",
}


def init_gates(app):
    @app.before_request
    def gate():
        if not current_user.is_authenticated:
            return None
        endpoint = request.endpoint or ""
        user = current_user

        if not user.is_active_account or user.deleted_at:
            logout_user()
            flash("This account is not available. Please contact Campus Swap support if you think this is a mistake.", "danger")
            return redirect(url_for("auth.login"))

        if endpoint in ALWAYS_ALLOWED or endpoint.startswith("parents.") or endpoint.startswith("auth."):
            return None
        if user.is_admin:
            return None

        if user.date_of_birth is None:
            return redirect(url_for("parents.age_gate"))

        if user.is_minor:
            from app.accounts import confirmed_guardian
            if not confirmed_guardian(user.id):
                return redirect(url_for("parents.waiting"))
            if user.parent_paused:
                return redirect(url_for("parents.paused"))
            return None

        # An adult. If a guardian link still exists from before they turned 18, end it.
        from app.models import Guardian
        from app.accounts import log_event
        links = Guardian.query.filter(Guardian.learner_id == user.id,
                                      Guardian.status.in_(["confirmed", "pending"])).all()
        if links:
            for link in links:
                link.status, link.ended_at, link.token_hash = "ended", datetime.utcnow(), None
            user.parent_paused = False
            user.allow_paid_trades = False
            db.session.commit()
            log_event(user.id, "aged_out")
        return None
