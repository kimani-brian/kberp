"""QWeb-style quotation report, rendered from one template on every path."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .pricing import tax_lines

TEMPLATES = Path(__file__).resolve().parents[3] / "web" / "templates"
_engine = Environment(
    loader=FileSystemLoader(str(TEMPLATES)),
    autoescape=select_autoescape(["html"]),
)


def quotation_html(env, order_id: int) -> str:
    """Render the printable quotation for a saved order."""
    rows = env["sales.order"].read([order_id])
    if not rows:
        raise ValueError("quotation not found")
    order = rows[0]
    company_id = (order.get("company_id") or {}).get("id")
    company = (
        env["core.company"].read([int(company_id)])[0]
        if company_id
        else {"name": "KB ERP Ltd", "vat": ""}
    )
    return _engine.get_template("report_quotation.html").render(
        order=order,
        company=company,
        tax_lines=tax_lines(env, order),
    )
