"""Kernel partner models. The Contacts app owns their UI; the kernel owns the data.

C1 adds the pieces every consumer depends on: the commercial hierarchy, the
stored `complete_name` that drives alphabetical ordering, tags, industries and
the bank directory. The sync rules live here rather than in the views so the
API and the browser cannot disagree.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from psycopg import sql

from ....orm import fields as f
from ....orm.model import BaseModel, ValidationError

ADDRESS_FIELDS = ("street", "street2", "city", "zip", "state_id", "country_id")
DELEGATED_FIELDS = ("industry_id", "company_registry")
ADDRESS_TYPES = ("contact", "invoice", "delivery", "other")
TYPE_LABELS = {
    "contact": "Contact",
    "invoice": "Invoice Address",
    "delivery": "Delivery Address",
    "other": "Other Address",
}


class Partner(BaseModel):
    _name = "core.partner"
    _table = "partner"
    _description = "Contact"
    _order = "complete_name, id"

    # Identity
    name = f.Char(required=True, string="Name")
    external_id = f.Char(string="External ID", index=True)
    is_company = f.Boolean(string="Is a Company", default=False)
    parent_id = f.Many2one("core.partner", string="Related Company")
    type = f.Selection(
        [
            ("contact", "Contact"),
            ("invoice", "Invoice Address"),
            ("delivery", "Delivery Address"),
            ("other", "Other Address"),
        ],
        default="contact",
    )
    function = f.Char(string="Job Position")
    company_id = f.Many2one("core.company", string="Company")

    # Contact details
    email = f.Char(string="Email")
    phone = f.Char(string="Phone")
    mobile = f.Char(string="Mobile")
    website = f.Char(string="Website")
    vat = f.Char(string="Tax ID")
    company_registry = f.Char(string="Company Registry")
    industry = f.Char(string="Industry (legacy)")
    industry_id = f.Many2one("core.industry", string="Industry")
    salesperson_id = f.Many2one("core.user", string="Salesperson")
    lang = f.Char(string="Language", default="en_US")
    purchase_warning = f.Text(string="Purchasing Warning")
    tag_ids = f.Many2many(
        "core.partner_tag",
        relation="core_partner_tag_rel",
        column1="partner_id",
        column2="tag_id",
        string="Tags",
    )

    # Address
    street = f.Char(string="Street")
    street2 = f.Char(string="Street 2")
    city = f.Char(string="City")
    zip = f.Char(string="ZIP")
    state_id = f.Many2one("core.state", string="State")
    country_id = f.Many2one("core.country", string="Country")

    # Bookkeeping
    active = f.Boolean(default=True)
    comment = f.Text(string="Notes")

    # Derived and stored. Kept as columns so search, ordering and reports use
    # the same value the form shows.
    complete_name = f.Char(string="Complete Name", default="", index=True)
    commercial_partner_id = f.Many2one("core.partner", string="Commercial Entity")

    # -- writing -----------------------------------------------------------
    def create(self, values: dict[str, Any]) -> int:
        values = dict(values)
        parent_id = values.get("parent_id")
        if parent_id:
            self._check_cycle(None, int(parent_id))
            self._inherit_from_company(values, int(parent_id))
        new_id = super().create(values)
        self._after_change([new_id], values)
        return new_id

    def write(self, ids: Any, values: dict[str, Any]) -> int:
        ids = [int(i) for i in ids]
        values = dict(values)
        parent_id = values.get("parent_id")
        if parent_id:
            for record_id in ids:
                self._check_cycle(record_id, int(parent_id))
        if values.get("active") is False:
            self._check_archive(ids)
        updated = super().write(ids, values)
        self._after_change(ids, values)
        return updated

    def unlink(self, ids: Any) -> int:
        ids = [int(i) for i in ids]
        if ids:
            self._check_referenced(ids)
        return super().unlink(ids)

    def resync_all(self) -> int:
        """Recompute derived columns after an upgrade or a bulk import."""
        rows = self.env.db.fetch_all(
            sql.SQL("SELECT id FROM {}").format(self.from_clause()), ()
        )
        ids = [int(row[0]) for row in rows]
        if ids:
            self._after_change(ids, {})
        return len(ids)

    def address_get(
        self, partner_id: int, types: Sequence[str] | None = None
    ) -> dict[str, int]:
        """Return the address to use for each purpose.

        A document asks for `["invoice", "delivery"]` and receives partner ids.
        Resolution walks from the record itself to its parent and finally to the
        commercial entity, then looks among that entity's address children. A
        company with an invoice address therefore invoices to the child, while
        a person without a delivery address falls back to the company.
        """
        requested = list(types or ADDRESS_TYPES)
        unknown = set(requested) - set(ADDRESS_TYPES)
        if unknown:
            raise ValidationError(f"unknown address type: {', '.join(sorted(unknown))}")
        row = self._row(partner_id, ("id", "parent_id", "commercial_partner_id"))
        if not row:
            raise ValidationError("No such contact")
        commercial_id = int(row.get("commercial_partner_id") or partner_id)
        chain = [int(partner_id)]
        parent_id = row.get("parent_id")
        if parent_id and int(parent_id) != commercial_id:
            chain.append(int(parent_id))
        if commercial_id not in chain:
            chain.append(commercial_id)

        result: dict[str, int] = {}
        for address_type in requested:
            chosen = commercial_id
            for candidate_id in chain:
                candidate = self._row(candidate_id, ("id", "type"))
                if candidate.get("type") == address_type:
                    chosen = candidate_id
                    break
            else:
                children = self._select_raw(
                    ("id",),
                    where="parent_id = %s AND type = %s AND active",
                    params=(commercial_id, address_type),
                )
                if children:
                    chosen = int(children[0]["id"])
            result[address_type] = chosen
        return result

    def statistics(self, ids: Sequence[int]) -> dict[int, dict[str, int]]:
        """Address and bank counts for a page of contacts, in two queries."""
        wanted = [int(i) for i in ids]
        result = {record_id: {"addresses": 0, "bank_accounts": 0} for record_id in wanted}
        if not wanted:
            return result
        address_rows = self.env.db.fetch_all(
            sql.SQL(
                "SELECT parent_id, count(*) FROM {} "
                "WHERE parent_id = ANY(%s) AND active GROUP BY parent_id"
            ).format(self.from_clause()),
            (wanted,),
        )
        for parent_id, count in address_rows:
            if int(parent_id) in result:
                result[int(parent_id)]["addresses"] = int(count)

        bank = self.env["core.bank_account"]
        bank_rows = self.env.db.fetch_all(
            sql.SQL(
                "SELECT partner_id, count(*) FROM {} "
                "WHERE partner_id = ANY(%s) AND active GROUP BY partner_id"
            ).format(bank.from_clause()),
            (wanted,),
        )
        for partner_id, count in bank_rows:
            if int(partner_id) in result:
                result[int(partner_id)]["bank_accounts"] = int(count)
        return result

    # -- derived fields ----------------------------------------------------
    def _after_change(self, ids: list[int], values: dict[str, Any]) -> None:
        for record_id in ids:
            row = self._row(record_id, ("id", "name", "parent_id", "is_company"))
            if not row:
                continue
            self._update_raw(
                [record_id],
                {
                    "complete_name": self._complete_name(row),
                    "commercial_partner_id": self._commercial_partner(row),
                },
            )
        self._refresh_descendants(ids)

        address_changed = any(name in values for name in ADDRESS_FIELDS)
        for record_id in ids:
            row = self._row(record_id, ("id", "is_company", "parent_id", "type"))
            if not row:
                continue
            is_company = bool(row["is_company"])
            parent_id = row["parent_id"]

            if address_changed and is_company:
                updates = {
                    name: values[name]
                    for name in ADDRESS_FIELDS
                    if name in values and values[name] is not None
                }
                children = self._contact_children(record_id)
                if updates and children:
                    self._update_raw(children, updates)

            if "vat" in values and not is_company and parent_id and values.get("vat"):
                company_id = self._commercial_partner(
                    self._row(parent_id, ("id", "is_company", "parent_id", "commercial_partner_id"))
                )
                self._update_raw([company_id], {"vat": values["vat"]})

            delegated = {name: values[name] for name in DELEGATED_FIELDS if name in values}
            if delegated and is_company:
                children = self._contact_children(record_id)
                if children:
                    self._update_raw(children, delegated)

    def _refresh_descendants(self, ids: list[int]) -> None:
        queue = list(ids)
        seen: set[int] = set()
        depth = 0
        while queue and depth < 20:
            next_queue: list[int] = []
            for parent_id in queue:
                rows = self._select_raw(
                    ("id", "name", "parent_id", "is_company"),
                    where="parent_id = %s",
                    params=(parent_id,),
                )
                for row in rows:
                    if row["id"] in seen:
                        continue
                    seen.add(row["id"])
                    self._update_raw(
                        [row["id"]],
                        {
                            "complete_name": self._complete_name(row),
                            "commercial_partner_id": self._commercial_partner(row),
                        },
                    )
                    next_queue.append(row["id"])
            queue = next_queue
            depth += 1

    def _complete_name(self, row: dict[str, Any]) -> str:
        name = str(row.get("name") or "")
        parent_id = row.get("parent_id")
        if not parent_id:
            return name
        parent = self._row(parent_id, ("name", "complete_name"))
        parent_name = str(parent.get("complete_name") or parent.get("name") or "")
        if not parent_name:
            return name
        return f"{parent_name}, {name}" if name else parent_name

    def _commercial_partner(self, row: dict[str, Any]) -> int:
        record_id = int(row["id"])
        parent_id = row.get("parent_id")
        if row.get("is_company") or not parent_id:
            return record_id
        parent = self._row(parent_id, ("id", "is_company", "commercial_partner_id"))
        if parent.get("is_company"):
            return int(parent["id"])
        return int(parent.get("commercial_partner_id") or parent["id"])

    # -- sync rules --------------------------------------------------------
    def _inherit_from_company(self, values: dict[str, Any], parent_id: int) -> None:
        if values.get("type") not in (None, "contact"):
            return
        parent = self._row(parent_id, ("id", "is_company", "parent_id", "commercial_partner_id"))
        if not parent:
            return
        company_id = self._commercial_partner(parent)
        company = self._row(company_id, (*ADDRESS_FIELDS, *DELEGATED_FIELDS, "vat"))
        for name in ADDRESS_FIELDS:
            if values.get(name) in (None, "") and company.get(name) is not None:
                values[name] = company[name]
        for name in DELEGATED_FIELDS:
            if values.get(name) in (None, "") and company.get(name) is not None:
                values[name] = company[name]
        if values.get("vat") in (None, "") and company.get("vat"):
            values["vat"] = company["vat"]

    def _check_cycle(self, record_id: int | None, parent_id: int) -> None:
        seen: set[int] = set()
        current: int | None = parent_id
        while current:
            if record_id is not None and current == record_id:
                raise ValidationError("A contact cannot be its own ancestor")
            if current in seen:
                raise ValidationError("The parent hierarchy contains a cycle")
            seen.add(current)
            current = self._row(current, ("parent_id",)).get("parent_id")

    def _check_archive(self, ids: list[int]) -> None:
        if not self._table_exists("core", "res_users"):
            return
        query = sql.SQL(
            "SELECT count(*) FROM {}.{} WHERE partner_id = ANY(%s) AND active"
        ).format(sql.Identifier("core"), sql.Identifier("res_users"))
        row = self.env.db.fetch_one(query, (ids,))
        if row and row[0]:
            raise ValidationError(
                "This contact belongs to an active user; deactivate the user first"
            )

    def _check_referenced(self, ids: list[int]) -> None:
        children = self._select_raw(
            ("id",),
            where="parent_id = ANY(%s) AND NOT (id = ANY(%s))",
            params=(ids, ids),
        )
        if children:
            raise ValidationError(
                "This contact still has addresses or people attached; move them first"
            )
        registry = getattr(self.env, "registry", None)
        if registry is None:
            return
        for model in registry.models.values():
            if model._name == self._name or model._abstract:
                continue
            for name, field in model._fields.items():
                if not isinstance(field, f.Many2one) or field.comodel != self._name:
                    continue
                query = sql.SQL("SELECT count(*) FROM {} WHERE {} = ANY(%s)").format(
                    model.from_clause(), sql.Identifier(name)
                )
                row = self.env.db.fetch_one(query, (ids,))
                if row and row[0]:
                    raise ValidationError(
                        "This contact is referenced by existing records and cannot be deleted"
                    )

    # -- small SQL helpers -------------------------------------------------
    def _table_exists(self, schema: str, table: str) -> bool:
        row = self.env.db.fetch_one(
            """
            SELECT 1 FROM information_schema.tables
             WHERE table_schema = %s AND table_name = %s
            """,
            (schema, table),
        )
        return row is not None

    def _row(self, record_id: int, columns: tuple[str, ...]) -> dict[str, Any]:
        rows = self._select_raw(columns, where="id = %s", params=(record_id,))
        return rows[0] if rows else {}

    def _select_raw(
        self,
        columns: tuple[str, ...],
        *,
        where: str,
        params: tuple[Any, ...],
    ) -> list[dict[str, Any]]:
        query = sql.SQL("SELECT {} FROM {} WHERE {}").format(
            sql.SQL(", ").join(sql.Identifier(name) for name in columns),
            self.from_clause(),
            sql.SQL(where),
        )
        rows = self.env.db.fetch_all(query, params)
        return [dict(zip(columns, row)) for row in rows]

    def _update_raw(self, ids: list[int], values: dict[str, Any]) -> None:
        if not ids or not values:
            return
        assignments = sql.SQL(", ").join(
            sql.SQL("{} = %s").format(sql.Identifier(name)) for name in values
        )
        query = sql.SQL("UPDATE {} SET {} WHERE id = ANY(%s)").format(
            self.from_clause(), assignments
        )
        self.env.db.execute(query, [*values.values(), ids])

    def _contact_children(self, company_id: int) -> list[int]:
        rows = self._select_raw(
            ("id",),
            where="parent_id = %s AND type = %s",
            params=(company_id, "contact"),
        )
        return [int(row["id"]) for row in rows]


class PartnerTag(BaseModel):
    _name = "core.partner_tag"
    _table = "partner_tag"
    _description = "Contact Tag"
    _order = "name"

    name = f.Char(required=True, index=True)
    parent_id = f.Many2one("core.partner_tag", string="Parent Tag")
    color = f.Integer(string="Color", default=0)
    active = f.Boolean(default=True)


class Industry(BaseModel):
    _name = "core.industry"
    _table = "industry"
    _description = "Industry"
    _order = "name"

    name = f.Char(required=True, index=True)
    active = f.Boolean(default=True)


class Bank(BaseModel):
    _name = "core.bank"
    _table = "res_bank"
    _description = "Bank"
    _order = "name"

    name = f.Char(required=True, index=True)
    bic = f.Char(string="BIC/SWIFT")
    country_id = f.Many2one("core.country", string="Country")
    active = f.Boolean(default=True)

    def create(self, values: dict[str, Any]) -> int:
        values = dict(values)
        self._normalise(values)
        return super().create(values)

    def write(self, ids: Any, values: dict[str, Any]) -> int:
        values = dict(values)
        self._normalise(values)
        return super().write(ids, values)

    @staticmethod
    def _normalise(values: dict[str, Any]) -> None:
        bic = values.get("bic")
        if isinstance(bic, str):
            values["bic"] = bic.replace(" ", "").upper()


class BankAccount(BaseModel):
    _name = "core.bank_account"
    _table = "bank_account"
    _description = "Bank Account"
    _rec_name = "acc_number"
    _order = "acc_number"
    _unique_together = (("partner_id", "acc_number"),)

    partner_id = f.Many2one("core.partner", string="Account Holder", required=True, index=True)
    bank_id = f.Many2one("core.bank", string="Bank")
    acc_number = f.Char(string="Account Number", required=True, index=True)
    acc_holder_name = f.Char(string="Account Holder Name")
    company_id = f.Many2one("core.company", string="Company")
    active = f.Boolean(default=True)

    def create(self, values: dict[str, Any]) -> int:
        values = dict(values)
        self._normalise(values)
        self._check_duplicate(values)
        return super().create(values)

    def write(self, ids: Any, values: dict[str, Any]) -> int:
        ids = [int(i) for i in ids]
        values = dict(values)
        self._normalise(values)
        if "acc_number" in values or "partner_id" in values:
            for record_id in ids:
                current = self.read([record_id])[0]
                merged = {
                    "partner_id": values.get("partner_id", current.get("partner_id")),
                    "acc_number": values.get("acc_number", current.get("acc_number")),
                }
                merged["partner_id"] = (
                    merged["partner_id"].get("id")
                    if isinstance(merged["partner_id"], dict)
                    else merged["partner_id"]
                )
                self._check_duplicate(merged, exclude=record_id)
        return super().write(ids, values)

    @staticmethod
    def _normalise(values: dict[str, Any]) -> None:
        account = values.get("acc_number")
        if isinstance(account, str):
            values["acc_number"] = "".join(ch for ch in account if ch.isalnum()).upper()

    def _check_duplicate(self, values: dict[str, Any], *, exclude: int | None = None) -> None:
        partner_id = values.get("partner_id")
        acc_number = values.get("acc_number")
        if not partner_id or not acc_number:
            return
        domain: list[Any] = [
            ("partner_id", "=", partner_id),
            ("acc_number", "=", acc_number),
        ]
        if exclude is not None:
            domain.append(("id", "!=", exclude))
        if self.search(domain, limit=1):
            raise ValidationError(
                "This partner already has a bank account with that number"
            )


class Country(BaseModel):
    _name = "core.country"
    _table = "country"
    _description = "Country"
    _rec_name = "name"
    _order = "name"

    code = f.Char(required=True, size=2, index=True)
    name = f.Char(required=True, index=True)
    phone_code = f.Char()


class State(BaseModel):
    _name = "core.state"
    _table = "state"
    _description = "State"
    _rec_name = "name"
    _order = "name"

    code = f.Char(required=True)
    name = f.Char(required=True, index=True)
    country_id = f.Many2one("core.country", string="Country", required=True)
