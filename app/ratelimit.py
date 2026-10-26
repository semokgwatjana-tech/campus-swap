"""
Rate limiting backed by the database, so every server process shares the same
counts. The rules live in ratelimit_rules.py.

Attempts are stored as one-way hashes of the email and the visitor's address
(keyed with SECRET_KEY), never as the values themselves.
"""

import hashlib
import hmac
import random
from datetime import datetime, timedelta

from flask import current_app, request

from app.extensions import db
from app.models import LoginAttempt
from app.ratelimit_rules import RULES, decide

_EPOCH = datetime(1970, 1, 1)


def _seconds(moment):
    return (moment - _EPOCH).total_seconds()


def hash_value(value):
    key = current_app.config["SECRET_KEY"].encode("utf-8")
    return hmac.new(key, str(value).lower().encode("utf-8"), hashlib.sha256).hexdigest()


def client_ip():
    return request.remote_addr or "unknown"


def ip_hash():
    return hash_value(f"ip:{client_ip()}")


def _keys(kind, account):
    for scope, limit, window in RULES[kind]:
        if scope == "account":
            if account is None:
                continue
            yield hash_value(f"acct:{account}"), limit, window
        else:
            yield ip_hash(), limit, window


def check(kind, account=None):
    """(allowed, seconds_to_wait). Call BEFORE doing the work being limited."""
    now = datetime.utcnow()
    allowed, wait = True, 0
    for key, limit, window in _keys(kind, account):
        rows = (LoginAttempt.query
                .filter(LoginAttempt.kind == kind, LoginAttempt.key_hash == key,
                        LoginAttempt.created_at > now - timedelta(seconds=window))
                .order_by(LoginAttempt.created_at.desc()).limit(limit).all())
        ok, seconds = decide([_seconds(r.created_at) for r in rows], _seconds(now), limit, window)
        if not ok:
            allowed, wait = False, max(wait, seconds)
    return allowed, wait


def hit(kind, account=None):
    """Record one attempt. Returns True if this attempt just used up a limit
    (so the caller can warn the account owner exactly once)."""
    was_allowed, _ = check(kind, account)
    now = datetime.utcnow()
    for key, _limit, _window in _keys(kind, account):
        db.session.add(LoginAttempt(kind=kind, key_hash=key, created_at=now))
    db.session.commit()
    if random.random() < 0.05:                      # tidy up now and then
        LoginAttempt.query.filter(LoginAttempt.created_at < now - timedelta(days=2)).delete()
        db.session.commit()
    now_allowed, _ = check(kind, account)
    return was_allowed and not now_allowed


def clear(kind, account):
    """Forget one account's counted attempts (after a correct sign-in)."""
    key = hash_value(f"acct:{account}")
    LoginAttempt.query.filter_by(kind=kind, key_hash=key).delete()
    db.session.commit()
