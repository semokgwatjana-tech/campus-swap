"""
Campus Swap - Database Models
------------------------------
A scalable relational schema for the student-to-student trading platform.

Tables map 1:1 onto the entities called for in the product spec: Users,
Profiles, Listings, Categories, Images, Conversations, Messages, Reviews,
Notifications, Wishlist, SwapRequests, DonationRequests, Reports,
Transactions, Badges/Achievements, and Admin users (role-based, not a
separate table, to keep auth simple and consistent).
"""

from datetime import datetime, timedelta
import enum

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from app.extensions import db


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ListingType(enum.Enum):
    SELL = "sell"
    SWAP = "swap"
    DONATE = "donate"


class ListingCondition(enum.Enum):
    NEW = "New"
    EXCELLENT = "Excellent"
    GOOD = "Good"
    FAIR = "Fair"


class ListingStatus(enum.Enum):
    PENDING_APPROVAL = "pending_approval"   # awaiting admin moderation
    ACTIVE = "active"
    RESERVED = "reserved"
    SOLD = "sold"
    DONATED = "donated"
    SWAPPED = "swapped"
    REMOVED = "removed"                     # removed by admin


class TransactionStatus(enum.Enum):
    PENDING = "PENDING"
    PAYMENT_PROCESSING = "PAYMENT_PROCESSING"
    PAID = "PAID"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    RESERVED = "RESERVED"
    READY_FOR_PICKUP = "READY_FOR_PICKUP"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    REFUND_REQUESTED = "REFUND_REQUESTED"
    REFUNDED = "REFUNDED"


class TransactionType(enum.Enum):
    PURCHASE = "purchase"
    DONATION = "donation"
    SWAP = "swap"
    SWAP_WITH_TOP_UP = "swap_with_top_up"


class PaymentMethod(enum.Enum):
    CARD = "card"
    EFT = "eft"
    INSTANT_EFT = "instant_eft"          # PayShap-style
    WALLET = "wallet"                    # future digital wallet
    NONE = "none"                        # donations / pure swaps


