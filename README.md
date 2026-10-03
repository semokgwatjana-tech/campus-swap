# Campus Swap 🎓

A trusted student economy platform — **buy, sell, swap, and donate** educational
resources within your campus. Built with Python (Flask), SQLAlchemy, and a
custom **neumorphic** design system (soft shadows, rounded corners, calm
green/white/navy palette).

## Quick Start

```bash
# 1. Create a virtual environment
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set up the database
export FLASK_APP=run.py         # Windows: set FLASK_APP=run.py
flask init-db
flask seed-db                   # optional: demo categories, users & listings
flask create-admin --email admin@campusswap.app --password ChangeMe123

# 4. Run it
python run.py
# → http://localhost:5000
```

Demo accounts created by `flask seed-db` all use the password `password123`
(e.g. `sarah.mokoena@campusswap.app`).

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
| AI feature placeholders (price suggestion, listing generator, smart search) | ✅ stubbed, provider-agnostic |
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
    ├── seed.py / cli.py    # demo data + `flask` CLI commands
    ├── auth/               # register, login, password reset
    ├── main/               # landing, dashboard, profile, wishlist, notifications, impact
    ├── marketplace/        # browse, listing detail, sell/edit, AI placeholders
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

## What's a placeholder (by design, per spec)

- **AI features** (`app/marketplace/ai_features.py`) use lightweight
  heuristics today so every button is fully wired up end-to-end. Swap in a
  real AI/vision API by editing just that file.
- **Email** is not wired to a real SMTP/verification provider; password
  reset links are shown directly in a flash message for demo purposes
  (clearly labeled "Demo mode").
- **Payment provider** is the sandbox gateway described above — safe by
  design until real credentials are added.
