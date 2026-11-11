"""PII masking for logs, traces and the audit log: emails, phone numbers, payment details, tokens."""

from __future__ import annotations

import re
from typing import Any

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE = re.compile(r"(?<!\d)(?:\+?\d[\d\s().-]{7,}\d)(?!\d)")
CARD = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
IBAN = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")
TOKEN = re.compile(r"\b(?:gsk_|sk-|lsv2_|ghp_|github_pat_|xox[bp]-|Bearer\s+)[A-Za-z0-9_\-.]{8,}")
HANDLE = re.compile(r"(?i)\b(?:whatsapp|telegram|signal|skype)\s*[:@]?\s*[+\w.@-]{4,}")

_RULES = [
    (TOKEN, "[TOKEN]"),
    (EMAIL, "[EMAIL]"),
    (IBAN, "[IBAN]"),
    (CARD, "[CARD]"),
    (PHONE, "[PHONE]"),
    (HANDLE, "[CONTACT]"),
]


def mask_pii(text: str) -> str:
    if not text:
        return text
    for pattern, repl in _RULES:
        text = pattern.sub(repl, text)
    return text


def mask_pii_in(obj: Any) -> Any:
    if isinstance(obj, str):
        return mask_pii(obj)
    if isinstance(obj, dict):
        return {k: ("[REDACTED]" if _secret_key(k) else mask_pii_in(v)) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [mask_pii_in(v) for v in obj]
    return obj


def _secret_key(k: str) -> bool:
    k = k.lower()
    return any(
        s in k
        for s in (
            "password",
            "secret",
            "api_key",
            "apikey",
            "access_token",
            "refresh_token",
            "authorization",
        )
    )


def contains_contact_details(text: str) -> list[str]:
    """Which PII kinds appear in text (for the Compliance Guard)."""
    found = []
    if EMAIL.search(text):
        found.append("email")
    if PHONE.search(text):
        found.append("phone")
    if HANDLE.search(text):
        found.append("messaging_handle")
    if CARD.search(text) or IBAN.search(text):
        found.append("payment_details")
    return found
