"""
Browser security headers and the Content-Security-Policy.

The policy lists exactly where scripts, styles, images and fonts may come from.
Inline scripts need a fresh random nonce on every page, so an attacker who
manages to inject markup cannot run their own script.
"""

import secrets

from flask import g, request, current_app

CDN = "https://cdn.jsdelivr.net"


def build_csp(nonce):
    """The policy as one header value."""
    return "; ".join([
        "default-src 'self'",
        f"script-src 'self' 'nonce-{nonce}' {CDN}",
        "script-src-attr 'none'",                 # no onclick="..." style handlers anywhere
        f"style-src 'self' 'unsafe-inline' {CDN}",  # style="" attributes are used across the pages
        "img-src 'self' data: blob:",
        f"font-src 'self' data: {CDN}",
        "connect-src 'self'",
        "manifest-src 'self'",
        "worker-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ])


def init_security_headers(app):
    @app.before_request
    def make_nonce():
        g.csp_nonce = secrets.token_urlsafe(18)

    @app.context_processor
    def expose_nonce():
        return {"csp_nonce": getattr(g, "csp_nonce", "")}

    @app.after_request
    def add_headers(response):
        h = response.headers
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        h.setdefault("Permissions-Policy",
                     "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()")
        h.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        if request.is_secure and not current_app.debug:
            h.setdefault("Strict-Transport-Security", "max-age=31536000")
        if response.mimetype == "text/html":
            # Pages hold personal information: never keep them in a shared cache or
            # let the Back button show them again after sign-out.
            h["Cache-Control"] = "no-store, max-age=0"
        mode = current_app.config.get("CSP_MODE", "enforce")
        if mode != "off" and getattr(g, "csp_nonce", None):
            name = "Content-Security-Policy-Report-Only" if mode == "report-only" else "Content-Security-Policy"
            h[name] = build_csp(g.csp_nonce)
        return response
