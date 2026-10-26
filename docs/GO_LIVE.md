# Campus Swap: go-live guide

Everything below is controlled by environment settings, so you change a few
lines in one file on the server and never edit code for these.

## 1. Where the settings go (PythonAnywhere free plan)

Open the WSGI file from the Web tab. Add the lines you need **above**
`from run import app as application`:

```python
import os

os.environ['SECRET_KEY'] = 'your-long-random-string'
os.environ['FLASK_ENV'] = 'production'

# Business details (shown in the footer and legal pages)
os.environ['BUSINESS_NAME'] = 'Your registered name, or your own name if trading as an individual'
os.environ['BUSINESS_REG_NUMBER'] = 'Registration number, or "Not a registered company"'
os.environ['BUSINESS_ADDRESS'] = 'Street, suburb, city, postal code'
os.environ['SUPPORT_EMAIL'] = 'support@yourdomain.co.za'
os.environ['LEGAL_LAST_UPDATED'] = '1 November 2026'

# Optional: only these email domains may register, e.g. your campus
os.environ['ALLOWED_SCHOOL_EMAIL_DOMAINS'] = '@uj.ac.za,@wits.ac.za'
```

Save, then press **Reload** on the Web tab. This file lives on the server, not
in GitHub, so these values are never published.

Until a value is set, a visible `[INSERT ...]` placeholder is shown on the
site. That is deliberate, so unfinished details are never mistaken for real
ones.

## 2. Password-reset emails

Without this, nobody on the live site can reset a forgotten password.

**Option A: Gmail (free)**
1. Use a Gmail account for the app. Turn on 2-step verification.
2. In your Google account, create an **App password** (Security, then App passwords).
3. Add to the WSGI file:

```python
os.environ['MAIL_PROVIDER'] = 'smtp'
os.environ['MAIL_SMTP_USER'] = 'yourapp@gmail.com'
os.environ['MAIL_SMTP_PASSWORD'] = 'the-16-character-app-password'
os.environ['MAIL_FROM'] = 'yourapp@gmail.com'
```

**Option B: SendGrid (HTTPS API)**
```python
os.environ['MAIL_PROVIDER'] = 'sendgrid'
os.environ['SENDGRID_API_KEY'] = 'SG.xxxxx'
os.environ['MAIL_FROM'] = 'a-sender-you-verified-in-sendgrid@yourdomain.co.za'
```

Reload, then use "Forgot password" with a real address to test.

## 3. Clear the demo data (once, before real students sign up)

In a PythonAnywhere Bash console:

```
cd ~/campus-swap
workon campusswap-env
export FLASK_APP=run.py
flask clear-demo-data
```

It asks for confirmation, then removes only the four seeded demo students and
everything attached to them. Your admin account, categories and badges stay.

## 4. Change the admin password

```
flask reset-password --email admin@campusswap.app
```

The password is typed at a hidden prompt, so it never appears on screen or in
your command history.

## 5. Payments: what changes when you go live

The site shows a "Demo payments" bar while `PAYMENT_GATEWAY` is `sandbox`.
When a real gateway is connected, that bar disappears automatically.

Steps, in order:
1. Open a merchant account with a South African provider and get **test**
   (sandbox) credentials first.
2. Free PythonAnywhere accounts can only call approved sites. Ask PythonAnywhere
   support to allowlist the provider's API domain, or move to a paid plan.
3. Add the provider's class to `app/transactions/payment_gateway.py` and
   register it in `GATEWAYS`. Real providers use a hosted checkout page and
   confirm payment through a webhook, so the card fields on the checkout page
   are removed at that point and card details never reach this server.
4. Set `PAYMENT_GATEWAY` to the provider's name.
5. Run test payments end to end, including a refund.
6. Re-read the Refund Policy and make sure it matches what the provider
   actually does (settlement times, who can refund, fees).

## 6. Before real students use it

- Fill in every business detail above.
- Have a South African attorney read the Terms, Privacy Policy and Refund
  Policy. They are a drafted starting point, not legal advice.
- If you are operating as an individual and not a registered company, edit the
  wording in Terms section 1 ("a company registered in South Africa") so it is
  accurate.
- Register your Information Officer with the Information Regulator (POPIA requires
  this for organisations that process personal information). Check the current process on the Regulator's website.


## Settings (version 1.1.0 and later)

1. Run `flask --app run.py upgrade-db` once (see the README). It never deletes data.
2. Optional: `os.environ['BUSINESS_PHONE'] = '0817370210'` shows your phone in the footer and Help.
3. Changing an email address needs email sending (section 2 above). Without it,
   the email field refuses the change and says why.


## Version 2.0 settings for the live site

Set these in your web server's environment (on PythonAnywhere, in the WSGI file before the app is imported):

```python
os.environ['FLASK_ENV'] = 'production'
os.environ['SECRET_KEY'] = '<a long random string, 32+ characters, kept secret>'
# PythonAnywhere sits behind one proxy, which is what the sign-in limits assume (the default in production):
os.environ['TRUSTED_PROXIES'] = '1'
```

- Email must work (SMTP settings above). Without it nobody can sign up, because every address has to be confirmed.
- Create the first administrator with `flask --app run.py create-admin --email you@example.com` (the password is asked for
  at a hidden prompt), sign in, and turn on two-step verification when asked.
- `CSP_MODE` can be `enforce` (default), `report-only` or `off` if the browser security policy ever blocks something you add.
- Bootstrap and the icons still load from the jsDelivr CDN (the security policy allows it). Self-hosting them is a good next step.
- Have an attorney review the Terms, Privacy Policy and the parent confirmation wording before launch: they now cover under-18s
  (POPIA rules on children's information), parent monitoring, and storing a date of birth.
