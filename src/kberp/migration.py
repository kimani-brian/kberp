"""Migration importers for partners, products, opening balances and counts.

The importers are deliberately small CSV readers with an explicit dry-run. A
dry run validates every row and reports what would happen without writing; a
commit then performs the same plan. Re-running a partner or product file is
safe because rows are matched on their external id first and on a natural key
second.

Opening balances are posted as one balanced journal entry. Stock counts are
created as drafts unless `validate=True`, so a warehouse team can review them
before the ledger moves.
"""

from __future__ import annotations

import csv
import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .config import BASE_DIR
from .env import Env

PROJECT_ROOT = BASE_DIR.parents[1]
TEMPLATE_DIR = PROJECT_ROOT / "migration" / "templates"

KINDS = ("partners", "products", "opening_balances", "stock_counts")


class MigrationError(RuntimeError):
    pass


@dataclass
class ImportResult:
    kind: str
    dry_run: bool = False
    rows: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    totals: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "ok": self.ok,
            "dry_run": self.dry_run,
            "rows": self.rows,
            "created": self.created,
            "updated": self.updated,
            "skipped": self.skipped,
            "errors": self.errors,
            "warnings": self.warnings,
            "totals": self.totals,
        }


def load_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise MigrationError(f"file not found: {path}")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise MigrationError(f"{path} has no header row")
        rows = []
        for raw in reader:
            rows.append(
                {
                    (key or "").strip(): (value or "").strip()
                    for key, value in raw.items()
                }
            )
    return rows


def _bool(value: str, default: bool = False) -> bool:
    if not value:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _decimal(value: str, where: str, errors: list[str]) -> Decimal:
    if not value:
        return Decimal(0)
    try:
        return Decimal(value.replace(",", ""))
    except InvalidOperation:
        errors.append(f"{where}: {value!r} is not a number")
        return Decimal(0)


def _date(value: str, where: str, errors: list[str]) -> dt.date | None:
    if not value:
        errors.append(f"{where}: date is required")
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        errors.append(f"{where}: {value!r} is not an ISO date (YYYY-MM-DD)")
        return None


def _lookup(env: Env, model: str, domain: list[Any], *, create: dict[str, Any] | None = None) -> int | None:
    rows = env[model].search(domain, limit=1)
    if rows:
        return rows[0]
    if create is None:
        return None
    return env[model].create(create)


