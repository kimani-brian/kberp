"""Field types for the KB ERP ORM.

Fields describe both the Python API and the PostgreSQL column. Types are
deliberately close to Odoo's names so the XML and mental model carry over.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Sequence
from decimal import Decimal
from typing import Any


class Field:
    type = "char"
    column_type = "varchar"

    def __init__(
        self,
        string: str | None = None,
        *,
        required: bool = False,
        readonly: bool = False,
        index: bool = False,
        default: Any = None,
        help: str | None = None,
        groups: str | None = None,
        size: int | None = None,
    ):
        self.string = string
        self.required = required
        self.readonly = readonly
        self.index = index
        self.default = default
        self.help = help
        self.groups = groups
        self.size = size
        self.name: str = ""  # set by the metaclass

    # -- conversion --------------------------------------------------------
    def to_python(self, value: Any) -> Any:
        return value

    def to_sql(self, value: Any) -> Any:
        value = self.to_python(value)
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, (dt.date, dt.datetime)):
            return value
        return value

    def default_value(self) -> Any:
        value = self.default
        return value() if callable(value) else value

    @property
    def ddl(self) -> str:
        parts = [self.column_type]
        if self.required and self.default_value() is None:
            parts.append("NOT NULL")
        return " ".join(parts)

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.name}>"


class Char(Field):
    type = "char"
    column_type = "varchar"

    @property
    def ddl(self) -> str:
        base = f"varchar({self.size})" if self.size else "varchar"
        return f"{base} NOT NULL" if self.required and self.default_value() is None else base


class Text(Field):
    type = "text"
    column_type = "text"


class Integer(Field):
    type = "integer"
    column_type = "integer"

    def to_python(self, value: Any) -> Any:
        if value is None or value == "":
            return None
        return int(value)


class Boolean(Field):
    type = "boolean"
    column_type = "boolean"

    def to_python(self, value: Any) -> Any:
        if value in (None, ""):
            return None
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)


class Float(Field):
    type = "float"
    column_type = "double precision"

    def to_python(self, value: Any) -> Any:
        if value is None or value == "":
            return None
        return float(value)


class Monetary(Field):
    type = "monetary"
    column_type = "numeric(18, 4)"

    def to_python(self, value: Any) -> Any:
        if value is None or value == "":
            return Decimal(0)
        return value if isinstance(value, Decimal) else Decimal(str(value))


class Date(Field):
    type = "date"
    column_type = "date"

    def to_python(self, value: Any) -> Any:
        if value in (None, ""):
            return None
        if isinstance(value, dt.datetime):
            return value.date()
        if isinstance(value, dt.date):
            return value
        return dt.date.fromisoformat(str(value)[:10])


class Datetime(Field):
    type = "datetime"
    column_type = "timestamptz"

    def to_python(self, value: Any) -> Any:
        if value in (None, ""):
            return None
        if isinstance(value, dt.datetime):
            return value
        return dt.datetime.fromisoformat(str(value))


class Selection(Field):
    type = "selection"
    column_type = "varchar"

    def __init__(self, selection: Sequence[tuple[str, str] | str], **kwargs: Any):
        super().__init__(**kwargs)
        normalised: list[tuple[str, str]] = []
        for item in selection:
            if isinstance(item, str):
                normalised.append((item, item))
            else:
                normalised.append((item[0], item[1]))
        self.selection = normalised

    def labels(self) -> dict[str, str]:
        return dict(self.selection)


class Many2one(Field):
    type = "many2one"
    column_type = "integer"

    def __init__(self, comodel: str, **kwargs: Any):
        super().__init__(**kwargs)
        self.comodel = comodel

    def to_python(self, value: Any) -> Any:
        if value in (None, "", False):
            return None
        if isinstance(value, dict):
            return value.get("id")
        return int(value)


class Many2many(Field):
    """A relation table of two integer columns, Odoo's `(0, 0, ids)` shape.

    The field owns no column on the model table. The installer creates the
    relation table in the owning model's schema.
    """

    type = "many2many"
    column_type = ""

    def __init__(
        self,
        comodel: str,
        *,
        relation: str | None = None,
        column1: str | None = None,
        column2: str | None = None,
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        self.comodel = comodel
        self.relation = relation
        self.column1 = column1
        self.column2 = column2

    def relation_name(self, model) -> str:
        return self.relation or f"{model.table_name()}_{self.name}_rel"

    def relation_columns(self, model) -> tuple[str, str]:
        return (
            self.column1 or f"{model.table_name()}_id",
            self.column2 or f"{self.comodel.replace('.', '_')}_id",
        )


class One2many(Field):
    """A list of child rows that point back at this record.

    Like `Many2many`, the field owns no column. The installer creates no table
    for it; the child model owns the foreign key. Reads and writes are expanded
    in the ORM so a document and its lines can be edited as one value.
    """

    type = "one2many"
    column_type = ""

    def __init__(self, comodel: str, inverse: str, **kwargs: Any):
        super().__init__(**kwargs)
        self.comodel = comodel
        self.inverse = inverse


class StringList(Field):
    """A PostgreSQL text[] of values, used for group membership and tags."""

    type = "string_list"
    column_type = "text[]"

    def to_python(self, value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return list(value)

    def to_sql(self, value: Any) -> Any:
        return self.to_python(value)

    def default_value(self) -> Any:
        return self.to_python(super().default_value())


FIELD_TYPES = {
    "char": Char,
    "text": Text,
    "integer": Integer,
    "boolean": Boolean,
    "float": Float,
    "monetary": Monetary,
    "date": Date,
    "datetime": Datetime,
    "many2one": Many2one,
    "many2many": Many2many,
    "string_list": StringList,
    "selection": Selection,
}

AUDIT_FIELDS: dict[str, Field] = {
    "create_uid": Many2one("core.user", string="Created by", readonly=True),
    "create_date": Datetime(string="Created on", readonly=True),
    "write_uid": Many2one("core.user", string="Last Updated by", readonly=True),
    "write_date": Datetime(string="Last Updated on", readonly=True),
}


def collect_fields(namespace: dict[str, Any], bases: Iterable[type]) -> dict[str, Field]:
    fields: dict[str, Field] = {}
    for base in bases:
        fields.update(getattr(base, "_fields", {}))
    for key, value in list(namespace.items()):
        if isinstance(value, Field):
            value.name = key
            fields[key] = value
    return fields
