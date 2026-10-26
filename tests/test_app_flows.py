"""
End-to-end checks of the main flows, run against a throw-away in-memory database.

IMPORTANT: these need the real libraries (pip install -r requirements.txt). They could not be run
where this version was written, so run them once on your own computer and send back anything that
fails:

    set FLASK_ENV=development        (Windows PowerShell: $env:FLASK_ENV="development")
    python -m unittest tests.test_app_flows -v
"""
import re
import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest import mock

from app import create_app
from app.extensions import db
from app.models import (
    User, Profile, Listing, ListingType, ListingStatus, ListingCondition, Category, Guardian,
    Transaction, TransactionStatus, Message, Conversation,
)

PASSWORD = "blue-kettle-orbit-91"


def years_ago(n):
    today = date.today()
    return today.replace(year=today.year - n, day=min(today.day, 28))


class Flows(unittest.TestCase):
    def setUp(self):
        self.app = create_app("testing")
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        db.session.add(Category(name="Textbooks", slug="textbooks", icon="book"))
        db.session.commit()
        self.client = self.app.test_client()
        self.sent = []
        patcher = mock.patch("app.accounts.send_email", side_effect=lambda to, subject, body: self.sent.append((to, body)) or True)
        patcher.start(); self.addCleanup(patcher.stop)

    def tearDown(self):
        db.session.remove(); db.drop_all(); self.ctx.pop()

    # -- helpers --
    def make_user(self, email, age=25, verified=True, guardian=False):
        u = User(full_name=email.split("@")[0].title() + " Test", student_number="S-" + email, school_email=email,
                 date_of_birth=years_ago(age), email_confirmed=True, is_verified=verified)
        u.set_password(PASSWORD)
        db.session.add(u); db.session.flush()
        db.session.add(Profile(user_id=u.id, campus="Main Campus"))
        if guardian:
            db.session.add(Guardian(learner_id=u.id, guardian_name="Parent", guardian_email="parent@x.co.za",
                                    status="confirmed", confirmed_at=datetime.utcnow()))
        db.session.commit()
        return u

    def make_listing(self, seller, price=180, title="Maths Guide", ltype=ListingType.SELL):
        l = Listing(seller_id=seller.id, title=title, description="Good condition", category_id=1,
                    listing_type=ltype, condition=ListingCondition.GOOD, price=price, campus="Main Campus",
                    status=ListingStatus.ACTIVE)
        db.session.add(l); db.session.commit()
        return l

    def login(self, email, password=PASSWORD):
        return self.client.post("/auth/login", data={"login-school_email": email, "login-password": password},
                                follow_redirects=True)

    # -- sign-in limits --
    def test_five_wrong_passwords_lock_sign_in(self):
        self.make_user("a@x.co.za")
        for _ in range(5):
            self.login("a@x.co.za", "wrong-password-1")
        page = self.login("a@x.co.za")                       # even the RIGHT password is refused now
        self.assertIn(b"Too many tries", page.data)

    def test_wrong_email_and_wrong_password_look_the_same(self):
        self.make_user("a@x.co.za")
        one = self.login("a@x.co.za", "wrong-password-1").data
        two = self.login("nobody@x.co.za", "wrong-password-1").data
        self.assertIn(b"Incorrect email or password", one)
        self.assertIn(b"Incorrect email or password", two)

    # -- passwords and email --
    def test_weak_password_is_refused_at_signup(self):
        r = self.client.post("/auth/register", data={
            "signup-full_name": "Thandi Test", "signup-student_number": "T1", "signup-school_email": "t@x.co.za",
            "signup-date_of_birth": years_ago(22).isoformat(), "signup-year_of_study": "1st Year", "signup-campus": "Main Campus",
            "signup-password": "Password123!", "signup-confirm_password": "Password123!", "signup-consent": "y"})
        self.assertIn(b"too common", r.data)
        self.assertIsNone(User.query.filter_by(school_email="t@x.co.za").first())

    def test_email_must_be_confirmed_before_sign_in(self):
        with mock.patch("app.auth.routes.mail_is_configured", return_value=True):
            self.client.post("/auth/register", data={
                "signup-full_name": "Thandi Test", "signup-student_number": "T1", "signup-school_email": "t@x.co.za",
                "signup-date_of_birth": years_ago(22).isoformat(), "signup-year_of_study": "1st Year", "signup-campus": "Main Campus",
                "signup-password": PASSWORD, "signup-confirm_password": PASSWORD, "signup-consent": "y"})
            user = User.query.filter_by(school_email="t@x.co.za").first()
            self.assertFalse(user.email_confirmed)
            self.assertIn(b"confirm your email", self.login("t@x.co.za").data.lower())
            link = re.search(r"/auth/verify/(\S+)", self.sent[-1][1]).group(1)
            self.client.get("/auth/verify/" + link)
            self.assertTrue(db.session.get(User, user.id).email_confirmed)

    def test_logout_needs_post(self):
        self.make_user("a@x.co.za"); self.login("a@x.co.za")
        self.assertEqual(self.client.get("/auth/logout").status_code, 405)
        self.assertEqual(self.client.post("/auth/logout").status_code, 302)

    # -- the two sides --
    def test_learners_and_adults_cannot_see_each_other(self):
        adult = self.make_user("adult@x.co.za", age=30)
        learner = self.make_user("kid@x.co.za", age=16, guardian=True)
        adult_item = self.make_listing(adult, title="Adult Item")
        kid_item = self.make_listing(learner, title="Learner Item", ltype=ListingType.SWAP, price=0)
        self.login("kid@x.co.za")
        self.assertEqual(self.client.get(f"/listing/{adult_item.id}").status_code, 404)
        self.assertEqual(self.client.get(f"/listing/{kid_item.id}").status_code, 200)
        self.assertNotIn(b"Adult Item", self.client.get("/browse").data)
        self.client.post("/auth/logout"); self.login("adult@x.co.za")
        self.assertEqual(self.client.get(f"/listing/{kid_item.id}").status_code, 404)

    def test_learner_stays_locked_until_guardian_confirms(self):
        self.make_user("kid@x.co.za", age=15)                   # no confirmed guardian
        r = self.client.post("/auth/login", data={"login-school_email": "kid@x.co.za", "login-password": PASSWORD})
        r = self.client.get("/dashboard")
        self.assertIn("/parent/waiting", r.headers.get("Location", ""))

    def test_learner_cannot_buy_without_permission(self):
        adult = self.make_user("seller@x.co.za", age=16, guardian=True)
        kid = self.make_user("buyer@x.co.za", age=16, guardian=True)
        item = self.make_listing(adult)
        self.login("buyer@x.co.za")
        self.client.post(f"/listing/{item.id}/buy")
        self.assertEqual(Transaction.query.count(), 0)

    # -- buying --
    def test_only_one_buyer_can_reserve(self):
        seller = self.make_user("s@x.co.za"); b1 = self.make_user("b1@x.co.za"); b2 = self.make_user("b2@x.co.za")
        item = self.make_listing(seller)
        self.login("b1@x.co.za"); self.client.post(f"/listing/{item.id}/buy")
        self.client.post("/auth/logout"); self.login("b2@x.co.za"); self.client.post(f"/listing/{item.id}/buy")
        self.assertEqual(Transaction.query.count(), 1)
        self.assertEqual(Transaction.query.first().buyer_id, b1.id)

    def test_accepted_chat_offer_sets_price_and_receipt(self):
        seller = self.make_user("s@x.co.za"); buyer = self.make_user("b@x.co.za")
        item = self.make_listing(seller, price=180)
        self.login("b@x.co.za")
        self.client.post(f"/messages/start/{item.id}")
        convo = Conversation.query.first()
        self.client.post(f"/messages/{convo.id}", data={"body": "Take less?", "offer_price": "150"})
        offer = Message.query.filter(Message.offer_price.isnot(None)).first()
        self.assertEqual(offer.offer_status, "pending")
        self.client.post(f"/messages/{convo.id}/offer/{offer.id}/accept")          # the buyer cannot accept their own offer
        self.assertEqual(db.session.get(Message, offer.id).offer_status, "pending")
        self.client.post("/auth/logout"); self.login("s@x.co.za")
        self.client.post(f"/messages/{convo.id}/offer/{offer.id}/accept")
        self.assertEqual(db.session.get(Message, offer.id).offer_status, "accepted")
        self.client.post("/auth/logout"); self.login("b@x.co.za")
        self.client.post(f"/listing/{item.id}/buy")
        t = Transaction.query.first()
        self.assertEqual((t.price_source, t.item_price, t.listed_price), ("chat_offer", Decimal("150.00"), Decimal("180.00")))

    def test_only_buyer_can_confirm_handover(self):
        seller = self.make_user("s@x.co.za"); buyer = self.make_user("b@x.co.za")
        item = self.make_listing(seller)
        t = Transaction(reference="CS-T-1", listing_id=item.id, buyer_id=buyer.id, seller_id=seller.id, item_price=180,
                        service_fee=0, total_amount=180, status=TransactionStatus.PAID)
        db.session.add(t); db.session.commit()
        self.login("s@x.co.za")
        self.assertEqual(self.client.post(f"/transaction/{t.id}/complete").status_code, 403)
        self.client.post("/auth/logout"); self.login("b@x.co.za")
        self.client.post(f"/transaction/{t.id}/complete")
        self.assertEqual(db.session.get(Transaction, t.id).status, TransactionStatus.COMPLETED)


if __name__ == "__main__":
    unittest.main()