# -- partners --------------------------------------------------------------
def import_partners(
    env: Env, rows: list[dict[str, str]], *, dry_run: bool = True
) -> ImportResult:
    result = ImportResult("partners", dry_run=dry_run, rows=len(rows))
    partners = env["core.partner"]
    tags = env["core.partner_tag"]
    provided = {row.get("external_id", "") for row in rows if row.get("external_id")}
    seen: set[str] = set()
    pending_parents: list[tuple[str, int, str]] = []
    imported: dict[str, int] = {}
    for number, row in enumerate(rows, start=2):
        where = f"partners row {number}"
        name = row.get("name", "")
        if not name:
            result.errors.append(f"{where}: name is required")
            continue
        external_id = row.get("external_id", "")
        if external_id and external_id in seen:
            result.errors.append(f"{where}: duplicate external_id {external_id!r}")
            continue
        seen.add(external_id)

        values: dict[str, Any] = {
            "name": name,
            "is_company": _bool(row.get("is_company", "")),
        }
        for key in (
            "email",
            "phone",
            "mobile",
            "street",
            "street2",
            "city",
            "zip",
            "vat",
            "website",
            "function",
            "lang",
        ):
            if row.get(key):
                values[key] = row[key]
        if external_id:
            values["external_id"] = external_id
        if row.get("country_code"):
            country = _lookup(
                env, "core.country", [("code", "=", row["country_code"].upper())]
            )
            if country:
                values["country_id"] = country
            else:
                result.warnings.append(
                    f"{where}: unknown country code {row['country_code']!r}"
                )

        domain: list[Any] | None = None
        if external_id:
            domain = [("external_id", "=", external_id)]
        elif row.get("vat"):
            domain = [("vat", "=", row["vat"])]
        elif row.get("email"):
            domain = [("email", "=", row["email"])]

        existing = partners.search(domain, limit=1) if domain else []
        if not existing:
            existing = partners.search(
                [("name", "=", name), ("is_company", "=", values["is_company"])],
                limit=1,
            )

        tag_names = [tag.strip() for tag in row.get("tags", "").split(";") if tag.strip()]
        tag_ids: list[int] = []
        for tag_name in tag_names:
            tag_id = tags.search([("name", "=", tag_name)], limit=1)
            if tag_id:
                tag_ids.append(tag_id[0])
            elif dry_run:
                result.warnings.append(f"{where}: tag {tag_name!r} would be created")
            else:
                tag_ids.append(tags.create({"name": tag_name}))

        if existing:
            result.updated += 1
            record_id = existing[0]
            if not dry_run:
                update = {key: value for key, value in values.items() if key != "name"}
                if update:
                    partners.write([record_id], update)
                if tag_ids:
                    partners.write([record_id], {"tag_ids": tag_ids})
        else:
            result.created += 1
            record_id = 0
            if not dry_run:
                record_id = partners.create(values)
                if tag_ids:
                    partners.write([record_id], {"tag_ids": tag_ids})
        if external_id and record_id:
            imported[external_id] = record_id
        if row.get("parent_external_id"):
            pending_parents.append((row["parent_external_id"], record_id, where))

    for parent_external, record_id, where in pending_parents:
        parent_id = imported.get(parent_external)
        if not parent_id:
            parent = partners.search(
                [("external_id", "=", parent_external)], limit=1
            )
            parent_id = parent[0] if parent else None
        if not parent_id:
            if dry_run and parent_external in provided:
                continue
            result.errors.append(
                f"{where}: parent external_id {parent_external!r} not found"
            )
            continue
        if not dry_run and record_id:
            partners.write([record_id], {"parent_id": parent_id})

    return result


# -- products --------------------------------------------------------------
def import_products(
    env: Env, rows: list[dict[str, str]], *, dry_run: bool = True
) -> ImportResult:
    result = ImportResult("products", dry_run=dry_run, rows=len(rows))
    products = env["core.product_template"]
    uoms = env["core.uom"]
    categories = env["core.product_category"]
    seen: set[str] = set()
    for number, row in enumerate(rows, start=2):
        where = f"products row {number}"
        name = row.get("name", "")
        if not name:
            result.errors.append(f"{where}: name is required")
            continue
        external_id = row.get("external_id", "")
        if external_id and external_id in seen:
            result.errors.append(f"{where}: duplicate external_id {external_id!r}")
            continue
        seen.add(external_id)

        values: dict[str, Any] = {
            "name": name,
            "type": row.get("type") or "goods",
            "list_price": float(_decimal(row.get("list_price", ""), where, result.errors)),
            "standard_price": float(
                _decimal(row.get("standard_price", ""), where, result.errors)
            ),
        }
        for key in ("default_code", "barcode", "description", "external_id"):
            if row.get(key):
                values[key] = row[key]
        if values["type"] not in {"goods", "service"}:
            result.errors.append(f"{where}: type must be goods or service")
            continue

        if row.get("uom"):
            uom = uoms.search([("name", "=", row["uom"])], limit=1)
            if uom:
                values["uom_id"] = uom[0]
            elif dry_run:
                result.warnings.append(f"{where}: unit {row['uom']!r} not found")
            else:
                result.warnings.append(f"{where}: unit {row['uom']!r} not created")
        if row.get("category"):
            category = categories.search([("name", "=", row["category"])], limit=1)
            if category:
                values["category_id"] = category[0]
            elif dry_run:
                result.warnings.append(f"{where}: category {row['category']!r} would be created")
            else:
                values["category_id"] = categories.create({"name": row["category"]})

        domain: list[Any] | None = None
        if external_id:
            domain = [("external_id", "=", external_id)]
        elif row.get("default_code"):
            domain = [("default_code", "=", row["default_code"])]
        elif row.get("barcode"):
            domain = [("barcode", "=", row["barcode"])]

        existing = products.search(domain, limit=1) if domain else []
        if existing:
            result.updated += 1
            if not dry_run:
                products.write(existing, {k: v for k, v in values.items() if k != "name"})
        else:
            result.created += 1
            if not dry_run:
                products.create(values)

    return result


