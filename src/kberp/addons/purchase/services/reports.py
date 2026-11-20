"""Printable purchase order, rendered from one template."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATES = Path(__file__).resolve().parents[3] / "web" / "templates"
_engine = Environment(
    loader=FileSystemLoader(str(TEMPLATES)),
    autoescape=select_autoescape(["html"]),
)


def purchase_html(env, order_id: int) -> str:
    rows = env["purchase.order"].read([order_id])
    if not rows:
        raise ValueError("purchase order not found")
    order = rows[0]
    vendor = env["core.partner"].read([order["partner_id"]["id"]])[0]
    company_id = (order.get("company_id") or {}).get("id")
    company = (
        env["core.company"].read([int(company_id)])[0]
        if company_id
        else {"name": "KB ERP Ltd"}
    )
    return _engine.get_template("report_purchase.html").render(
        order=order, vendor=vendor, company=company
    )