class SwapRequestStatus(enum.Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    COUNTERED = "countered"
    CANCELLED = "cancelled"


class DonationRequestStatus(enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DECLINED = "declined"
    COLLECTED = "collected"


class ReportStatus(enum.Enum):
    OPEN = "open"
    REVIEWING = "reviewing"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class UserRole(enum.Enum):
    STUDENT = "student"
    ADMIN = "admin"


# ---------------------------------------------------------------------------
# Users & Profiles
# ---------------------------------------------------------------------------

class User(UserMixin, db.Model):
    """Authentication + core identity. Extended profile fields live in
    Profile (kept separate so auth stays lean and profile data can grow
    without touching the login-critical table)."""

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    student_number = db.Column(db.String(40), unique=True, nullable=False, index=True)
    school_email = db.Column(db.String(160), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)

    role = db.Column(db.Enum(UserRole), default=UserRole.STUDENT, nullable=False)
    is_verified = db.Column(db.Boolean, default=False)          # student verification
    is_active_account = db.Column(db.Boolean, default=True)     # admin can suspend
    email_confirmed = db.Column(db.Boolean, default=False)

    password_reset_token = db.Column(db.String(100), nullable=True)
    password_reset_expires = db.Column(db.DateTime, nullable=True)

    trust_score = db.Column(db.Float, default=0.0)              # derived from reviews
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    profile = db.relationship("Profile", back_populates="user", uselist=False,
                               cascade="all, delete-orphan")
    listings = db.relationship("Listing", back_populates="seller",
                                foreign_keys="Listing.seller_id")

    # Flask-Login required overrides
    def get_id(self):
        return str(self.id)

    @property
    def is_active(self):
        return self.is_active_account

    def set_password(self, raw_password):
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password):
        return check_password_hash(self.password_hash, raw_password)

    @property
    def is_admin(self):
        return self.role == UserRole.ADMIN

    @property
    def average_rating(self):
        reviews = Review.query.filter_by(reviewee_id=self.id).all()
        if not reviews:
            return None
        return round(sum(r.rating for r in reviews) / len(reviews), 1)

    def __repr__(self):
        return f"<User {self.student_number} {self.school_email}>"


class Profile(db.Model):
    """Extended, editable profile information shown on a student's public page."""

    __tablename__ = "profiles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)

    profile_picture = db.Column(db.String(255), default="default_avatar.png")
    course = db.Column(db.String(120))
    year_of_study = db.Column(db.String(20))
    campus = db.Column(db.String(120))
    bio = db.Column(db.Text)

    user = db.relationship("User", back_populates="profile")

    def __repr__(self):
        return f"<Profile of user {self.user_id}>"


# ---------------------------------------------------------------------------
# Marketplace: Categories, Listings, Images
# ---------------------------------------------------------------------------

class Category(db.Model):
    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    slug = db.Column(db.String(80), unique=True, nullable=False)
    icon = db.Column(db.String(50), default="bi-box-seam")  # bootstrap-icons class

    listings = db.relationship("Listing", back_populates="category")


class Listing(db.Model):
    __tablename__ = "listings"

    id = db.Column(db.Integer, primary_key=True)
    seller_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=False)

    title = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text, nullable=False)
    listing_type = db.Column(db.Enum(ListingType), nullable=False, default=ListingType.SELL)
    condition = db.Column(db.Enum(ListingCondition), nullable=False, default=ListingCondition.GOOD)

    price = db.Column(db.Numeric(10, 2), default=0)             # 0 for donations
    swap_for = db.Column(db.String(255), nullable=True)          # what the seller wants in exchange
    campus = db.Column(db.String(120), nullable=False)

    status = db.Column(db.Enum(ListingStatus), default=ListingStatus.ACTIVE)
    is_featured = db.Column(db.Boolean, default=False)          # premium/sponsored listing
    views_count = db.Column(db.Integer, default=0)

    reserved_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    reserved_until = db.Column(db.DateTime, nullable=True)

    posted_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    seller = db.relationship("User", back_populates="listings", foreign_keys=[seller_id])
    category = db.relationship("Category", back_populates="listings")
    images = db.relationship("ListingImage", back_populates="listing",
                              cascade="all, delete-orphan", order_by="ListingImage.position")
    reserved_by = db.relationship("User", foreign_keys=[reserved_by_id])

    def is_reservation_active(self):
        return (self.reserved_until is not None and
                self.reserved_until > datetime.utcnow() and
                self.status == ListingStatus.RESERVED)

    def release_reservation_if_expired(self):
        if self.status == ListingStatus.RESERVED and self.reserved_until and \
                self.reserved_until <= datetime.utcnow():
            self.status = ListingStatus.ACTIVE
            self.reserved_by_id = None
            self.reserved_until = None
            db.session.commit()

    @property
    def primary_image(self):
        return self.images[0].filename if self.images else "placeholder.png"

    def __repr__(self):
        return f"<Listing {self.title} ({self.listing_type.value})>"


class ListingImage(db.Model):
    __tablename__ = "listing_images"

    id = db.Column(db.Integer, primary_key=True)
    listing_id = db.Column(db.Integer, db.ForeignKey("listings.id"), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    position = db.Column(db.Integer, default=0)

    listing = db.relationship("Listing", back_populates="images")


class Wishlist(db.Model):
    __tablename__ = "wishlist"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    listing_id = db.Column(db.Integer, db.ForeignKey("listings.id"), nullable=False)
    added_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User")
    listing = db.relationship("Listing")

    __table_args__ = (db.UniqueConstraint("user_id", "listing_id", name="uq_wishlist_user_listing"),)


# ---------------------------------------------------------------------------
# Messaging
# ---------------------------------------------------------------------------

class Conversation(db.Model):
    __tablename__ = "conversations"

    id = db.Column(db.Integer, primary_key=True)
    listing_id = db.Column(db.Integer, db.ForeignKey("listings.id"), nullable=True)
    participant_one_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    participant_two_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    listing = db.relationship("Listing")
    messages = db.relationship("Message", back_populates="conversation",
                                cascade="all, delete-orphan", order_by="Message.sent_at")

    def other_participant(self, current_user_id):
        return (self.participant_two_id if self.participant_one_id == current_user_id
                else self.participant_one_id)

    @property
    def last_message(self):
        return self.messages[-1] if self.messages else None


class Message(db.Model):
    __tablename__ = "messages"

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("conversations.id"), nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    body = db.Column(db.Text, nullable=True)
    image_filename = db.Column(db.String(255), nullable=True)
    offer_price = db.Column(db.Numeric(10, 2), nullable=True)
    proposed_pickup = db.Column(db.String(120), nullable=True)

    is_read = db.Column(db.Boolean, default=False)
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)

    conversation = db.relationship("Conversation", back_populates="messages")
    sender = db.relationship("User")


