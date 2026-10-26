"""
Checks for the parts of Settings that do not need a database:
two-step codes (against the official RFC 6238 test values), recovery codes,
and username and phone rules.

Run from the project root:   python tests/test_settings_logic.py
"""
import importlib.util
import sys
import types
from datetime import datetime as d
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parent.parent


# Stand-in package so security.py can import its sibling modules without Flask installed.
_pkg = types.ModuleType("app"); _pkg.__path__ = [str(ROOT / "app")]; sys.modules.setdefault("app", _pkg)


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sec = load("security", "app/security.py")

secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"          # RFC 6238 test secret
assert sec.totp_now(secret, at=59) == "287082"
assert sec.totp_now(secret, at=1111111109) == "081804"
assert sec.totp_now(secret, at=1234567890) == "005924"
assert sec.verify_totp(secret, "287082", at=59)
assert sec.verify_totp(secret, "287082", at=89)                # one step of clock drift
assert not sec.verify_totp(secret, "287082", at=149)           # too old
assert not sec.verify_totp(secret, "12345", at=59)
plain, stored = sec.new_recovery_codes()
left = sec.use_recovery_code(stored, plain[0])
assert left and sec.recovery_codes_left(left) == 7
assert sec.use_recovery_code(left, plain[0]) is None           # each code works once
assert sec.clean_username("@Nkgehle_K") == "nkgehle_k"
assert all(sec.clean_username(x) is None for x in ["ab", "admin", "has space", "a..b", ".x.", "a" * 31])
assert sec.clean_phone("081 737 0210") == "0817370210"
assert sec.clean_phone("+27 81 737 0210") == "+27817370210"
assert sec.clean_phone("12345") is None

print("All settings logic checks passed.")
