"""
Campus Swap - Payment Gateway Abstraction
------------------------------------------
This module is the ONLY place that talks to "the payment provider". Today
it is a safe sandbox simulation (no real money moves and no card data is
ever persisted). To go live, implement a new class with the same
`charge()` / `verify_webhook()` interface for a real South African gateway
(e.g. Yoco, PayFast, Ozow/PayShap) and swap it in via `get_gateway()`
without touching any route code.

SECURITY NOTES
--------------
* Card numbers / CVVs are NEVER written to the database - only the last 4
  digits are kept, purely for the on-screen receipt.
* All amount calculations happen server-side (see utils.calculate_service_fee
  and transactions/routes.py) - the client cannot influence the charged
  amount.
* Every successful charge returns a unique gateway reference which is
  stored against the Transaction row, mirroring how a real provider's
  webhook confirmation would work.
"""

import random
import string
import time
from dataclasses import dataclass


class PaymentError(Exception):
    """Raised when the (sandbox) provider declines or fails a payment."""


@dataclass
class ChargeResult:
    success: bool
    gateway_reference: str
    message: str


class BasePaymentGateway:
    def charge(self, amount, method, payment_details=None):
        raise NotImplementedError

    def verify_webhook(self, payload, signature):
        raise NotImplementedError


class SandboxPaymentGateway(BasePaymentGateway):
    """
    Deterministic-but-fake gateway used for the prototype/demo.

    Simulates realistic latency and a small number of test scenarios so the
    UI's PAYMENT_PROCESSING / PAID / PAYMENT_FAILED states can all be
    demonstrated safely:

      * Card ending in 0000 -> simulated decline (PAYMENT_FAILED)
      * Any other card / EFT / Instant EFT -> simulated success (PAID)

    No real card numbers, CVVs, or bank credentials are ever stored -
    `payment_details` is used only in-memory to pick a demo outcome and is
    discarded immediately after this function returns.
    """

    def charge(self, amount, method, payment_details=None):
        if amount < 0:
            raise PaymentError("Invalid amount.")

        # Simulate network latency to a real payment provider
        time.sleep(0.4)

        payment_details = payment_details or {}
        card_number = (payment_details.get("card_number") or "").replace(" ", "")

        # Demo-only decline scenario so PAYMENT_FAILED is reachable in a
        # walkthrough without needing a real bank sandbox.
        if card_number.endswith("0000") and len(card_number) >= 4:
            return ChargeResult(
                success=False,
                gateway_reference=self._reference(),
                message="Card declined by issuing bank (demo decline scenario).",
            )

        return ChargeResult(
            success=True,
            gateway_reference=self._reference(),
            message="Payment approved.",
        )

    def verify_webhook(self, payload, signature):
        # In a real integration this would validate an HMAC signature from
        # the provider before trusting the payload. The sandbox always
        # verifies true because there is no external provider calling back.
        return True

    @staticmethod
    def _reference():
        suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=10))
        return f"SANDBOX-{suffix}"


def get_gateway():
    """Factory so routes never instantiate a gateway class directly - makes
    swapping in a real provider later a one-line change."""
    return SandboxPaymentGateway()


def mask_card_number(card_number):
    """Only the last 4 digits should ever be shown or logged."""
    digits = (card_number or "").replace(" ", "")
    if len(digits) < 4:
        return "****"
    return f"**** **** **** {digits[-4:]}"
