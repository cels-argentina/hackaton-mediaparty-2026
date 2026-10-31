"""Minimización de datos: redacción de PII antes de persistir texto."""
from __future__ import annotations
import re

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"(?<!\d)(?:\+?54\s?9?\s?)?(?:\(?\d{2,4}\)?[\s-]?)?\d{3,4}[\s-]?\d{4}(?!\d)")
_DNI = re.compile(r"\b\d{1,2}\.?\d{3}\.?\d{3}\b")


def redact_pii(text: str) -> str:
    """Oculta emails, teléfonos y DNI. No es exhaustivo: no reemplaza una revisión humana."""
    for pattern, label in ((_EMAIL, "[email]"), (_DNI, "[dni]"), (_PHONE, "[tel]")):
        text = pattern.sub(label, text)
    return text
