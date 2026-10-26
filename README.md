# Campus Swap 🎓

A trusted student economy platform — **buy, sell, swap, and donate** educational
resources within your campus. Built with Python (Flask), SQLAlchemy, and a
custom **neumorphic** design system (soft shadows, rounded corners, calm
green/white/navy palette).

## Quick Start

```bash
# 0. Local work only: say so, otherwise the app starts as the LIVE site and wants a real SECRET_KEY
#    Windows PowerShell:  $env:FLASK_ENV="development"      Mac/Linux:  export FLASK_ENV=development

# 1. Create a virtual environment
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set up the database
export FLASK_APP=run.py         # Windows: set FLASK_APP=run.py
flask init-db
flask create-admin --email admin@campusswap.app --password ChangeMe123

# 4. Run it
python run.py
# → http://localhost:5000
```

`flask init-db` also adds the listing categories and badges the app needs. It creates
no users and no listings. If your database still holds the sample students that
earlier versions created, back it up and then remove them with
`flask --app run.py clear-demo-data`.

## What's included

| Area | Status |
|---|---|
| Landing page (hero, how-it-works, features, stats, footer) | ✅ |
| Auth: register / login / logout / forgot & reset password | ✅ |
| Student verification (admin-approved), verified badge | ✅ |
| Dashboard: greeting, search, quick actions, recommendations, messages, notifications | ✅ |
| Marketplace: browse, filter, search, categories, listing detail, related items | ✅ |
| Sell / Edit listing, photo upload, preview | ✅ |
| **Payments & Transactions** (see below) | ✅ |
| Donations flow (request → approve → completed transaction) | ✅ |
| Swap flow (offer → accept/decline, optional cash top-up) | ✅ |
| Messaging (conversations, offers, pickup suggestions, image sharing, read receipts) | ✅ |
| Wishlist + notifications | ✅ |
| Reviews & trust score | ✅ |
| Student profiles + badges (gamification) | ✅ |
| Admin panel (users, listings, reports, disputes, settings, analytics) | ✅ |
| Price guide on the sell page (real Campus Swap prices only, shown once at least 3 similar items exist) | ✅ |
| Reports / content moderation | ✅ |

## Design & compliance pass (this revision)

This revision was audited end-to-end against a specific checklist and fixed
where it fell short. Most of the app already passed on inspection; what
follows is the honest accounting, not a marketing summary.

**Already compliant on inspection (verified, not just assumed):**
- No purple, no gradients, anywhere in the CSS
- No fake reviews/testimonials; landing page stats are live database counts,
  confirmed by reading the route code
- No AI-sounding marketing buzzwords, no unsupported superlative claims
- No scroll-triggered or cursor animations; a `prefers-reduced-motion` rule
  already existed
- All text/background colour pairs pass WCAG AA (checked by computing actual
  contrast ratios, not eyeballing it)
- Both images shipped with the app (avatar placeholder, listing placeholder)
  are simple original shapes with no copyright exposure

