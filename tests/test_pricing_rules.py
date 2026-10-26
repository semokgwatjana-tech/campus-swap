"""
Checks for the price rules behind offers and receipts (no database needed).

Run from the project root:   python tests/test_pricing_rules.py
"""
import importlib.util
from datetime import datetime as d
from decimal import Decimal as D
from pathlib import Path

spec = importlib.util.spec_from_file_location("rules", Path(__file__).resolve().parent.parent / "app/pricing_rules.py")
rules = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rules)

# Offer amounts: must be above R0 and below the listed price
assert rules.offer_error(180, 150) is None
assert rules.offer_error(180, "150.50") is None
assert rules.offer_error(180, 180) is not None          # same as listed: pointless
assert rules.offer_error(180, 200) is not None          # higher than listed
assert rules.offer_error(180, 0) is not None
assert rules.offer_error(180, -5) is not None
assert rules.offer_error(180, "abc") is not None

# Which price is used, and where it came from
assert rules.choose_price(180, 150) == (D("150.00"), "chat_offer")
assert rules.choose_price(180, None) == (D("180.00"), "listing")
assert rules.choose_price(180, 180) == (D("180.00"), "listing")     # no discount, so listing
assert rules.choose_price(120, 150) == (D("120.00"), "listing")     # seller later cut the listing below the offer
assert rules.choose_price(180, 0) == (D("180.00"), "listing")
assert rules.money("3.745") == D("3.75") and rules.money(2.5) == D("2.50")
assert rules.difference(180, 150) == D("30.00")

# How an offer is treated over time (48 hour window)
sent, answered = d(2026, 10, 12, 10, 0), d(2026, 10, 12, 14, 32)
S = rules.offer_state
assert S(None, sent, None, d(2026, 10, 12, 11, 0), 48) == "legacy"
assert S("pending", sent, None, d(2026, 10, 13, 9, 59), 48) == "pending"
assert S("pending", sent, None, d(2026, 10, 14, 10, 1), 48) == "expired"
assert S("accepted", sent, answered, d(2026, 10, 14, 14, 31), 48) == "accepted"
assert S("accepted", sent, answered, d(2026, 10, 14, 14, 33), 48) == "expired"   # window counts from Accept
assert S("declined", sent, answered, d(2030, 1, 1), 48) == "declined"
assert S("used", sent, answered, d(2030, 1, 1), 48) == "used"
assert S("withdrawn", sent, None, d(2026, 10, 12, 11, 0), 48) == "withdrawn"
print("All price rule checks passed.")

# Price guide: honest only when there are enough real prices
G = rules.summarise_prices
assert G([100, 200]) is None                                   # too few: say nothing
assert G([]) is None and G([None, 0, -5]) is None              # nothing usable
assert G([100, 200, 300]) == {"low": D("100.00"), "median": D("200.00"), "high": D("300.00"), "count": 3}
assert G([150, 100, 300, 250]) ["median"] == D("200.00")       # median of four is the middle pair's average
assert G([120, 130, 140], minimum=4) is None
print("All price guide checks passed.")
