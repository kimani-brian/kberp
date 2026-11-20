"""Development mail transport: write a deterministic email into a local drop.

Swapping this for SMTP is a transport change; the rendered HTML and the
attachment contract stay the same. Messages are named by order number so
re-sending a quotation overwrites the previous copy rather than piling up.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Any


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-") or "message"


def send_report(
    mail_dir: Path,
    *,
    recipient: str,
    subject: str,
    body: str,
    attachment_name: str,
    attachment_html: str,
    metadata: dict[str, Any] | None = None,
) -> Path:
    """Deliver a report to the local mail drop and return its path."""
    directory = Path(mail_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%d-%H%M%S")
    path = directory / f"{stamp}-{_safe(attachment_name)}.json"
    payload = {
        "to": recipient,
        "subject": subject,
        "body": body,
        "attachment": {"name": attachment_name, "content_type": "text/html", "html": attachment_html},
        "metadata": metadata or {},
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path