**Fixed in this pass:**
- Removed the Google Fonts CDN link (it was loaded but unused — the CSS
  already had a system-font fallback — and it contradicted the Privacy
  Policy's own claim of not using it)
- Removed two emoji from the UI copy
- Changed fully-pill-shaped (999px) badges/status chips to an 8px "chip"
  radius, consistent with the rest of the design system
- Added a real favicon (SVG + PNG fallback)
- Rewired dead `#` footer links to the real Terms/Privacy/Refund Policy
  routes and added a business-details line (with bracketed placeholders to
  fill in before launch)
- Added a skip-to-content link, `aria-label`s on every icon-only control,
  `aria-hidden="true"` on ~120 purely decorative icons, and converted a
  keyboard-inaccessible `href="#"` dropdown trigger into a real `<button>`
- Added descriptive `alt` text to avatars, listing photos, and shared chat
  images that previously had `alt=""`
- Replaced every em dash in the UI copy with standard punctuation
- Added a required "I've read the Refund Policy" checkbox at checkout,
  alongside the Terms/Privacy consent checkbox already required at
  registration

**Left as-is, deliberately:**
- No cookie-policy page and no cookie-consent banner. The app only sets a
  session cookie and a CSRF token, both strictly necessary to function, so
  under standard practice no consent banner is required. This reasoning is
  spelled out in the Privacy Policy's Cookies section rather than hidden.
- Bootstrap and Bootstrap Icons are still loaded from the jsDelivr CDN.
  Self-hosting them is the right production hardening step (see below) —
  it wasn't done here only because this build environment has no network
  access to fetch the library files. The CDN links now use
  `crossorigin="anonymous"` and `referrerpolicy="no-referrer"`, and the
  third-party exposure is disclosed in the Privacy Policy.

**Before you launch commercially, still do this:**
1. Replace every `[INSERT ...]` placeholder in the footer and in
   `legal/terms.html`, `legal/privacy_policy.html`, and
   `legal/refund_policy.html` with your real registered company name,
   CIPC registration number, address, and contact emails.
2. Have a South African attorney review the Terms, Privacy Policy, and
   Refund Policy — they are a solid, law-aware starting point (POPIA, the
   Consumer Protection Act, ECTA) but are explicitly labelled as templates,
   not legal advice.
3. Self-host Bootstrap, Bootstrap Icons, and pick a font you're licensed to
   bundle, to remove the remaining third-party CDN requests entirely.
4. Connect a real payment provider in `app/transactions/payment_gateway.py`
   and update the Refund Policy's payment-timing section to match its real
   settlement behaviour.

## Going live

Business details, password-reset email, campus email domains and the payment
provider are all set through environment settings, with no code edits. See
`docs/GO_LIVE.md` for the exact lines, the demo-data cleanup command
(`flask clear-demo-data`) and the admin password command
(`flask reset-password --email ...`).

## Mobile app

Campus Swap is installable as a Progressive Web App: open the deployed site
on a phone and use the browser's "Add to Home Screen" (Android Chrome) or
"Add to Home Screen" from the Share menu (iOS Safari). It gets a real icon,
opens full-screen with no browser bar, and caches its static assets for
resilience on a flaky connection. This works today, from any deployment,
with no extra steps beyond what's already in `app/static/manifest.webmanifest`
and `app/static/sw.js`.

For an actual app-store-installable `.apk`/`.ipa`, see `mobile-wrapper/` —
it's a Capacitor project scaffold that wraps the deployed site in a native
shell. Building the real binaries requires Android Studio (Android) and a
Mac with Xcode (iOS, which Apple requires) — see `mobile-wrapper/README.md`
for exact steps.

## Payment & Transaction System

This is the core of the spec, implemented in `app/transactions/`:

- **`payment_gateway.py`** — a swappable gateway abstraction. Today it's a
  **safe sandbox simulation** (no real money moves, no card data stored).
  To go live, write a new class with the same `charge()` / `verify_webhook()`
  interface for a real SA provider (Yoco, PayFast, Ozow/PayShap) and swap it
  in via `get_gateway()` — no route or template changes needed.
- **Server-side pricing only.** `utils.calculate_service_fee()` reads a
  configurable fee from `PlatformSetting` (editable in `/admin/settings`) and
  is recalculated on the server at reservation time *and* again immediately
  before charging — the browser can never influence the amount charged.
- **Reservation system.** Buying a listing sets `status=RESERVED` with a
  15-minute expiry (`Config.RESERVATION_TIMEOUT_MINUTES`) so two students can
  never pay for the same item; expired reservations release automatically.
- **Full status lifecycle:** `PENDING → RESERVED → PAYMENT_PROCESSING → PAID
  → READY_FOR_PICKUP → COMPLETED`, with `PAYMENT_FAILED`, `CANCELLED`,
  `REFUND_REQUESTED`, and `REFUNDED` branches — see `TransactionStatus` in
  `app/models.py`.
- **Unique transaction reference** per payment, e.g. `CS-2026-000184`, shown
  on the receipt and in purchase/sale history.
- **No card data is ever persisted** — only the last 4 digits are used for
  the on-screen receipt (`payment_gateway.mask_card_number`), and CVV is
  never stored at all.
- **Demo decline scenario:** at checkout, enter a card number **ending in
  `0000`** to see the `PAYMENT_FAILED` path; any other number succeeds.
- **Donations** use the same listing model with `price = R0` and skip the
  payment gateway entirely. **Swaps** are resource-for-resource with no
  payment, or resource + a cash top-up, in which case only the **difference**
  goes through the payment flow.
- **Disputes**: buyers/sellers can raise a structured dispute on any paid
  transaction; admins resolve it to `REFUNDED` or `COMPLETED` from
  `/admin/disputes`.
- **Safe pickup only** — checkout requires choosing from a fixed list of
  public campus locations (library, student centre, security office,
  residence reception); there is no field for a home address anywhere in the
  app.

## Project structure

```
campus_swap/
├── run.py                 # dev entry point
├── config.py              # env-driven config (SQLite dev → PostgreSQL prod)
├── requirements.txt
└── app/
    ├── __init__.py        # application factory
    ├── extensions.py      # db, login_manager, csrf (avoids circular imports)
    ├── models.py           # full relational schema (users, listings, transactions, etc.)
    ├── forms.py            # Flask-WTF forms (CSRF-protected)
    ├── utils.py            # shared helpers (uploads, fees, notifications)
    ├── seed.py / cli.py    # categories and badges + `flask` CLI commands
    ├── auth/               # register, login, password reset
    ├── main/               # landing, dashboard, profile, wishlist, notifications, impact
    ├── marketplace/        # browse, listing detail, sell/edit, price guide
    ├── transactions/       # checkout, payments, donations, swaps, reviews, disputes
    ├── messaging/          # conversations
    ├── admin/              # moderation, verification, settings, analytics
    ├── static/css/style.css  # neumorphic design system
    └── templates/          # Jinja2, extends base.html
```

## Security notes

- Passwords hashed with Werkzeug (`generate_password_hash`); never stored in
  plaintext.
- CSRF protection on every form via Flask-WTF.
- All server-rendered price/fee calculations — never trusted from the client.
- Card numbers/CVVs are never written to the database.
- File uploads are re-named with a random UUID and restricted to image
  extensions.
- Role-based access (`admin_required` decorator) protects `/admin/*`.

## What is still simulated

Only the payment gateway. Checkout uses the sandbox gateway, so no real money moves
and the "Demo payments" banner stays until a real provider is connected (see
`docs/GO_LIVE.md`). Everything else is real: accounts, listings, chats, offers,
receipts and emails (email needs the SMTP settings in `docs/GO_LIVE.md`).

## Settings area (version 1.1.0)

Settings are at `/settings` (account menu, then Settings). Each setting is stored
in the database and takes effect in the app.

| Section | What it does |
|---|---|
| Account | Username, phone number, email change (confirmed by a link sent to the new address), password change, two-step verification (authenticator app and recovery codes), security notifications, log out. |
| Privacy | Profile public or private, and an optional About text. |
| Lists | Which of your lists (for sale, swap, donations) comes first on My Listings and your profile. |
| Chats | Download a backup of your chats as text or JSON. |
| Appearance | Light, Dark, Blue and Velvet. The logo badge changes with the mode. |
| Storage and data | What you have uploaded, and clearing saved data on this device. Photos are never resized or altered. |
| Accessibility | Increase contrast (Light mode) and turn animation off. |
| Help and feedback | Help centre, contact us, send feedback, report a technical issue (stored, emailed, and listed for admins at `/admin/feedback`), legal pages, app info. |
| Invite a friend | A personal invite link, with a count of students who joined through it. |
| App updates | Current version and release notes (edit `app/releases.py` and `APP_VERSION` in `config.py` for each release). |
| Delete account | Anonymises the account, takes down listings. Blocked while a transaction or dispute is open. |

Not built yet, shown as "Coming soon" or left out: notifications settings,
parental control, live location, voice notes, chat transfer, passkeys, adding a
second account, and blocking access 14 days after a new version.

### Upgrading an existing database

Run these once after copying the new code, and before opening the site:

```bash
flask --app run.py upgrade-db
```

It adds the new columns and tables and never deletes or changes existing data.
Without it, logins fail because the users table is missing the new columns.

### Tests

```bash
python tests/test_settings_logic.py
```


## Receipts and chat offers (version 1.3.0)

- **Offers in chat** now have an Accept, Decline and Withdraw step. Only the other
  person can accept or decline, and only an offer that is lower than the listed
  price is allowed. A new offer replaces your earlier one that is still waiting.
- **Where the price comes from.** When a purchase starts, the server uses the newest
  accepted offer between that buyer and the seller if it is still valid
  (`OFFER_VALID_HOURS` in `config.py`, default 48 hours from the moment it was
  accepted). Otherwise it uses the listing price. The browser never sends a price.
- **Receipts** say "Price from: Listing", or "Price from: Chat offer, accepted
  <date and time>" together with the listed price, the agreed price and the
  difference. These are saved on the transaction, so a receipt never changes
  later, even if the listing is edited or the chat is deleted.
- Accepting an offer replaces any other waiting or accepted offer in that chat, so there is only ever one agreed price. An accepted offer can only be paid for once.
- After copying the new code, run `flask --app run.py upgrade-db` again. It adds
  the new columns without touching existing data. Older receipts show
  "Price from: Listing".
- Test: `python tests/test_pricing_rules.py`


## Version 2.0: security, under-18 accounts and cleaner flows

**Safe by default.** With no `FLASK_ENV` set the app starts as the live site and refuses to run
without a strong `SECRET_KEY` (32+ characters). Local work needs `FLASK_ENV=development`. The Flask
debugger is only ever on for the local address 127.0.0.1.

**Accounts and sign-in**
- Email must be confirmed before anyone can sign in (a link is emailed). Sign-ups close if email
  sending is not set up on a live site.
- 5 wrong passwords in 15 minutes locks sign-in for that account (and 30 per network address);
  wrong two-step codes, password resets, sign-ups and Settings password checks have limits too.
  Counts are stored as one-way hashes. The account owner is emailed when a lock starts.
- Passwords: at least 10 characters, and common ones ("Password123!") are refused.
- Reset, verification, guardian and sign-in tokens are stored only as hashes. A password change or
  reset signs the account out on every other device.
- Administrators must turn on two-step verification before using `/admin`. Admin actions are logged.
- Logout is a protected POST. Sign-in activity is listed in Settings > Account.

**Under 18**
- Date of birth at sign-up decides the side: learner (under 18) or adult. The sides never see,
  message or trade with each other. This is enforced on the server in `app/sides.py`.
- A learner's account stays locked until a parent or guardian confirms by email. The parent portal
  (`/parent/sign-in`, one-time email link, no password) lets them read chats, listings and
  purchases, pause the account, allow buying and selling (off by default), or close the account.
- Learners: private profile, no phone number, no profile photo, swap and donate only unless a
  guardian allows paid trades. They are told their guardian can read their chats.
- Accounts without a date of birth (from before this version) are asked for one at next sign-in.
  Only an administrator can correct a date of birth afterwards (Admin > Users).

**Flows that were incomplete and now work:** a Requests page (`/transactions/requests`) lets owners
accept or decline donation requests and swap offers; swap top-ups can now be paid; only one buyer can
reserve an item; payment needs the item still held for that buyer; only the buyer confirms a hand-over;
a price changed mid-checkout is never charged silently.

**Checks you can run any time (no database needed)**
```bash
python tools/audit.py              # links, forms, CSRF, risky code
python tools/static_check.py       # undefined names, unknown fields, broken imports
python tests/test_security_rules.py
python tests/test_pricing_rules.py
python tests/test_settings_logic.py
python -m unittest tests.test_app_flows -v     # needs the real libraries; run it once locally
```

**Upgrade an existing database** (after copying the new files, before opening the site):
`flask --app run.py upgrade-db`. People who already have accounts keep working: their email counts
as confirmed, and they are asked for a date of birth. Everyone is signed out once.
