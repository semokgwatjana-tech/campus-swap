"""
Seeds the database with realistic demo data so the platform can be explored
immediately after setup: categories, a handful of student accounts, sample
listings (sell / swap / donate), and a couple of badges.
"""

from app.extensions import db
from app.models import (
    User, Profile, Category, Listing, ListingImage, Badge,
    UserRole, ListingType, ListingCondition, ListingStatus,
)

CATEGORIES = [
    ("Textbooks", "textbooks", "bi-book"),
    ("Past Papers", "past-papers", "bi-file-earmark-text"),
    ("Notes", "notes", "bi-journal-text"),
    ("Calculators", "calculators", "bi-calculator"),
    ("Laboratory Equipment", "laboratory-equipment", "bi-flask"),
    ("Uniforms", "uniforms", "bi-briefcase"),
    ("Stationery", "stationery", "bi-pencil"),
    ("Laptops", "laptops", "bi-laptop"),
    ("Study Desks", "study-desks", "bi-lamp"),
    ("Backpacks", "backpacks", "bi-backpack2"),
]

BADGES = [
    ("Verified Seller", "Completed student verification and made a sale", "bi-patch-check"),
    ("Campus Hero", "Helped many fellow students through donations", "bi-mortarboard"),
    ("Top Donor", "Among the top donors on their campus", "bi-heart"),
    ("Fast Responder", "Replies to messages quickly", "bi-lightning"),
    ("Trusted Seller", "Consistently high ratings from buyers", "bi-shield-check"),
    ("100 Sales", "Reached 100 completed sales", "bi-trophy"),
    ("Top Reviewer", "Left thoughtful reviews for many transactions", "bi-star"),
]

DEMO_USERS = [
    dict(full_name="Sarah Mokoena", student_number="S2023001", school_email="sarah.mokoena@campusswap.app",
         course="BCom Accounting", year_of_study="2nd Year", campus="Main Campus"),
    dict(full_name="Thabo Nkosi", student_number="S2022014", school_email="thabo.nkosi@campusswap.app",
         course="BSc Computer Science", year_of_study="3rd Year", campus="Engineering Campus"),
    dict(full_name="Aisha Patel", student_number="S2024087", school_email="aisha.patel@campusswap.app",
         course="LLB Law", year_of_study="1st Year", campus="City Campus"),
    dict(full_name="Lindiwe Dube", student_number="S2021045", school_email="lindiwe.dube@campusswap.app",
         course="BSc Nursing", year_of_study="4th Year", campus="Health Sciences Campus"),
]

DEMO_LISTINGS = [
    dict(title="Financial Accounting 101 Textbook (5th Edition)",
         description="Barely used, no highlighting. Perfect for first-year Accounting students.",
         category_slug="textbooks", listing_type=ListingType.SELL, condition=ListingCondition.EXCELLENT,
         price=280, campus="Main Campus"),
    dict(title="Casio FX-991 Scientific Calculator",
         description="Reliable calculator, all functions working perfectly.",
         category_slug="calculators", listing_type=ListingType.SELL, condition=ListingCondition.GOOD,
         price=220, campus="Engineering Campus"),
    dict(title="2023 Past Exam Papers - Intro to Law",
         description="Full set of past papers with memo answers, great for exam prep.",
         category_slug="past-papers", listing_type=ListingType.SELL, condition=ListingCondition.NEW,
         price=50, campus="City Campus"),
    dict(title="Nursing Uniform Set (Size M)",
         description="Clean uniform set, only worn for one semester.",
         category_slug="uniforms", listing_type=ListingType.DONATE, condition=ListingCondition.GOOD,
         price=0, campus="Health Sciences Campus"),
    dict(title="Calculus Textbook - Swap for Physics Textbook",
         description="Looking to swap my Calculus 2 textbook for a Physics 1 textbook.",
         category_slug="textbooks", listing_type=ListingType.SWAP, condition=ListingCondition.GOOD,
         price=0, campus="Main Campus", swap_for="Physics 1 Textbook"),
    dict(title="Study Desk with Drawer",
         description="Compact wooden study desk, great for res rooms.",
         category_slug="study-desks", listing_type=ListingType.SELL, condition=ListingCondition.FAIR,
         price=450, campus="Main Campus"),
]


def run_seed():
    # Categories
    slug_to_category = {}
    for name, slug, icon in CATEGORIES:
        category = Category.query.filter_by(slug=slug).first()
        if not category:
            category = Category(name=name, slug=slug, icon=icon)
            db.session.add(category)
            db.session.flush()
        slug_to_category[slug] = category

    # Badges
    for name, description, icon in BADGES:
        if not Badge.query.filter_by(name=name).first():
            db.session.add(Badge(name=name, description=description, icon=icon))

    db.session.commit()

    # Users
    created_users = []
    for data in DEMO_USERS:
        user = User.query.filter_by(school_email=data["school_email"]).first()
        if not user:
            user = User(
                full_name=data["full_name"],
                student_number=data["student_number"],
                school_email=data["school_email"],
                is_verified=True,
                email_confirmed=True,
            )
            user.set_password("password123")
            db.session.add(user)
            db.session.flush()
            db.session.add(Profile(
                user_id=user.id, course=data["course"],
                year_of_study=data["year_of_study"], campus=data["campus"],
            ))
        created_users.append(user)
    db.session.commit()

    # Listings (round-robin across demo users)
    for i, data in enumerate(DEMO_LISTINGS):
        if Listing.query.filter_by(title=data["title"]).first():
            continue
        seller = created_users[i % len(created_users)]
        listing = Listing(
            seller_id=seller.id,
            category_id=slug_to_category[data["category_slug"]].id,
            title=data["title"],
            description=data["description"],
            listing_type=data["listing_type"],
            condition=data["condition"],
            price=data["price"],
            swap_for=data.get("swap_for"),
            campus=data["campus"],
            status=ListingStatus.ACTIVE,
        )
        db.session.add(listing)
        db.session.flush()
        db.session.add(ListingImage(listing_id=listing.id, filename="placeholder.png", position=0))

    db.session.commit()
