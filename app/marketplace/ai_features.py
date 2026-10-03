"""
Campus Swap - Smart AI Feature Placeholders
---------------------------------------------
These functions are intentionally provider-agnostic stubs. Each one returns
a realistic, well-shaped response so the UI can be fully built and
demonstrated today. Swapping in a real AI API later (e.g. the Anthropic
API) means editing ONLY the body of these functions - no route or template
changes required.

To connect a real provider, you would typically:
  1. Add your API key to an environment variable (never hard-code it).
  2. Replace the mocked logic below with an API call.
  3. Keep the same return shape so templates keep working.
"""

import re
from statistics import mean

from app.models import Listing, ListingStatus, Category


# Rough baseline prices (R) per category, used only for the offline demo
# price-suggestion heuristic below.
_CATEGORY_BASELINE_PRICE = {
    "textbooks": 350,
    "past-papers": 60,
    "notes": 80,
    "calculators": 250,
    "laboratory-equipment": 300,
    "uniforms": 200,
    "stationery": 40,
    "laptops": 4500,
    "study-desks": 600,
    "backpacks": 250,
}

_CONDITION_MULTIPLIER = {
    "New": 1.0,
    "Excellent": 0.8,
    "Good": 0.6,
    "Fair": 0.4,
}


def suggest_price(category_slug, condition, title=""):
    """
    AI Price Suggestion (placeholder).

    A real implementation would call an AI/pricing API with the book
    edition, condition, historical Campus Swap sale prices, and current
    market demand. For now this blends a category baseline, the condition
    multiplier, and the median price of similar *currently active*
    listings so the suggestion still feels grounded in real marketplace
    data.
    """
    baseline = _CATEGORY_BASELINE_PRICE.get(category_slug, 150)
    multiplier = _CONDITION_MULTIPLIER.get(condition, 0.6)
    heuristic_price = round(baseline * multiplier, -1) or 10

    similar_prices = []
    category = Category.query.filter_by(slug=category_slug).first()
    if category:
        similar = (
            Listing.query.filter_by(category_id=category.id, status=ListingStatus.ACTIVE)
            .limit(25)
            .all()
        )
        similar_prices = [float(l.price) for l in similar if l.price and float(l.price) > 0]

    if similar_prices:
        market_median = sorted(similar_prices)[len(similar_prices) // 2]
        suggested = round((heuristic_price + market_median) / 2, -1) or heuristic_price
    else:
        suggested = heuristic_price

    return {
        "suggested_price": max(suggested, 10),
        "price_range_low": max(round(suggested * 0.8, -1), 10),
        "price_range_high": round(suggested * 1.25, -1),
        "based_on": [
            "Category baseline pricing",
            f"Item condition ({condition})",
            f"{len(similar_prices)} similar active listing(s) on Campus Swap",
            "Market demand (placeholder - connect a live AI pricing API for real demand signals)",
        ],
    }


def generate_listing_from_image(image_filename=None, hint_text=""):
    """
    AI Listing Generator (placeholder).

    A production build would send the uploaded photo to a vision-capable AI
    model and ask it to identify the item, then generate a title,
    description, category, and keywords. Here we return a helpful,
    clearly-labelled template the student can edit, so the "Generate from
    photo" button is fully wired up end-to-end in the UI.
    """
    base_title = hint_text.strip().title() if hint_text.strip() else "Study Item (edit this title)"
    return {
        "title": base_title,
        "description": (
            "AI-drafted description - please review and edit before publishing.\n\n"
            "This item is in good, usable condition and ready for its next student owner. "
            "Add details such as the edition, module code, or any markings/highlighting so "
            "buyers know exactly what they're getting."
        ),
        "suggested_category": "textbooks",
        "keywords": ["textbook", "second-hand", "student", "campus swap"],
        "note": "This is a placeholder AI suggestion. Connect a vision-capable AI API to "
                "auto-detect the item from the photo in production.",
    }


def smart_search(query_text):
    """
    AI Smart Search (placeholder).

    Interprets a natural-language query (e.g. "I need first year Accounting
    books") and maps it to marketplace filters. The real version would use
    an LLM for intent parsing; this uses lightweight keyword matching so
    the search bar behaves sensibly today.
    """
    text = query_text.lower()
    year_match = re.search(r"(first|1st|second|2nd|third|3rd|final)\s*year", text)
    year = year_match.group(0) if year_match else None

    subject_keywords = [
        "accounting", "law", "physics", "chemistry", "biology", "economics",
        "engineering", "mathematics", "statistics", "psychology", "nursing",
        "computer science", "business",
    ]
    subject = next((s for s in subject_keywords if s in text), None)

    result_types = []
    if "book" in text or "textbook" in text:
        result_types.append("Books")
    if "note" in text:
        result_types.append("Notes")
    if "past paper" in text or "exam" in text:
        result_types.append("Past Papers")
    if "calculator" in text:
        result_types.append("Calculators")
    if not result_types:
        result_types = ["Books", "Notes", "Past Papers"]

    keywords = [w for w in [subject, year] if w]
    return {
        "interpreted_subject": subject,
        "interpreted_year": year,
        "result_categories": result_types,
        "suggested_keywords": keywords or [text.strip()],
        "note": "AI Smart Search is running in placeholder mode - keyword matching only. "
                "Connect an AI API for full natural-language understanding, including future "
                "tutor matching.",
    }
