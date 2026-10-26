"""
Rate limit rules. Pure functions, no database, so they can be tested alone.
app/ratelimit.py applies them to stored attempts.

Each rule is (scope, how many attempts, within how many seconds). A kind of
action is blocked as soon as ANY of its rules is used up.
"""

import math

RULES = {
    # wrong passwords: 5 per account, and a looser limit per network address
    "login":        [("account", 5, 900), ("ip", 30, 900)],
    # wrong two-step or recovery codes
    "twofa":        [("account", 5, 900), ("ip", 30, 900)],
    # asking for a password reset email
    "reset":        [("account", 3, 3600), ("ip", 10, 3600)],
    # creating accounts
    "register":     [("ip", 10, 3600)],
    # asking for another verification email
    "verify_email": [("account", 3, 3600), ("ip", 10, 3600)],
    # wrong "current password" typed inside Settings
    "password_check": [("account", 5, 900)],
    # guardian emails and sign-in links
    "guardian":     [("account", 3, 3600), ("ip", 10, 3600)],
}


def decide(attempt_times, now, limit, window_seconds):
    """Return (allowed, seconds_until_allowed). Times are plain seconds."""
    recent = sorted(t for t in attempt_times if now - t < window_seconds)
    if len(recent) < limit:
        return True, 0
    frees_at = recent[len(recent) - limit] + window_seconds
    return False, max(1, math.ceil(frees_at - now))


def minutes_text(seconds):
    minutes = max(1, math.ceil(seconds / 60))
    return f"{minutes} minute" + ("" if minutes == 1 else "s")
