"""
Account security helpers: two-step verification (TOTP, RFC 6238), recovery
codes, and validation of usernames and phone numbers.

Only the standard library is used. The authenticator-app codes are the same
ones Google Authenticator, Microsoft Authenticator and Authy produce, so
nothing extra has to be installed on the server.
"""

import base64
import hashlib
import hmac
import json
import re
import secrets
import struct
import time
from urllib.parse import quote

from werkzeug.security import generate_password_hash, check_password_hash

USERNAME_RE = re.compile(r"^[a-z0-9_.]{3,30}$")
PHONE_RE = re.compile(r"^\+?[0-9]{9,15}$")
RESERVED_USERNAMES = {"admin", "administrator", "support", "campusswap", "campus_swap", "moderator", "staff"}


# --- Usernames and phone numbers ------------------------------------------

def clean_username(raw):
    """Return the lower-case username without a leading @, or None if invalid."""
    value = (raw or "").strip().lstrip("@").lower()
    if not USERNAME_RE.match(value) or value in RESERVED_USERNAMES:
        return None
    if value.startswith(".") or value.endswith(".") or ".." in value:
        return None
    return value


def clean_phone(raw):
    """Return the phone number with spaces, dashes and brackets removed, or None."""
    value = re.sub(r"[\s\-()]", "", raw or "")
    return value if PHONE_RE.match(value) else None


# --- TOTP -------------------------------------------------------------------

def new_totp_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _hotp(secret, counter, digits=6):
    padded = secret + "=" * (-len(secret) % 8)
    key = base64.b32decode(padded.upper())
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


def totp_now(secret, at=None, step=30):
    return _hotp(secret, int((time.time() if at is None else at) // step))


def verify_totp(secret, code, at=None, step=30, window=1):
    """Accept the current code and one step either side, to allow for clock drift."""
    code = re.sub(r"\s", "", code or "")
    if not secret or not re.fullmatch(r"[0-9]{6}", code):
        return False
    now = int((time.time() if at is None else at) // step)
    return any(hmac.compare_digest(_hotp(secret, now + d), code) for d in range(-window, window + 1))


def totp_uri(secret, account, issuer="Campus Swap"):
    return (f"otpauth://totp/{quote(issuer)}:{quote(account)}"
            f"?secret={secret}&issuer={quote(issuer)}&digits=6&period=30")


# --- Recovery codes ---------------------------------------------------------

def new_recovery_codes(count=8):
    """Return (plain_codes, json_of_hashes). Only the hashes are stored."""
    plain = [f"{secrets.token_hex(2)}-{secrets.token_hex(2)}" for _ in range(count)]
    return plain, json.dumps([generate_password_hash(c) for c in plain])


def use_recovery_code(stored_json, code):
    """Return the new stored JSON with the used code removed, or None if no match."""
    code = (code or "").strip().lower()
    try:
        hashes = json.loads(stored_json or "[]")
    except ValueError:
        return None
    for i, h in enumerate(hashes):
        if check_password_hash(h, code):
            return json.dumps(hashes[:i] + hashes[i + 1:])
    return None


def recovery_codes_left(stored_json):
    try:
        return len(json.loads(stored_json or "[]"))
    except ValueError:
        return 0


# --- Password policy ----------------------------------------------------------

import hashlib
from app.common_passwords import COMMON_PASSWORDS, COMMON_BASES

MIN_PASSWORD_LENGTH = 10
_LOOKALIKES = str.maketrans({"@": "a", "$": "s", "0": "o", "3": "e", "1": "i", "!": "i", "5": "s", "7": "t"})
_SEQUENCES = ("abcdefghijklmnopqrstuvwxyz", "0123456789", "qwertyuiopasdfghjklzxcvbnm")


def password_problem(password, email="", name="", min_length=MIN_PASSWORD_LENGTH):
    """Why a password is not good enough, or None. Length and guessability only;
    forcing symbols and capitals just produces predictable passwords."""
    password = password or ""
    if len(password) < min_length:
        return f"Use at least {min_length} characters."
    if len(password) > 128:
        return "Use 128 characters or fewer."
    lowered = password.lower()
    common = "That password is too common and easy to guess. Choose something less predictable."
    if lowered in COMMON_PASSWORDS:
        return common
    # Core word: drop trailing digits/symbols, then swap look-alike characters.
    core = re.sub(r"^[^a-z0-9@$!]+|[^a-z]+$", "", lowered)
    for candidate in (re.sub(r"[^a-z]", "", core.translate(_LOOKALIKES)),
                      re.sub(r"[^a-z]", "", lowered.translate(_LOOKALIKES))):
        if candidate in COMMON_BASES:
            return common
    if len(set(lowered)) <= 3:
        return "Avoid repeating just a few characters."
    for seq in _SEQUENCES:
        if lowered in seq * 2 or lowered in seq[::-1] * 2:      # runs that wrap around count too
            return "Avoid keyboard and number runs like 1234567890 or qwertyuiop."
    local = (email or "").split("@")[0].lower()
    if len(local) >= 4 and local in lowered:
        return "Your password should not contain the first part of your email address."
    for part in re.split(r"\s+", (name or "").lower()):
        if len(part) >= 4 and part in lowered:
            return "Your password should not contain your name."
    return None


# --- Email helpers -------------------------------------------------------------

_TYPO_DOMAINS = {
    "gmail.con": "gmail.com", "gmial.com": "gmail.com", "gmai.com": "gmail.com", "gmail.co": "gmail.com",
    "gamil.com": "gmail.com", "gnail.com": "gmail.com", "gmail.cm": "gmail.com", "gmail.comm": "gmail.com",
    "gmail.vom": "gmail.com", "yahoo.con": "yahoo.com", "yaho.com": "yahoo.com", "yahoo.co": "yahoo.com",
    "hotmail.con": "hotmail.com", "hotmial.com": "hotmail.com", "hotmail.co": "hotmail.com",
    "outlook.con": "outlook.com", "outlok.com": "outlook.com", "icloud.con": "icloud.com",
    "icoud.com": "icloud.com", "live.con": "live.com",
}


def email_typo_hint(email):
    """A friendly 'Did you mean...?' for a common typo in the domain, or None."""
    if "@" not in (email or ""):
        return None
    local, domain = email.strip().rsplit("@", 1)
    fixed = _TYPO_DOMAINS.get(domain.lower())
    return f"Did you mean {local}@{fixed}?" if fixed else None


def mask_email(email):
    """jo***@school.ac.za style, so a screen can say where mail went without exposing it."""
    if "@" not in (email or ""):
        return ""
    local, domain = email.rsplit("@", 1)
    return f"{local[:2]}***@{domain}" if len(local) > 2 else f"{local[:1]}***@{domain}"


# --- Tokens ----------------------------------------------------------------------

def new_token():
    return secrets.token_urlsafe(32)


def hash_token(token):
    """Tokens (reset, verify, guardian, sign-in) are stored only as this hash, so a
    leaked database copy cannot be used to take over an account."""
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()
