"""The model layer: registry-driven tables, recordsets and CRUD.

Deliberately small for P0, but the semantics are the ones the product needs:
server-side validation, domain-searched reads, audit columns, and every write
behind an access check.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Sequence
from typing import Any, ClassVar

from psycopg import sql

from . import fields as f
from .domains import Compiler, DomainError, domain_matches_values, order_by


class AccessError(PermissionError):
    pass


class ValidationError(ValueError):
    pass


class ConflictError(ValidationError):
    """A transition was requested from a state that does not allow it."""


class MetaModel(type):
    _fields: dict[str, f.Field]

    def __new__(mcls, name: str, bases: tuple[type, ...], namespace: dict[str, Any]):
        cls = super().__new__(mcls, name, bases, namespace)
        cls._fields = f.collect_fields(namespace, bases)
        if not namespace.get("_abstract"):
            for field_name, field in f.AUDIT_FIELDS.items():
                cls._fields.setdefault(field_name, field)
                field.name = field_name
        return cls


class BaseModel(metaclass=MetaModel):
    _name: str = ""
    _table: str | None = None
    _schema: str | None = None
    _description: str = ""
    _order: str = "id"
    _rec_name: str = "name"
    _abstract: bool = False
    _module: str = ""
    _unique_fields: tuple[str, ...] = ()
    _unique_together: tuple[tuple[str, ...], ...] = ()
    _fields: ClassVar[dict[str, f.Field]] = {}

    def __init__(self, env):
        self.env = env

    # -- table helpers -----------------------------------------------------
    @classmethod
    def table_name(cls) -> str:
        return cls._table or cls._name.replace(".", "_")

    @classmethod
    def from_clause(cls) -> sql.Composable:
        if not cls._schema:
            raise RuntimeError(f"{cls._name}: schema not assigned by the registry")
        return sql.SQL("{}.{}").format(sql.Identifier(cls._schema), sql.Identifier(cls.table_name()))

    # -- access control ----------------------------------------------------
    def check_access(self, mode: str) -> None:
        self.env.check_access(self._name, mode)

    # -- reading -----------------------------------------------------------
    def _default_scope(self, domain: Sequence[Any] | None) -> Sequence[Any] | None:
        """Combine the archived-row scope with the user's record rules."""
        tokens = list(domain or [])
        if "active" in self._fields and self.env.context.get("active_test", True):
            mentions_active = any(
                isinstance(token, (tuple, list)) and token and token[0] == "active"
                for token in tokens
            )
            if not mentions_active:
                tokens = (
                    ["&", *tokens, ("active", "=", True)]
                    if tokens
                    else [("active", "=", True)]
                )
        rule = self.env.rule_domain(self._name, "read")
        if rule:
            tokens = ["&", *rule, *tokens] if tokens else list(rule)
        return tokens

    def search(
        self,
        domain: Sequence[Any] | None = None,
        order: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[int]:
        self.check_access("read")
        compiler = Compiler(self)
        where = compiler.sql(self._default_scope(domain))
        query = sql.SQL("SELECT id FROM {} WHERE {} ORDER BY {}").format(
            self.from_clause(), sql.SQL(where), sql.SQL(order_by(self, order))
        )
        if limit is not None:
            query = sql.SQL("{} LIMIT %s OFFSET %s").format(query)
            params: list[Any] = [*compiler.params, int(limit), int(offset)]
        else:
            if offset:
                query = sql.SQL("{} OFFSET %s").format(query)
                params = [*compiler.params, int(offset)]
            else:
                params = compiler.params
        rows = self.env.db.fetch_all(query, params)
        return [row[0] for row in rows]

    def search_count(self, domain: Sequence[Any] | None = None) -> int:
        self.check_access("read")
        compiler = Compiler(self)
        where = compiler.sql(self._default_scope(domain))
        query = sql.SQL("SELECT count(*) FROM {} WHERE {}").format(
            self.from_clause(), sql.SQL(where)
        )
        row = self.env.db.fetch_one(query, compiler.params)
        return int(row[0]) if row else 0

    def read_group(
        self,
        domain: Sequence[Any] | None = None,
        groupby: str = "id",
        *,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Count records per value of one field.

        Only one level is supported: enough for a grouped directory and for the
        report screens that arrive with Sales. A many2many field counts a record
        once per linked value, so group totals can exceed the record count.
        """
        self.check_access("read")
        field = self._fields.get(groupby)
        if field is None:
            raise DomainError(f"{self._name} has no field {groupby!r}")
        compiler = Compiler(self)
        where = sql.SQL(compiler.sql(self._default_scope(domain)))
        params = list(compiler.params)

        if isinstance(field, f.Many2many):
            owner, target = field.relation_columns(self)
            relation = sql.SQL("{}.{}").format(
                sql.Identifier(self._schema or "core"),
                sql.Identifier(field.relation_name(self)),
            )
            value_sql = sql.SQL("rel.{}").format(sql.Identifier(target))
            query = sql.SQL(
                "SELECT {value} AS value, count(*) FROM {table} "
                "JOIN {relation} rel ON rel.{owner} = id "
                "WHERE {where} GROUP BY {value} ORDER BY 2 DESC, 1"
            ).format(
                value=value_sql,
                table=self.from_clause(),
                relation=relation,
                owner=sql.Identifier(owner),
                where=where,
            )
        else:
            column = sql.SQL("{}").format(sql.Identifier(groupby))
            query = sql.SQL(
                "SELECT {column} AS value, count(*) FROM {table} "
                "WHERE {where} GROUP BY {column} ORDER BY 2 DESC, 1"
            ).format(column=column, table=self.from_clause(), where=where)

        if limit is not None:
            query = sql.SQL("{} LIMIT %s").format(query)
            params.append(int(limit))
        rows = self.env.db.fetch_all(query, params)

        labels: dict[int, str] = {}
        if isinstance(field, (f.Many2one, f.Many2many)):
            comodel = self.env[field.comodel]
            ids = [int(row[0]) for row in rows if row[0] is not None]
            labels = comodel.name_by_ids(ids)
        selection = dict(field.selection) if isinstance(field, f.Selection) else {}
        no_value_label = (
            f"No {field.string.lower()}" if field.string else "Not set"
        )

        groups: list[dict[str, Any]] = []
        for raw, count in rows:
            value: Any = raw
            if isinstance(field, (f.Many2one, f.Many2many)):
                value = int(raw) if raw is not None else False
                label = (
                    labels.get(int(raw))
                    if raw is not None
                    else no_value_label
                )
            elif isinstance(field, f.Selection):
                label = selection.get(raw, "Not set" if raw is None else str(raw))
            elif isinstance(field, f.Boolean):
                label = "Yes" if raw else "No"
            elif raw is None or raw == "":
                label = "Not set"
            else:
                label = str(raw)
            groups.append({"value": value, "label": label or "Not set", "count": int(count)})
        return groups

    def read(self, ids: Iterable[int], fields: Sequence[str] | None = None) -> list[dict[str, Any]]:
        self.check_access("read")
        ids = [int(i) for i in ids]
        if not ids:
            return []
        names = list(fields) if fields else list(self._fields)
        for name in names:
            if name != "id" and name not in self._fields:
                raise ValidationError(f"{self._name} has no field {name!r}")
        columns = [
            "id",
            *[
                n
                for n in names
                if n != "id"
                and not isinstance(self._fields[n], (f.Many2many, f.One2many))
            ],
        ]
        where: sql.Composable = sql.SQL("id = ANY(%s)")
        params: list[Any] = [ids]
        rule = self.env.rule_domain(self._name, "read")
        if rule:
            compiler = Compiler(self)
            where = sql.SQL("id = ANY(%s) AND ({})").format(
                sql.SQL(compiler.sql(rule))
            )
            params.extend(compiler.params)
        query = sql.SQL("SELECT {} FROM {} WHERE {}").format(
            sql.SQL(", ").join(sql.Identifier(c) for c in columns),
            self.from_clause(),
            where,
        )
        rows = self.env.db.fetch_all(query, params)
        by_id = {row[0]: dict(zip(columns, row)) for row in rows}
        result: list[dict[str, Any]] = []
        for record_id in ids:
            row = by_id.get(record_id)
            if row is not None:
                result.append(row)
        self._expand_many(result)
        self._expand_many2many(result, names)
        return self._expand_one2many(result, names)

    def _expand_one2many(
        self, rows: list[dict[str, Any]], names: Sequence[str]
    ) -> list[dict[str, Any]]:
        targets = [n for n in names if isinstance(self._fields.get(n), f.One2many)]
        if not rows or not targets:
            return rows
        owner_ids = [row["id"] for row in rows]
        for name in targets:
            field = self._fields[name]
            assert isinstance(field, f.One2many)
            child = self.env[field.comodel]
            child_ids = child.search([(field.inverse, "in", owner_ids)], order="id")
            child_rows = child.read(child_ids)
            grouped: dict[int, list[dict[str, Any]]] = {}
            for row in child_rows:
                parent = row.get(field.inverse)
                parent_id = parent.get("id") if isinstance(parent, dict) else parent
                if parent_id:
                    grouped.setdefault(int(parent_id), []).append(row)
            for row in rows:
                row[name] = grouped.get(row["id"], [])
        return rows

    def lock(self, ids: Iterable[int]) -> list[int]:
        """Lock rows for the duration of the active transaction.

        Reservation uses this to stop two pickings taking the same quant. Call
        it from inside a request or job transaction; outside one PostgreSQL
        releases the lock at the end of the statement.
        """
        record_ids = [int(record_id) for record_id in ids]
        if not record_ids:
            return []
        query = sql.SQL(
            "SELECT id FROM {} WHERE id = ANY(%s) ORDER BY id FOR UPDATE"
        ).format(self.from_clause())
        return [row[0] for row in self.env.db.fetch_all(query, (record_ids,))]

    def _expand_many(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Expand many2one values in one query per field, never one per row."""
        for name, field in self._fields.items():
            if not isinstance(field, f.Many2one):
                continue
            values = {row.get(name) for row in rows if row.get(name)}
            if not values:
                continue
            labels = self.env[field.comodel].name_by_ids(values)
            for row in rows:
                value = row.get(name)
                if value:
                    row[name] = {
                        "id": value,
                        "name": labels.get(value, f"{field.comodel},{value}"),
                    }
        return rows

    def _expand_many2many(
        self, rows: list[dict[str, Any]], names: Sequence[str]
    ) -> list[dict[str, Any]]:
        targets = [n for n in names if isinstance(self._fields.get(n), f.Many2many)]
        if not rows or not targets:
            return rows
        owner_ids = [row["id"] for row in rows]
        schema = sql.Identifier(self._schema or "core")
        for name in targets:
            field = self._fields[name]
            assert isinstance(field, f.Many2many)
            owner, target = field.relation_columns(self)
            query = sql.SQL(
                "SELECT {}, {} FROM {}.{} WHERE {} = ANY(%s) ORDER BY {}, {}"
            ).format(
                sql.Identifier(owner),
                sql.Identifier(target),
                schema,
                sql.Identifier(field.relation_name(self)),
                sql.Identifier(owner),
                sql.Identifier(owner),
                sql.Identifier(target),
            )
            links = self.env.db.fetch_all(query, (owner_ids,))
            grouped: dict[int, list[int]] = {}
            for row_owner, row_target in links:
                grouped.setdefault(row_owner, []).append(row_target)
            all_targets = [tid for values in grouped.values() for tid in values]
            labels = self.env[field.comodel].name_by_ids(all_targets) if all_targets else {}
            for row in rows:
                row[name] = [
                    {"id": tid, "name": labels.get(tid, f"{field.comodel},{tid}")}
                    for tid in grouped.get(row["id"], [])
                ]
        return rows

    def name_by_ids(self, ids: Iterable[int]) -> dict[int, str]:
        ids = [int(i) for i in ids]
        if not ids:
            return {}
        rec_name = self._rec_name if self._rec_name in self._fields else "id"
        column = sql.Identifier(rec_name)
        query = sql.SQL("SELECT id, {} FROM {} WHERE id = ANY(%s)").format(column, self.from_clause())
        rows = self.env.db.fetch_all(query, (ids,))
        labels: dict[int, str] = {}
        for record_id, value in rows:
            labels[record_id] = str(value) if value not in (None, "") else f"{self._name},{record_id}"
        return labels

    def fields_get(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for name, field in self._fields.items():
            entry: dict[str, Any] = {
                "type": field.type,
                "string": field.string or name.replace("_id", "").replace("_", " ").title(),
                "required": field.required,
                "readonly": field.readonly,
            }
            if isinstance(field, f.Selection):
                entry["selection"] = field.selection
            if isinstance(field, f.Many2one):
                entry["relation"] = field.comodel
            if isinstance(field, f.Many2many):
                entry["relation"] = field.comodel
                entry["multiple"] = True
            if isinstance(field, f.One2many):
                entry["relation"] = field.comodel
                entry["inverse"] = field.inverse
                entry["multiple"] = True
            result[name] = entry
        return result

    # -- writing -----------------------------------------------------------
    def create(self, values: dict[str, Any]) -> int:
        self.check_access("create")
        many2many = self._many2many_values(values)
        one2many = self._one2many_values(values)
        data = self._prepare_values(
            {
                name: value
                for name, value in values.items()
                if name not in many2many and name not in one2many
            },
            creating=True,
        )
        rule = self.env.rule_domain(self._name, "create")
        if rule and not domain_matches_values(rule, data):
            raise AccessError(
                f"{(self.env.user or {}).get('login', 'This user')} may not create "
                f"{self._description.lower()} in that company"
            )
        columns = list(data)
        query = sql.SQL("INSERT INTO {} ({}) VALUES ({}) RETURNING id").format(
            self.from_clause(),
            sql.SQL(", ").join(sql.Identifier(c) for c in columns),
            sql.SQL(", ").join(sql.Placeholder() for _ in columns),
        )
        row = self.env.db.fetch_one(query, [data[c] for c in columns])
        if row is None:  # pragma: no cover - defensive
            raise ValidationError("insert returned no id")
        new_id = row[0]
        self._write_many2many([new_id], many2many)
        self._write_one2many([new_id], one2many)
        return new_id

    def write(self, ids: Iterable[int], values: dict[str, Any]) -> int:
        self.check_access("write")
        ids = [int(i) for i in ids]
        if not ids:
            return 0
        self._check_rule(ids, "write")
        many2many = self._many2many_values(values)
        one2many = self._one2many_values(values)
        data = self._prepare_values(
            {
                name: value
                for name, value in values.items()
                if name not in many2many and name not in one2many
            },
            creating=False,
        )
        updated = len(ids)
        if data:
            assignments = sql.SQL(", ").join(
                sql.SQL("{} = %s").format(sql.Identifier(c)) for c in data
            )
            query = sql.SQL("UPDATE {} SET {} WHERE id = ANY(%s)").format(
                self.from_clause(), assignments
            )
            updated = self.env.db.execute(query, [*data.values(), ids])
        self._write_many2many(ids, many2many)
        self._write_one2many(ids, one2many)
        return updated

    def _one2many_values(
        self, values: dict[str, Any]
    ) -> dict[str, tuple[f.One2many, list[dict[str, Any]]]]:
        result: dict[str, tuple[f.One2many, list[dict[str, Any]]]] = {}
        for name, value in values.items():
            field = self._fields.get(name)
            if isinstance(field, f.One2many) and isinstance(value, list):
                result[name] = (
                    field,
                    [dict(item) for item in value if isinstance(item, dict)],
                )
        return result

    def _write_one2many(
        self,
        ids: list[int],
        groups: dict[str, tuple[f.One2many, list[dict[str, Any]]]],
    ) -> None:
        for field, children in groups.values():
            child_model = self.env[field.comodel]
            for owner_id in ids:
                kept: dict[int, dict[str, Any]] = {}
                added: list[dict[str, Any]] = []
                for item in children:
                    record_id = item.pop("id", None)
                    if record_id in (None, "", False):
                        added.append(item)
                    else:
                        kept[int(record_id)] = item
                existing = child_model.search([(field.inverse, "=", owner_id)])
                removed = [record_id for record_id in existing if record_id not in kept]
                if removed:
                    child_model.unlink(removed)
                for record_id, values in kept.items():
                    child_model.write([record_id], values)
                for values in added:
                    child_model.create({**values, field.inverse: owner_id})

    def _many2many_values(self, values: dict[str, Any]) -> dict[str, list[int]]:
        result: dict[str, list[int]] = {}
        for name, value in values.items():
            field = self._fields.get(name)
            if not isinstance(field, f.Many2many):
                continue
            if value is None:
                result[name] = []
            else:
                result[name] = [
                    int(item["id"] if isinstance(item, dict) else item) for item in value
                ]
        return result

    def _write_many2many(self, ids: list[int], values: dict[str, list[int]]) -> None:
        if not values:
            return
        schema = sql.Identifier(self._schema or "core")
        for name, targets in values.items():
            field = self._fields[name]
            assert isinstance(field, f.Many2many)
            owner, target = field.relation_columns(self)
            relation = sql.SQL("{}.{}").format(
                schema, sql.Identifier(field.relation_name(self))
            )
            self.env.db.execute(
                sql.SQL("DELETE FROM {} WHERE {} = ANY(%s)").format(
                    relation, sql.Identifier(owner)
                ),
                (ids,),
            )
            for owner_id in ids:
                for target_id in dict.fromkeys(targets):
                    self.env.db.execute(
                        sql.SQL("INSERT INTO {} ({}, {}) VALUES (%s, %s)").format(
                            relation, sql.Identifier(owner), sql.Identifier(target)
                        ),
                        (owner_id, target_id),
                    )

    def unlink(self, ids: Iterable[int]) -> int:
        self.check_access("unlink")
        ids = [int(i) for i in ids]
        if not ids:
            return 0
        self._check_rule(ids, "unlink")
        query = sql.SQL("DELETE FROM {} WHERE id = ANY(%s)").format(self.from_clause())
        return self.env.db.execute(query, (ids,))

    def _check_rule(self, ids: list[int], mode: str) -> None:
        """Refuse to change rows the user's record rules do not reach."""
        rule = self.env.rule_domain(self._name, mode)
        if not rule:
            return
        compiler = Compiler(self)
        where = compiler.sql(["&", ("id", "in", list(set(ids))), *rule])
        query = sql.SQL("SELECT count(*) FROM {} WHERE {}").format(
            self.from_clause(), sql.SQL(where)
        )
        row = self.env.db.fetch_one(query, compiler.params)
        if (int(row[0]) if row else 0) != len(set(ids)):
            raise AccessError(
                f"{(self.env.user or {}).get('login', 'This user')} may not {mode} "
                f"these {self._description.lower()} records"
            )

    def _prepare_values(self, values: dict[str, Any], *, creating: bool) -> dict[str, Any]:
        data: dict[str, Any] = {}
        for name, value in values.items():
            if name == "id":
                continue
            field = self._fields.get(name)
            if field is None:
                raise ValidationError(f"{self._name} has no field {name!r}")
            if isinstance(field, f.Many2one) and isinstance(value, dict):
                value = value.get("id")
            if field.required and (
                value is None or (isinstance(value, str) and not value.strip())
            ):
                raise ValidationError(f"{field.string or name} is required")
            data[name] = field.to_sql(value)
        for name, field in self._fields.items():
            if isinstance(field, f.Many2many):
                continue
            if name in data or not creating:
                continue
            if field.default is not None:
                data[name] = field.to_sql(field.default_value())
            elif field.required:
                raise ValidationError(f"{field.string or name} is required")
        if "create_uid" in self._fields:
            if creating:
                data["create_uid"] = self.env.uid
                data["create_date"] = dt.datetime.now(dt.UTC)
            data["write_uid"] = self.env.uid
            data["write_date"] = dt.datetime.now(dt.UTC)
        return data

    # -- records -----------------------------------------------------------
    def browse(self, ids: int | Iterable[int]) -> Record | list[Record]:
        if isinstance(ids, int):
            return Record(self, ids)
        return [Record(self, int(i)) for i in ids]

    def display_name(self) -> str:
        return self._description or self._name


class Record:
    """A single row with lazy field access and change tracking."""

    def __init__(self, model: BaseModel, record_id: int):
        object.__setattr__(self, "_model", model)
        object.__setattr__(self, "id", record_id)
        object.__setattr__(self, "_values", None)
        object.__setattr__(self, "_dirty", {})

    # -- loading -----------------------------------------------------------
    def _load(self) -> dict[str, Any]:
        values = self._values
        if values is None:
            rows = self._model.read([self.id])
            values = rows[0] if rows else {}
            object.__setattr__(self, "_values", values)
        return values

    def _get(self, name: str) -> Any:
        if name in self._dirty:
            return self._dirty[name]
        return self._load().get(name)

    def _set(self, name: str, value: Any) -> None:
        if name == "id":
            raise AttributeError("id is immutable")
        if name not in self._model._fields:
            raise AttributeError(f"{self._model._name} has no field {name!r}")
        self._dirty[name] = value

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        if name in self._model._fields:
            return self._get(name)
        raise AttributeError(name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_") or name == "id":
            object.__setattr__(self, name, value)
        else:
            self._set(name, value)

    # -- persistence -------------------------------------------------------
    def write(self, values: dict[str, Any] | None = None) -> bool:
        payload = dict(self._dirty)
        if values:
            payload.update(values)
        if not payload:
            return True
        self._model.write([self.id], payload)
        object.__setattr__(self, "_values", None)
        object.__setattr__(self, "_dirty", {})
        return True

    def unlink(self) -> bool:
        return bool(self._model.unlink([self.id]))

    @property
    def display_name(self) -> str:
        value = self._get("name") if "name" in self._model._fields else None
        return str(value) if value else f"{self._model._name},{self.id}"

    def __repr__(self) -> str:
        return f"<{self._model._name}({self.id}) {self.display_name}>"