# -- opening balances ------------------------------------------------------
def import_opening_balances(
    env: Env, rows: list[dict[str, str]], *, dry_run: bool = True
) -> ImportResult:
    result = ImportResult("opening_balances", dry_run=dry_run, rows=len(rows))
    if not rows:
        result.errors.append("opening_balances: no rows")
        return result
    accounts = env["accounting.account"]
    partners = env["core.partner"]
    journals = env["accounting.journal"]

    lines: list[dict[str, Any]] = []
    debit_total = Decimal(0)
    credit_total = Decimal(0)
    entry_date: dt.date | None = None
    for number, row in enumerate(rows, start=2):
        where = f"opening_balances row {number}"
        date = _date(row.get("date", ""), where, result.errors)
        if date and entry_date and date != entry_date:
            result.errors.append(f"{where}: all opening balances share one date")
        entry_date = entry_date or date
        code = row.get("account_code", "")
        account = accounts.search([("code", "=", code)], limit=1) if code else []
        if not account:
            result.errors.append(f"{where}: unknown account code {code!r}")
            continue
        debit = _decimal(row.get("debit", ""), where, result.errors)
        credit = _decimal(row.get("credit", ""), where, result.errors)
        if debit and credit:
            result.errors.append(f"{where}: a line has both debit and credit")
        debit_total += debit
        credit_total += credit

        values: dict[str, Any] = {
            "account_id": account[0],
            "name": row.get("label") or "Opening balance",
            "debit": float(debit),
            "credit": float(credit),
        }
        if row.get("partner_external_id"):
            partner = partners.search(
                [("external_id", "=", row["partner_external_id"])], limit=1
            )
            if partner:
                values["partner_id"] = partner[0]
            else:
                result.errors.append(
                    f"{where}: unknown partner external_id "
                    f"{row['partner_external_id']!r}"
                )
        lines.append(values)

    result.totals = {
        "debit": str(debit_total),
        "credit": str(credit_total),
    }
    if debit_total != credit_total:
        result.errors.append(
            f"opening balances do not balance: debit {debit_total} != credit {credit_total}"
        )
    if result.errors or not lines:
        return result

    journal = journals.search([("code", "=", "GEN")], limit=1)
    if not journal:
        result.errors.append("no general journal (code GEN) found")
        return result
    existing = env["accounting.move"].search(
        [("origin", "=", "MIGRATION/OPENING")], limit=1
    )
    if existing:
        result.skipped = 1
        result.warnings.append("opening balances were already imported")
        return result

    if dry_run:
        return result

    from .addons.accounting.services import posting

    move_id = env["accounting.move"].create(
        {
            "name": "OPENING",
            "move_type": "entry",
            "journal_id": journal[0],
            "date": entry_date or dt.date.today(),
            "origin": "MIGRATION/OPENING",
            "line_ids": lines,
        }
    )
    posting.post(env, move_id)
    result.created = 1
    return result


