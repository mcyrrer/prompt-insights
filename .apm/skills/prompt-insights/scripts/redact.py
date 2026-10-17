"""Shared redaction helpers.

Redaction runs in code, before any text reaches the model or the HTML report.
It is deliberately aggressive: over-redacting a quote is cheap, leaking a token is not.
"""
from __future__ import annotations

import os
import re

HOME = os.path.expanduser("~")

_RULES = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)", re.S), "<private-key>"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "<aws-key>"),
    (re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b"), "<github-token>"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"), "<github-token>"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}\b"), "<api-key>"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}\b"), "<slack-token>"),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b"), "<jwt>"),
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=\-]{12,}"), r"\1 <token>"),
    (re.compile(
        r"(?i)\b([a-z0-9_\-]*(?:password|passwd|secret|token|api[_-]?key|access[_-]?key|"
        r"client[_-]?secret|authorization)[a-z0-9_\-]*)\s*([:=])\s*[\"']?[^\s\"',;]{4,}"),
     r"\1\2<redacted>"),
    (re.compile(r"\b[a-z][a-z0-9+.\-]*://[^\s/@:]+:[^\s/@]+@"), "<scheme>://<creds>@"),
    (re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"), "<email>"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "<ip>"),
    (re.compile(r"\b[A-Fa-f0-9]{32,}\b"), "<hex>"),
]

_BLOB = re.compile(r"[A-Za-z0-9+/_\-]{40,}={0,2}")


def _blob_sub(m: re.Match) -> str:
    s = m.group(0)
    if s.count("/") >= 2:  # looks like a path, keep it readable
        return s
    if re.search(r"\d", s) and re.search(r"[A-Za-z]", s):
        return "<blob>"
    return s


def compile_extra(patterns):
    """Compile user-supplied extra regexes (e.g. internal hostnames, customer names)."""
    return [re.compile(p) for p in (patterns or [])]


def tilde(text: str) -> str:
    if not text:
        return text
    return text.replace(HOME, "~") if HOME and HOME != "/" else text


def redact(text, extra=None):
    if not text:
        return text
    t = tilde(str(text))
    for rx, rep in _RULES:
        t = rx.sub(rep, t)
    t = _BLOB.sub(_blob_sub, t)
    for rx in extra or []:
        t = rx.sub("<redacted>", t)
    return t


def truncate(text, n: int = 200) -> str:
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    return t if len(t) <= n else t[: n - 1] + "…"
