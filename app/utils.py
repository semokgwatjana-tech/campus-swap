"""
Reusable helper functions shared across blueprints.
"""

import os
import uuid
from datetime import datetime

from flask import current_app
from werkzeug.utils import secure_filename

from app.extensions import db
from app.models import Notification, NotificationType, Transaction


def allowed_file(filename):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext in current_app.config["ALLOWED_IMAGE_EXTENSIONS"]


def save_uploaded_image(file_storage, subfolder="listings"):
    """Save an uploaded image with a random, collision-safe filename.
    Returns the stored filename (not the full path) or None if invalid."""
    if not file_storage or file_storage.filename == "":
        return None
    if not allowed_file(file_storage.filename):
        return None

    ext = file_storage.filename.rsplit(".", 1)[-1].lower()
    safe_name = f"{uuid.uuid4().hex}.{ext}"
    folder = os.path.join(current_app.config["UPLOAD_FOLDER"], subfolder)
    os.makedirs(folder, exist_ok=True)
    file_storage.save(os.path.join(folder, secure_filename(safe_name)))
    return f"{subfolder}/{safe_name}"


def generate_transaction_reference():
    """
    Generates a human-readable, unique transaction reference such as
    CS-2026-000184. The numeric part increments per year based on how many
    transactions already exist for the current year, which keeps ids short
    and predictable for receipts while remaining effectively unique because
    the primary key + reference are both unique-constrained.
    """
    year = datetime.utcnow().year
    count_this_year = Transaction.query.filter(
        Transaction.reference.like(f"CS-{year}-%")
    ).count()
    sequence = count_this_year + 1
    candidate = f"CS-{year}-{sequence:06d}"

    # Extremely defensive: guarantee uniqueness even under race conditions
    # by nudging the sequence forward if a collision is somehow found.
    while Transaction.query.filter_by(reference=candidate).first() is not None:
        sequence += 1
        candidate = f"CS-{year}-{sequence:06d}"
    return candidate


def notify_user(user_id, notification_type, title, body=None, link=None):
    """Create an in-app notification for a user. Centralised so every
    feature (messages, offers, sales, swaps, wishlist, reviews, donations)
    creates notifications the same way."""
    notification = Notification(
        user_id=user_id,
        notification_type=notification_type,
        title=title,
        body=body,
        link=link,
    )
    db.session.add(notification)
    db.session.commit()
    return notification


def unread_notification_count(user_id):
    return Notification.query.filter_by(user_id=user_id, is_read=False).count()


def calculate_service_fee(item_price):
    """Server-side fee calculation - NEVER trust a fee/total sent from the
    browser. Reads the configurable percentage/fixed fee from platform
    settings (falling back to config defaults) so admins can tune pricing
    without a code change."""
    from app.models import PlatformSetting

    percent = float(PlatformSetting.get("service_fee_percent",
                                         current_app.config["DEFAULT_SERVICE_FEE_PERCENT"]))
    fixed = float(PlatformSetting.get("service_fee_fixed",
                                       current_app.config["DEFAULT_SERVICE_FEE_FIXED"]))
    fee = round(float(item_price) * (percent / 100.0) + fixed, 2)
    return fee
