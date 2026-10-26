"""
Checks for the pure security rules: password policy, age sides, rate limits,
email typo hints and tokens. No database or web framework needed.

Run from the project root:   python tests/test_security_rules.py
"""
import importlib.util
import sys
import types
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Stand-in package so the modules load without Flask installed.
pkg = types.ModuleType("app"); pkg.__path__ = [str(ROOT / "app")]; sys.modules["app"] = pkg

def load(name):
    spec = importlib.util.spec_from_file_location(f"app.{name}", ROOT / "app" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec); sys.modules[f"app.{name}"] = mod; spec.loader.exec_module(mod); return mod

common = load("common_passwords")
# security.py imports werkzeug, which is installed alongside Flask
sec = load("security"); age = load("age_rules"); rl = load("ratelimit_rules")

# ---- passwords ----
P = sec.password_problem
assert P("short1") is not None                                  # too short
assert P("a" * 129) is not None                                 # too long
for weak in ["password123", "Password123", "Password123!", "P@ssw0rd123", "qwertyuiop", "1234567890", "iloveyou2025",
             "campusswap2026", "Welcome2024!", "aaaaaaaaaaaa", "abcdefghijkl", "0123456789012"]:
    assert P(weak) is not None, weak
assert P("correct horse battery staple") is None                # long passphrase is fine
assert P("Tr4in-Cloud-Mango-77") is None
assert P("xk29-plum-river-ghost") is None
assert P("sipho.mokoena2024xyz", email="sipho.mokoena@uj.ac.za") is not None        # contains email name
assert P("Thabo-is-awesome-77", name="Thabo Nkosi") is not None                      # contains first name
assert P("blue-kettle-orbit-91", email="sipho@uj.ac.za", name="Sipho Dlamini") is None

# ---- email helpers ----
assert sec.email_typo_hint("sipho@gmail.con") == "Did you mean sipho@gmail.com?"
assert sec.email_typo_hint("sipho@gmail.com") is None
assert sec.email_typo_hint("sipho@uj.ac.za") is None
assert sec.mask_email("sipho@uj.ac.za") == "si***@uj.ac.za"
assert sec.mask_email("ab@x.co") == "a***@x.co"
t = sec.new_token(); assert len(t) >= 40 and sec.hash_token(t) != t and sec.hash_token(t) == sec.hash_token(t)
assert sec.hash_token(t) != sec.hash_token(t + "x")

# ---- age and sides ----
today = date(2026, 10, 24)
assert age.side_of(date(2008, 10, 24), today) == "adult"        # 18 today
assert age.side_of(date(2008, 10, 25), today) == "learner"      # 18 tomorrow
assert age.side_of(date(2010, 1, 1), today) == "learner"
assert age.side_of(date(2000, 5, 5), today) == "adult"
assert age.side_of(None, today) is None
assert age.eighteen_cutoff(today) == date(2008, 10, 24)
assert age.eighteen_cutoff(date(2028, 2, 29)) == date(2010, 2, 28)
assert age.dob_problem(date(2014, 1, 1), today) is not None     # 12 years old
assert age.dob_problem(date(2013, 10, 24), today) is None       # 13 today
assert age.dob_problem(date(2030, 1, 1), today) is not None     # future
assert age.dob_problem(date(1900, 1, 1), today) is not None     # too old
assert age.dob_problem(None, today) is not None

# ---- rate limits: 5 wrong passwords in 15 minutes ----
D = rl.decide
now = 10_000.0
ok, wait = D([now - 10, now - 20, now - 30, now - 40], now, 5, 900); assert ok and wait == 0              # 4 so far: still allowed
ok, wait = D([now - 10, now - 20, now - 30, now - 40, now - 50], now, 5, 900); assert not ok and wait == 850   # 5: blocked
ok, wait = D([now - 901, now - 902, now - 903, now - 904, now - 905], now, 5, 900); assert ok                  # all too old
ok, wait = D([now - 899] + [now - 10] * 4, now, 5, 900); assert not ok and wait == 1                          # oldest drops off in 1s
ok, wait = D([now - 800, now - 700, now - 600, now - 500, now - 400, now - 300], now, 5, 900)
assert not ok and wait == 200                                                                                   # 6 attempts: free once the 2nd oldest ages out
assert rl.RULES["login"][0] == ("account", 5, 900)
assert rl.minutes_text(1) == "1 minute" and rl.minutes_text(61) == "2 minutes" and rl.minutes_text(850) == "15 minutes"
print("All security rule checks passed.")
