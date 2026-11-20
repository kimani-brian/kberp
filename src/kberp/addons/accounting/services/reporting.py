"""Statement, ledger, tax and review reports for A3."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from ....env import Env
from ....orm.model import ValidationError

EPS = Decimal("0.0001")
ASSET_TYPES = {"asset", "bank", "receivable"}
LIABILITY_TYPES = {"liability", "payable"}


def _number(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal(0)
    return Decimal(str(value))


def _id(value: Any) -> int | None:
    if not value:
        return None
    return value["id"] if isinstance(value, dict) else int(value)


def _posted_lines(
    env: Env, date_from: dt.date, date_to: dt.date
) -> list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]]:
    move_ids = env["accounting.move"].search(
        [("state", "=", "posted"), ("date", ">=", date_from), ("date", "<=", date_to)]
    )
    if not move_ids:
        return []
    moves = {row["id"]: row for row in env["accounting.move"].read(move_ids)}
    line_ids = env["accounting.move_line"].search([("move_id", "in", list(moves))])
    lines = env["accounting.move_line"].read(line_ids)
    account_ids = {_id(line.get("account_id")) for line in lines}
    accounts = {
        row["id"]: row
        for row in env["accounting.account"].read(
            [account_id for account_id in account_ids if account_id]
        )
    }
    result = []
    for line in lines:
        move = moves.get(_id(line.get("move_id")))
        account = accounts.get(_id(line.get("account_id")))
        if move and account:
            result.append((move, line, account))
    return result


def _balances(
    env: Env, date_from: dt.date, date_to: dt.date
) -> tuple[dict[str, Decimal], dict[str, Decimal]]:
    by_type: dict[str, Decimal] = {}
    by_account: dict[str, Decimal] = {}
    for _move, line, account in _posted_lines(env, date_from, date_to):
        delta = _number(line["debit"]) - _number(line["credit"])
        by_type[account["type"]] = by_type.get(account["type"], Decimal(0)) + delta
        key = f"{account['code']} {account['name']}"
        by_account[key] = by_account.get(key, Decimal(0)) + delta
    return by_type, by_account


def _clear(env: Env, report: dict[str, Any]) -> None:
    ids = [row["id"] for row in report.get("line_ids", [])]
    if ids:
        env["accounting.report_line"].unlink(ids)


def _add(
    env: Env,
    report_id: int,
    sequence: int,
    label: str,
    amount: Decimal | float,
    *,
    level: int = 1,
    style: str = "line",
) -> None:
    env["accounting.report_line"].create(
        {
            "report_id": report_id,
            "sequence": sequence,
            "label": label,
            "amount": amount,
            "level": level,
            "style": style,
        }
    )


def _balance_sheet(env: Env, report: dict[str, Any]) -> list[tuple[str, Decimal, int, str]]:
    by_type, by_account = _balances(env, report["date_from"], report["date_to"])
    rows: list[tuple[str, Decimal, int, str]] = []
    assets = sum((by_type.get(kind, Decimal(0)) for kind in ASSET_TYPES), Decimal(0))
    liabilities = -sum(
        (by_type.get(kind, Decimal(0)) for kind in LIABILITY_TYPES), Decimal(0)
    )
    equity = -by_type.get("equity", Decimal(0))
    income = -by_type.get("income", Decimal(0))
    expenses = by_type.get("expense", Decimal(0))
    profit = income - expenses
    rows.append(("Assets", assets, 1, "section"))
    for name, balance in sorted(by_account.items()):
        if balance != 0 and name.split()[0] and _account_type(env, name) in ASSET_TYPES:
            rows.append((name, balance, 2, "line"))
    rows.append(("Total assets", assets, 1, "total"))
    rows.append(("Liabilities", liabilities, 1, "section"))
    for name, balance in sorted(by_account.items()):
        if _account_type(env, name) in LIABILITY_TYPES and balance != 0:
            rows.append((name, -balance, 2, "line"))
    rows.append(("Total liabilities", liabilities, 1, "total"))
    rows.append(("Equity", equity, 1, "section"))
    for name, balance in sorted(by_account.items()):
        if _account_type(env, name) == "equity" and balance != 0:
            rows.append((name, -balance, 2, "line"))
    rows.append(("Current profit", profit, 2, "line"))
    rows.append(("Total equity", equity + profit, 1, "total"))
    rows.append(("Total liabilities and equity", liabilities + equity + profit, 1, "total"))
    return rows


def _account_type(env: Env, account_label: str) -> str:
    code = account_label.split(" ", 1)[0]
    ids = env["accounting.account"].search([("code", "=", code)], limit=1)
    return env["accounting.account"].read([ids[0]])[0]["type"] if ids else ""


def _profit_and_loss(env: Env, report: dict[str, Any]) -> list[tuple[str, Decimal, int, str]]:
    by_type, by_account = _balances(env, report["date_from"], report["date_to"])
    income = -by_type.get("income", Decimal(0))
    expenses = by_type.get("expense", Decimal(0))
    rows: list[tuple[str, Decimal, int, str]] = [("Income", income, 1, "section")]
    for name, balance in sorted(by_account.items()):
        if _account_type(env, name) == "income" and balance != 0:
            rows.append((name, -balance, 2, "line"))
    rows.append(("Total income", income, 1, "total"))
    rows.append(("Expenses", expenses, 1, "section"))
    for name, balance in sorted(by_account.items()):
        if _account_type(env, name) == "expense" and balance != 0:
            rows.append((name, balance, 2, "line"))
    rows.append(("Total expenses", expenses, 1, "total"))
    rows.append(("Net profit", income - expenses, 1, "total"))
    return rows


def _cash_flow(env: Env, report: dict[str, Any]) -> list[tuple[str, Decimal, int, str]]:
    by_type, _ = _balances(env, report["date_from"], report["date_to"])
    cash = by_type.get("bank", Decimal(0)) + by_type.get("asset", Decimal(0))
    income = -by_type.get("income", Decimal(0))
    expenses = by_type.get("expense", Decimal(0))
    rows = [
        ("Operating activities", income - expenses, 1, "section"),
        ("Net profit", income - expenses, 2, "line"),
        ("Investing activities", Decimal(0), 1, "section"),
        ("Financing activities", Decimal(0), 1, "section"),
        ("Net change in cash", cash, 1, "total"),
    ]
    return rows


def _trial_balance(env: Env, report: dict[str, Any]) -> list[tuple[str, Decimal, int, str]]:
    _by_type, by_account = _balances(env, report["date_from"], report["date_to"])
    rows = [("Account", Decimal(0), 1, "section")]
    total = Decimal(0)
    for name, balance in sorted(by_account.items()):
        rows.append((name, balance, 2, "line"))
        total += balance
    rows.append(("Total", total, 1, "total"))
    return rows


def _general_ledger(env: Env, report: dict[str, Any]) -> list[tuple[str, Decimal, int, str]]:
    rows: list[tuple[str, Decimal, int, str]] = []
    for index, (move, line, account) in enumerate(
        _posted_lines(env, report["date_from"], report["date_to"])[:500]
    ):
        delta = _number(line["debit"]) - _number(line["credit"])
        rows.append(
            (
                f"{move['date']} {move.get('name') or move['id']} · {account['name']} · {line.get('name') or ''}",
                delta,
                1,
                "line",
            )
        )
    if not rows:
        rows.append(("No posted journal items in this period", Decimal(0), 1, "line"))
    return rows


def _partner_lines(env: Env, report: dict[str, Any]) -> list[tuple[str, Decimal, int, str]]:
    totals: dict[str, Decimal] = {}
    for _move, line, account in _posted_lines(env, report["date_from"], report["date_to"]):
        if account["type"] not in ASSET_TYPES | LIABILITY_TYPES:
            continue
        partner = line.get("partner_id") or {}
        name = partner.get("name") if isinstance(partner, dict) else None
        if not name:
            continue
        totals[name] = totals.get(name, Decimal(0)) + _number(line["debit"]) - _number(
            line["credit"]
        )
    rows = [("Partner", Decimal(0), 1, "section")]
    total = Decimal(0)
    for name, balance in sorted(totals.items()):
        rows.append((name, balance, 2, "line"))
        total += balance
    rows.append(("Total", total, 1, "total"))
    return rows


def _aged(env: Env, report: dict[str, Any], move_type: str) -> list[tuple[str, Decimal, int, str]]:
    ids = env["accounting.move"].search(
        [("move_type", "=", move_type), ("state", "=", "posted"), ("amount_residual", ">", 0)]
    )
    buckets: dict[str, Decimal] = {}
    for invoice in env["accounting.move"].read(ids):
        due = invoice.get("due_date") or invoice["date"]
        days = (report["date_to"] - due).days
        if days <= 0:
            bucket = "Current"
        elif days <= 30:
            bucket = "1–30 days"
        elif days <= 60:
            bucket = "31–60 days"
        elif days <= 90:
            bucket = "61–90 days"
        else:
            bucket = "Over 90 days"
        partner = (invoice.get("partner_id") or {}).get("name") or "No partner"
        key = f"{partner} · {bucket}"
        buckets[key] = buckets.get(key, Decimal(0)) + _number(invoice["amount_residual"])
    rows = [("Partner and bucket", Decimal(0), 1, "section")]
    total = Decimal(0)
    for name, amount in sorted(buckets.items()):
        rows.append((name, amount, 2, "line"))
        total += amount
    rows.append(("Total", total, 1, "total"))
    return rows


def _tax_report(env: Env, report: dict[str, Any], by_group: bool = False) -> list[tuple[str, Decimal, int, str]]:
    totals: dict[str, Decimal] = {}
    for move, line, _account in _posted_lines(env, report["date_from"], report["date_to"]):
        if line.get("kind") != "tax":
            continue
        tax = line.get("tax_id") or {}
        if by_group:
            tax_id = _id(tax)
            tax_rows = env["accounting.tax"].read([tax_id]) if tax_id else []
            group = (tax_rows[0].get("group_id") or {}) if tax_rows else {}
            label = group.get("name") or "Ungrouped tax"
        else:
            label = (tax.get("name") if isinstance(tax, dict) else None) or line.get("name")
        direction = Decimal(-1) if move["move_type"] in ("in_invoice", "in_refund") else Decimal(1)
        totals[label] = totals.get(label, Decimal(0)) + direction * (
            _number(line["credit"]) - _number(line["debit"])
        )
    rows = [("Tax", Decimal(0), 1, "section")]
    total = Decimal(0)
    for name, amount in sorted(totals.items()):
        rows.append((name, amount, 2, "line"))
        total += amount
    rows.append(("Total tax due", total, 1, "total"))
    return rows


def _invoice_analysis(env: Env, report: dict[str, Any]) -> list[tuple[str, Decimal, int, str]]:
    totals: dict[str, Decimal] = {}
    ids = env["accounting.move"].search(
        [
            ("state", "=", "posted"),
            ("move_type", "in", ["out_invoice", "in_invoice", "out_refund", "in_refund"]),
            ("date", ">=", report["date_from"]),
            ("date", "<=", report["date_to"]),
        ]
    )
    for invoice in env["accounting.move"].read(ids):
        partner = (invoice.get("partner_id") or {}).get("name") or "No partner"
        totals[partner] = totals.get(partner, Decimal(0)) + _number(invoice["amount_total"])
    rows = [("Partner", Decimal(0), 1, "section")]
    total = Decimal(0)
    for name, amount in sorted(totals.items()):
        rows.append((name, amount, 2, "line"))
        total += amount
    rows.append(("Total invoiced", total, 1, "total"))
    return rows


def _analytic(env: Env, report: dict[str, Any]) -> list[tuple[str, Decimal, int, str]]:
    totals: dict[str, Decimal] = {}
    for _move, line, _account in _posted_lines(env, report["date_from"], report["date_to"]):
        analytic = line.get("analytic_account_id") or {}
        if not isinstance(analytic, dict) or not analytic.get("id"):
            continue
        name = analytic.get("name") or "Analytic account"
        totals[name] = totals.get(name, Decimal(0)) + _number(line["debit"]) - _number(
            line["credit"]
        )
    rows = [("Analytic account", Decimal(0), 1, "section")]
    total = Decimal(0)
    for name, amount in sorted(totals.items()):
        rows.append((name, amount, 2, "line"))
        total += amount
    rows.append(("Total", total, 1, "total"))
    return rows


def _executive_summary(env: Env, report: dict[str, Any]) -> list[tuple[str, Decimal, int, str]]:
    by_type, _ = _balances(env, report["date_from"], report["date_to"])
    revenue = -by_type.get("income", Decimal(0))
    expenses = by_type.get("expense", Decimal(0))
    rows = [
        ("Revenue", revenue, 1, "line"),
        ("Expenses", expenses, 1, "line"),
        ("Profit", revenue - expenses, 1, "total"),
        ("Receivables", by_type.get("receivable", Decimal(0)), 1, "line"),
        ("Payables", -by_type.get("payable", Decimal(0)), 1, "line"),
        ("Cash and bank", by_type.get("bank", Decimal(0)), 1, "line"),
        ("Inventory", by_type.get("asset", Decimal(0)), 1, "line"),
    ]
    return rows


def _unrealized(env: Env, report: dict[str, Any]) -> list[tuple[str, Decimal, int, str]]:
    rows: list[tuple[str, Decimal, int, str]] = []
    ids = env["accounting.move"].search(
        [
            ("state", "=", "posted"),
            ("move_type", "in", ["out_invoice", "in_invoice"]),
            ("amount_residual", ">", 0),
        ]
    )
    total = Decimal(0)
    for invoice in env["accounting.move"].read(ids):
        currency_id = _id(invoice.get("currency_id"))
        if not currency_id:
            continue
        currency = env["core.currency"].read([currency_id])[0]
        current_rate = Decimal(1) / _number(currency.get("rate") or 1)
        difference = _number(invoice["amount_residual"]) * (
            current_rate - _number(invoice.get("currency_rate") or 1)
        )
        if abs(difference) <= EPS:
            continue
        rows.append(
            (
                f"{invoice['name']} · {(invoice.get('partner_id') or {}).get('name') or ''}",
                difference,
                1,
                "line",
            )
        )
        total += difference
    rows.append(("Total unrealized difference", total, 1, "total"))
    return rows


def _purchase_review(env: Env, report: dict[str, Any], kind: str) -> list[tuple[str, Decimal, int, str]]:
    rows: list[tuple[str, Decimal, int, str]] = []
    total = Decimal(0)
    orders = env["purchase.order"].search([("state", "=", "purchase")])
    for order in env["purchase.order"].read(orders):
        for line in order.get("order_line", []):
            received = _number(line.get("qty_received"))
            billed = _number(line.get("qty_billed"))
            gap = billed - received if kind == "billed_not_received" else received - billed
            if gap <= EPS:
                continue
            amount = gap * _number(line.get("price_unit"))
            rows.append((f"{order['name']} · {line['name']}", amount, 1, "line"))
            total += amount
    if not rows:
        rows.append(("Nothing to review", Decimal(0), 1, "line"))
    rows.append(("Total", total, 1, "total"))
    return rows


def _sales_review(env: Env, report: dict[str, Any], kind: str) -> list[tuple[str, Decimal, int, str]]:
    rows: list[tuple[str, Decimal, int, str]] = []
    total = Decimal(0)
    orders = env["sales.order"].search([("state", "=", "sale")])
    for order in env["sales.order"].read(orders):
        for line in order.get("order_line", []):
            delivered = _number(line.get("qty_delivered"))
            invoiced = _number(line.get("qty_invoiced"))
            gap = delivered - invoiced if kind == "invoices_to_issue" else invoiced - delivered
            if gap <= EPS:
                continue
            amount = gap * _number(line.get("price_unit"))
            rows.append((f"{order['name']} · {line['name']}", amount, 1, "line"))
            total += amount
    if not rows:
        rows.append(("Nothing to review", Decimal(0), 1, "line"))
    rows.append(("Total", total, 1, "total"))
    return rows


def run(env: Env, report_id: int) -> dict[str, Any]:
    """Rebuild one report from posted entries."""
    rows = env["accounting.report"].read([report_id])
    if not rows:
        raise ValidationError("report not found")
    report = rows[0]
    if report["date_from"] > report["date_to"]:
        raise ValidationError("the start date cannot be after the end date")
    _clear(env, report)
    kind = report["report_type"]
    if kind == "balance_sheet":
        rows_out = _balance_sheet(env, report)
    elif kind == "profit_and_loss":
        rows_out = _profit_and_loss(env, report)
    elif kind == "cash_flow":
        rows_out = _cash_flow(env, report)
    elif kind == "trial_balance":
        rows_out = _trial_balance(env, report)
    elif kind == "general_ledger":
        rows_out = _general_ledger(env, report)
    elif kind == "partner_ledger":
        rows_out = _partner_lines(env, report)
    elif kind == "aged_receivable":
        rows_out = _aged(env, report, "out_invoice")
    elif kind == "aged_payable":
        rows_out = _aged(env, report, "in_invoice")
    elif kind == "tax_report":
        rows_out = _tax_report(env, report)
    elif kind == "fiscal_report":
        rows_out = _tax_report(env, report, by_group=True)
    elif kind == "ec_sales_list" or kind == "invoice_analysis":
        rows_out = _invoice_analysis(env, report)
    elif kind == "analytic_report":
        rows_out = _analytic(env, report)
    elif kind == "executive_summary":
        rows_out = _executive_summary(env, report)
    elif kind == "unrealized_currencies":
        rows_out = _unrealized(env, report)
    elif kind == "billed_not_received":
        rows_out = _purchase_review(env, report, "billed_not_received")
    elif kind == "bill_to_receive":
        rows_out = _purchase_review(env, report, "bill_to_receive")
    elif kind == "invoices_to_issue":
        rows_out = _sales_review(env, report, "invoices_to_issue")
    elif kind == "invoiced_not_delivered":
        rows_out = _sales_review(env, report, "invoiced_not_delivered")
    else:
        raise ValidationError(f"unknown report type {kind}")
    for index, (label, amount, level, style) in enumerate(rows_out):
        _add(env, report_id, (index + 1) * 10, label, amount, level=level, style=style)
    env["accounting.report"].write([report_id], {"state": "computed"})
    return {
        "ok": True,
        "message": f"{report['name']} rebuilt with {len(rows_out)} rows.",
        "state": "computed",
    }
