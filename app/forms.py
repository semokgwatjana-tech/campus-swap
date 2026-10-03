"""
Flask-WTF form definitions.

Using FlaskForm everywhere gives us automatic CSRF protection and
server-side validation (never trust client-side validation alone).
"""

from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import (
    StringField, PasswordField, SelectField, TextAreaField, DecimalField,
    BooleanField, HiddenField, IntegerField
)
from wtforms.validators import (
    DataRequired, Email, Length, EqualTo, Optional, NumberRange, ValidationError
)

from app.models import User


CAMPUSES = [
    "Main Campus", "North Campus", "South Campus", "City Campus",
    "Engineering Campus", "Health Sciences Campus",
]

YEARS_OF_STUDY = ["1st Year", "2nd Year", "3rd Year", "4th Year", "Honours", "Masters", "PhD"]


class RegistrationForm(FlaskForm):
    full_name = StringField("Full Name", validators=[DataRequired(), Length(max=120)])
    student_number = StringField("Student Number", validators=[DataRequired(), Length(max=40)])
    school_email = StringField("School Email", validators=[DataRequired(), Email(), Length(max=160)])
    course = StringField("Course", validators=[Optional(), Length(max=120)])
    year_of_study = SelectField("Year of Study", choices=[(y, y) for y in YEARS_OF_STUDY],
                                 validators=[Optional()])
    campus = SelectField("Campus", choices=[(c, c) for c in CAMPUSES], validators=[DataRequired()])
    profile_picture = FileField("Profile Picture (optional)",
                                 validators=[Optional(), FileAllowed(["jpg", "jpeg", "png", "gif", "webp"])])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=8)])
    confirm_password = PasswordField(
        "Confirm Password",
        validators=[DataRequired(), EqualTo("password", message="Passwords must match.")]
    )
    consent = BooleanField(
        "consent",
        validators=[DataRequired(message="You must agree to the Terms & Conditions and Privacy Policy to create an account.")],
    )

    def validate_student_number(self, field):
        if User.query.filter_by(student_number=field.data).first():
            raise ValidationError("An account with this student number already exists.")

    def validate_school_email(self, field):
        if User.query.filter_by(school_email=field.data.lower()).first():
            raise ValidationError("An account with this email already exists.")


class LoginForm(FlaskForm):
    school_email = StringField("School Email", validators=[DataRequired(), Email()])
    password = PasswordField("Password", validators=[DataRequired()])
    remember_me = BooleanField("Remember me")


class ForgotPasswordForm(FlaskForm):
    school_email = StringField("School Email", validators=[DataRequired(), Email()])


class ResetPasswordForm(FlaskForm):
    token = HiddenField()
    password = PasswordField("New Password", validators=[DataRequired(), Length(min=8)])
    confirm_password = PasswordField(
        "Confirm New Password",
        validators=[DataRequired(), EqualTo("password", message="Passwords must match.")]
    )


class ListingForm(FlaskForm):
    title = StringField("Title", validators=[DataRequired(), Length(max=160)])
    description = TextAreaField("Description", validators=[DataRequired(), Length(max=3000)])
    category_id = SelectField("Category", coerce=int, validators=[DataRequired()])
    listing_type = SelectField(
        "Listing Type",
        choices=[("sell", "Sell"), ("swap", "Swap"), ("donate", "Donate")],
        validators=[DataRequired()],
    )
    price = DecimalField("Price (R)", validators=[Optional(), NumberRange(min=0)], places=2)
    swap_for = StringField("What would you like in exchange?", validators=[Optional(), Length(max=255)])
    condition = SelectField(
        "Condition",
        choices=[("New", "New"), ("Excellent", "Excellent"), ("Good", "Good"), ("Fair", "Fair")],
        validators=[DataRequired()],
    )
    campus = SelectField("Campus", choices=[(c, c) for c in CAMPUSES], validators=[DataRequired()])
    photos = FileField("Photos", validators=[Optional(), FileAllowed(["jpg", "jpeg", "png", "gif", "webp"])])

    def validate(self, extra_validators=None):
        if not super().validate(extra_validators=extra_validators):
            return False
        if self.listing_type.data == "sell" and (self.price.data is None or self.price.data <= 0):
            self.price.errors.append("Please enter a price greater than R0 for items you are selling.")
            return False
        return True