# -- stock counts ----------------------------------------------------------
def import_stock_counts(
    env: Env,
    rows: list[dict[str, str]],
    *,
    dry_run: bool = True,
    validate: bool = False,
) -> ImportResult:
    result = ImportResult("stock_counts", dry_run=dry_run, rows=len(rows))
    locations = env["inventory.location"]
    products = env["core.product_template"]

    grouped: dict[str, list[dict[str, Any]]] = {}
    for number, row in enumerate(rows, start=2):
        where = f"stock_counts row {number}"
        location_name = row.get("location") or ""
        location = locations.search([("name", "=", location_name)], limit=1)
        if not location:
            location = locations.search([("usage", "=", "internal")], limit=1)
        if not location:
            result.errors.append(f"{where}: no internal location found")
            continue
        code = row.get("product_code") or row.get("product")
        product = products.search(
            ["|", ("default_code", "=", code), ("name", "=", code)], limit=1
        )
        if not product:
            result.errors.append(f"{where}: unknown product {code!r}")
            continue
        counted = _decimal(row.get("counted_qty", ""), where, result.errors)
        grouped.setdefault(str(location[0]), []).append(
            {
                "product_id": product[0],
                "counted_qty": float(counted),
            }
        )

    if result.errors:
        return result
    for location_id, lines in grouped.items():
        if not dry_run:
            count_id = env["inventory.stock_count"].create(
                {
                    "location_id": int(location_id),
                    "line_ids": lines,
                    "note": "Imported by kberp import stock_counts",
                }
            )
            if validate:
                from .addons.inventory.services import audit

                audit.validate_count(env, count_id)
        result.created += 1
    if dry_run:
        result.warnings.append("stock counts will be created as drafts")
    return result


IMPORTERS = {
    "partners": import_partners,
    "products": import_products,
    "opening_balances": import_opening_balances,
    "stock_counts": import_stock_counts,
}


def import_file(
    env: Env,
    kind: str,
    path: Path,
    *,
    dry_run: bool = True,
    validate: bool = False,
) -> ImportResult:
    if kind not in IMPORTERS:
        raise MigrationError(f"unknown import kind {kind!r}; choose from {', '.join(KINDS)}")
    rows = load_csv(path)
    if kind == "stock_counts":
        return import_stock_counts(env, rows, dry_run=dry_run, validate=validate)
    return IMPORTERS[kind](env, rows, dry_run=dry_run)


TEMPLATES: dict[str, tuple[str, list[str]]] = {
    "partners.csv": (
        "name,external_id,is_company,email,phone,vat,street,city,country_code,parent_external_id,tags",
        [
            (
                "Acme Ltd,PART-001,true,accounts@acme.test,+254700000001,P051234567X,"
                "Enterprise Road,Nairobi,KE,,Wholesale;Key account"
            ),
            (
                "Jane Wanjiru,PART-002,false,jane@acme.test,+254700000002,,"
                "Enterprise Road,Nairobi,KE,PART-001,"
            ),
        ],
    ),
    "products.csv": (
        "name,external_id,default_code,type,list_price,standard_price,uom,category,barcode,description",
        [
            (
                "Steel Bolt M8,PROD-001,BOLT-M8,goods,12.50,7.25,Units,Hardware,"
                "5901234123457,Galvanised steel bolt"
            ),
            (
                "Installation,PROD-002,SERV-INSTALL,service,1500,0,Hours,Services,,"
                "On-site installation"
            ),
        ],
    ),
    "opening_balances.csv": (
        "date,account_code,partner_external_id,label,debit,credit",
        [
            "2026-01-01,110000,,Opening bank balance,250000.00,0",
            "2026-01-01,300000,,Opening equity,0,250000.00",
        ],
    ),
    "stock_counts.csv": (
        "location,product_code,counted_qty",
        [
            "Stock,BOLT-M8,1200",
            "Stock,SERV-INSTALL,0",
        ],
    ),
}


def write_templates(directory: Path | None = None) -> list[Path]:
    target = directory or TEMPLATE_DIR
    target.mkdir(parents=True, exist_ok=True)
    written = []
    for name, (header, rows) in TEMPLATES.items():
        path = target / name
        path.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
        written.append(path)
    return written
