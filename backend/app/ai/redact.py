"""Reversible redaction applied before any call to an external (cloud) model."""
from __future__ import annotations

import re
from typing import Any

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# International (+…) or national trunk-prefixed (0…) numbers; deliberately does not match ISO dates.
PHONE = re.compile(r"(?<![\w-])(?:\+\d[\d\s]{7,15}\d|0\d{8,11})(?![\w-])")
IBAN = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")
NATIONAL_ID = re.compile(r"\b\d{10,15}\b")


class Redactor:
    def __init__(self, sensitive_terms: list[str] | None = None):
        self.forward: dict[str, str] = {}
        self.reverse: dict[str, str] = {}
        self.counters: dict[str, int] = {}
        terms = sorted({t.strip() for t in (sensitive_terms or []) if t and len(t.strip()) >= 3}, key=len, reverse=True)
        self.term_patterns = [(t, re.compile(r"(?<!\w)" + re.escape(t) + r"(?!\w)", re.IGNORECASE)) for t in terms]

    def _token(self, kind: str, value: str) -> str:
        key = value.lower()
        if key in self.forward:
            return self.forward[key]
        self.counters[kind] = self.counters.get(kind, 0) + 1
        tok = f"[{kind}_{self.counters[kind]}]"
        self.forward[key] = tok
        self.reverse[tok] = value
        return tok

    def redact_text(self, text: str) -> str:
        for term, pat in self.term_patterns:
            text = pat.sub(lambda m, t=term: self._token("PERSON", t), text)
        text = EMAIL.sub(lambda m: self._token("EMAIL", m.group(0)), text)
        text = IBAN.sub(lambda m: self._token("ACCOUNT", m.group(0)), text)
        text = PHONE.sub(lambda m: self._token("PHONE", m.group(0)), text)
        text = NATIONAL_ID.sub(lambda m: self._token("ID", m.group(0)), text)
        return text

    def restore(self, obj: Any) -> Any:
        if isinstance(obj, str):
            for tok, val in self.reverse.items():
                obj = obj.replace(tok, val)
            return obj
        if isinstance(obj, list):
            return [self.restore(x) for x in obj]
        if isinstance(obj, dict):
            return {k: self.restore(v) for k, v in obj.items()}
        return obj

    @property
    def count(self) -> int:
        return len(self.reverse)