class MessageForm(FlaskForm):
    body = TextAreaField("Message", validators=[Optional(), Length(max=2000)])
    offer_price = DecimalField("Offer price (optional)", validators=[Optional(), NumberRange(min=0)], places=2)
    proposed_pickup = SelectField(
        "Proposed pickup point",
        choices=[
            ("Campus Library", "Campus Library"),
            ("Student Centre", "Student Centre"),
            ("Campus Security Office", "Campus Security Office"),
            ("Residence Reception", "Residence Reception"),
        ],
        validators=[Optional()],
    )
    image = FileField("Attach image", validators=[Optional(), FileAllowed(["jpg", "jpeg", "png", "gif", "webp"])])


class CheckoutForm(FlaskForm):
    payment_method = SelectField(
        "Payment method",
        choices=[("card", "Credit / Debit Card"), ("eft", "EFT / Bank Transfer"),
                 ("instant_eft", "Instant EFT (PayShap-style)")],
        validators=[DataRequired()],
    )
    card_number = StringField("Card number", validators=[Optional(), Length(max=25)])
    card_expiry = StringField("Expiry (MM/YY)", validators=[Optional(), Length(max=7)])
    card_cvv = StringField("CVV", validators=[Optional(), Length(max=4)])
    pickup_location = SelectField(
        "Pickup location",
        choices=[
            ("Campus Library", "Campus Library"),
            ("Student Centre", "Student Centre"),
            ("Campus Security Office", "Campus Security Office"),
            ("Residence Reception", "Residence Reception"),
        ],
        validators=[DataRequired()],
    )
    agree_refund_policy = BooleanField(
        "agree_refund_policy",
        validators=[DataRequired(message="Please confirm you've read the Refund Policy before paying.")],
    )


class SwapOfferForm(FlaskForm):
    offered_listing_id = SelectField("Your item to offer", coerce=int, validators=[DataRequired()])
    top_up_amount = DecimalField("Top-up amount (R), if any", validators=[Optional(), NumberRange(min=0)],
                                  places=2, default=0)
    message = TextAreaField("Message to seller", validators=[Optional(), Length(max=1000)])


class ReviewForm(FlaskForm):
    rating = SelectField("Rating", choices=[(str(i), f"{i} star{'s' if i > 1 else ''}") for i in range(5, 0, -1)],
                          validators=[DataRequired()])
    comment = TextAreaField("Comment", validators=[Optional(), Length(max=1000)])


class DisputeForm(FlaskForm):
    reason = SelectField("Reason", validators=[DataRequired()])
    details = TextAreaField("Additional details", validators=[Optional(), Length(max=2000)])


class ReportForm(FlaskForm):
    reason = SelectField(
        "Reason",
        choices=[
            ("prohibited_item", "Prohibited or inappropriate item"),
            ("scam", "Suspected scam / fraud"),
            ("misleading", "Misleading description or photos"),
            ("offensive", "Offensive content"),
            ("other", "Other"),
        ],
        validators=[DataRequired()],
    )
    details = TextAreaField("Details", validators=[Optional(), Length(max=1000)])


class SearchForm(FlaskForm):
    class Meta:
        csrf = False  # GET search form, CSRF not required for a read-only query

    q = StringField("Search", validators=[Optional(), Length(max=160)])
    category = SelectField("Category", validators=[Optional()])
    campus = SelectField("Campus", choices=[("", "All Campuses")] + [(c, c) for c in CAMPUSES],
                          validators=[Optional()])
    condition = SelectField("Condition", choices=[("", "Any Condition"), ("New", "New"), ("Excellent", "Excellent"),
                                                    ("Good", "Good"), ("Fair", "Fair")], validators=[Optional()])
    listing_type = SelectField("Type", choices=[("", "Buy, Swap or Donate"), ("sell", "For Sale"),
                                                  ("swap", "Swap Only"), ("donate", "Free / Donation")],
                                validators=[Optional()])
    sort = SelectField("Sort by", choices=[
        ("newest", "Newest"), ("cheapest", "Cheapest"), ("popular", "Most Popular"),
    ], validators=[Optional()])