# ---------------------------------------------------------------------------
# Swap & Donation requests
# ---------------------------------------------------------------------------

class SwapRequest(db.Model):
    __tablename__ = "swap_requests"

    id = db.Column(db.Integer, primary_key=True)
    requester_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    target_listing_id = db.Column(db.Integer, db.ForeignKey("listings.id"), nullable=False)
    offered_listing_id = db.Column(db.Integer, db.ForeignKey("listings.id"), nullable=False)

    top_up_amount = db.Column(db.Numeric(10, 2), default=0)     # price-difference top-up
    message = db.Column(db.Text, nullable=True)
    status = db.Column(db.Enum(SwapRequestStatus), default=SwapRequestStatus.PENDING)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    responded_at = db.Column(db.DateTime, nullable=True)

    requester = db.relationship("User", foreign_keys=[requester_id])
    target_listing = db.relationship("Listing", foreign_keys=[target_listing_id])
    offered_listing = db.relationship("Listing", foreign_keys=[offered_listing_id])


class DonationRequest(db.Model):
    __tablename__ = "donation_requests"

    id = db.Column(db.Integer, primary_key=True)
    listing_id = db.Column(db.Integer, db.ForeignKey("listings.id"), nullable=False)
    requester_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    message = db.Column(db.Text, nullable=True)
    status = db.Column(db.Enum(DonationRequestStatus), default=DonationRequestStatus.PENDING)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    listing = db.relationship("Listing")
    requester = db.relationship("User")


# ---------------------------------------------------------------------------
# Transactions / Payments
# ---------------------------------------------------------------------------

class Transaction(db.Model):
    """
    Represents money (or R0 donation / pure swap) changing hands for a
    listing. The backend - never the client - is the source of truth for
    price and status. See app/transactions/payment_gateway.py for the
    sandbox payment simulation this model is driven by.
    """

    __tablename__ = "transactions"

    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(30), unique=True, nullable=False, index=True)  # e.g. CS-2026-000184

    listing_id = db.Column(db.Integer, db.ForeignKey("listings.id"), nullable=False)
    buyer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    seller_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    transaction_type = db.Column(db.Enum(TransactionType), nullable=False, default=TransactionType.PURCHASE)
    item_price = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    service_fee = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    total_amount = db.Column(db.Numeric(10, 2), nullable=False, default=0)

    payment_method = db.Column(db.Enum(PaymentMethod), default=PaymentMethod.NONE)
    status = db.Column(db.Enum(TransactionStatus), default=TransactionStatus.PENDING, index=True)

    pickup_location = db.Column(db.String(120), nullable=True)
    gateway_reference = db.Column(db.String(80), nullable=True)   # id returned by the sandbox/provider

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    paid_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)

    listing = db.relationship("Listing")
    buyer = db.relationship("User", foreign_keys=[buyer_id])
    seller = db.relationship("User", foreign_keys=[seller_id])
    disputes = db.relationship("Dispute", back_populates="transaction", cascade="all, delete-orphan")

    def status_label(self):
        return self.status.value.replace("_", " ").title()

    def __repr__(self):
        return f"<Transaction {self.reference} {self.status.value}>"


