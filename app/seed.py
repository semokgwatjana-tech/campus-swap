"""
Reference data the app needs in order to work: the listing categories and the
badge definitions. This creates NO users, NO listings and NO sample content.
Everything people see on the site is created by real people.
"""

from app.extensions import db
from app.models import Category, Badge

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


def load_reference_data():
    """Add any missing categories and badges. Safe to run again at any time."""
    for name, slug, icon in CATEGORIES:
        if not Category.query.filter_by(slug=slug).first():
            db.session.add(Category(name=name, slug=slug, icon=icon))
    for name, description, icon in BADGES:
        if not Badge.query.filter_by(name=name).first():
            db.session.add(Badge(name=name, description=description, icon=icon))
    db.session.commit()