class Dispute(db.Model):
    __tablename__ = "disputes"

    id = db.Column(db.Integer, primary_key=True)
    transaction_id = db.Column(db.Integer, db.ForeignKey("transactions.id"), nullable=False)
    raised_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    reason = db.Column(db.String(80), nullable=False)   # e.g. "item_not_received"
    details = db.Column(db.Text, nullable=True)
    status = db.Column(db.Enum(ReportStatus), default=ReportStatus.OPEN)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    resolved_at = db.Column(db.DateTime, nullable=True)
    admin_notes = db.Column(db.Text, nullable=True)

    transaction = db.relationship("Transaction", back_populates="disputes")
    raised_by = db.relationship("User")


# ---------------------------------------------------------------------------
# Reviews / Trust
# ---------------------------------------------------------------------------

class Review(db.Model):
    __tablename__ = "reviews"

    id = db.Column(db.Integer, primary_key=True)
    transaction_id = db.Column(db.Integer, db.ForeignKey("transactions.id"), nullable=False)
    reviewer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    reviewee_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    rating = db.Column(db.Integer, nullable=False)     # 1-5
    comment = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    transaction = db.relationship("Transaction")
    reviewer = db.relationship("User", foreign_keys=[reviewer_id])
    reviewee = db.relationship("User", foreign_keys=[reviewee_id])

    __table_args__ = (db.UniqueConstraint("transaction_id", "reviewer_id",
                                           name="uq_review_once_per_transaction"),)


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

class NotificationType(enum.Enum):
    MESSAGE = "message"
    OFFER = "offer"
    SALE = "sale"
    SWAP = "swap"
    WISHLIST_PRICE_DROP = "wishlist_price_drop"
    WISHLIST_AVAILABLE = "wishlist_available"
    NEW_REVIEW = "new_review"
    DONATION_REQUEST = "donation_request"
    SYSTEM = "system"


class Notification(db.Model):
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    notification_type = db.Column(db.Enum(NotificationType), nullable=False)
    title = db.Column(db.String(160), nullable=False)
    body = db.Column(db.String(255), nullable=True)
    link = db.Column(db.String(255), nullable=True)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User")


# ---------------------------------------------------------------------------
# Gamification
# ---------------------------------------------------------------------------

class Badge(db.Model):
    __tablename__ = "badges"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    description = db.Column(db.String(255))
    icon = db.Column(db.String(50), default="bi-award")


class UserBadge(db.Model):
    __tablename__ = "user_badges"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    badge_id = db.Column(db.Integer, db.ForeignKey("badges.id"), nullable=False)
    earned_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User")
    badge = db.relationship("Badge")

    __table_args__ = (db.UniqueConstraint("user_id", "badge_id", name="uq_user_badge"),)


# ---------------------------------------------------------------------------
# Reports (content moderation - distinct from transaction Disputes)
# ---------------------------------------------------------------------------

class Report(db.Model):
    __tablename__ = "reports"

    id = db.Column(db.Integer, primary_key=True)
    reporter_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    listing_id = db.Column(db.Integer, db.ForeignKey("listings.id"), nullable=True)
    reported_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    reason = db.Column(db.String(120), nullable=False)
    details = db.Column(db.Text, nullable=True)
    status = db.Column(db.Enum(ReportStatus), default=ReportStatus.OPEN)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    reporter = db.relationship("User", foreign_keys=[reporter_id])
    listing = db.relationship("Listing")
    reported_user = db.relationship("User", foreign_keys=[reported_user_id])


# ---------------------------------------------------------------------------
# Platform settings (admin-configurable, e.g. service fee)
# ---------------------------------------------------------------------------

class PlatformSetting(db.Model):
    __tablename__ = "platform_settings"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(80), unique=True, nullable=False)
    value = db.Column(db.String(255), nullable=False)

    @staticmethod
    def get(key, default=None):
        row = PlatformSetting.query.filter_by(key=key).first()
        return row.value if row else default

    @staticmethod
    def set(key, value):
        row = PlatformSetting.query.filter_by(key=key).first()
        if row:
            row.value = str(value)
        else:
            row = PlatformSetting(key=key, value=str(value))
            db.session.add(row)
        db.session.commit()
