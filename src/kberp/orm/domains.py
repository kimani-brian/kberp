"""Domain (search filter) compiler: Odoo domain lists to parameterised SQL."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from . import fields as f

OPS = {
    "=": "=",
    "!=": "<>",
    ">": ">",
    ">=": ">=",
    "<": "<",
    "<=": "<=",
}

SQL_OPS = {
    "=": "=",
    "!=": "<>",
    ">": ">",
    ">=": ">=",
    "<": "<",
    "<=": "<=",
    "like": "LIKE",
    "not like": "NOT LIKE",
    "ilike": "ILIKE",
    "not ilike": "NOT ILIKE",
    "=like": "LIKE",
    "=ilike": "ILIKE",
}

HIDDEN_FIELDS = {"id"}


class DomainError(ValueError):
    pass


class Compiler:
    def __init__(self, model) -> None:
        self.model = model
        self.params: list[Any] = []

    # -- public ------------------------------------------------------------
    def sql(self, domain: Sequence[Any] | None) -> str:
        if not domain:
            return "TRUE"
        tokens = list(domain)
        fragments: list[str] = []
        index = 0
        while index < len(tokens):
            fragment, index = self._parse(tokens, index)
            fragments.append(fragment)
        if len(fragments) == 1:
            return fragments[0]
        return "(" + " AND ".join(fragments) + ")"

    # -- internals ---------------------------------------------------------
    def _parse(self, tokens: list[Any], index: int) -> tuple[str, int]:
        if index >= len(tokens):
            raise DomainError("unexpected end of domain")
        token = tokens[index]
        if token == "!":
            inner, index = self._parse(tokens, index + 1)
            return f"(NOT {inner})", index
        if token in ("&", "|"):
            left, index = self._parse(tokens, index + 1)
            right, index = self._parse(tokens, index)
            op = "AND" if token == "&" else "OR"
            return f"({left} {op} {right})", index
        if isinstance(token, (tuple, list)):
            return self._leaf(token), index + 1
        raise DomainError(f"invalid domain token: {token!r}")

    def _leaf(self, leaf: Sequence[Any]) -> str:
        if len(leaf) == 2:
            name, value = leaf
            op = "="
        elif len(leaf) == 3:
            name, op, value = leaf
        else:
            raise DomainError(f"invalid leaf: {leaf!r}")

        field = self.model._fields.get(name)
        if op in ("child_of", "parent_of"):
            return self._hierarchy(field, op, value)
        if isinstance(field, f.Many2many):
            return self._many2many(field, op, value)
        column = self._column(name)

        # In Odoo a `False` compared against a many2one means "no value".
        if value is False and field is not None and field.type != "boolean":
            value = None

        if op in ("in", "not in"):
            return self._in(column, op, value)

        if value is None:
            if op == "=":
                return f"{column} IS NULL"
            if op == "!=":
                return f"{column} IS NOT NULL"
            raise DomainError(f"operator {op!r} cannot compare to NULL")

        sql_op = SQL_OPS.get(op)
        if sql_op is None:
            raise DomainError(f"unsupported operator: {op!r}")

        if op in ("like", "ilike", "not like", "not ilike"):
            value = f"%{value}%"
        if op in ("=like", "=ilike"):
            sql_op = SQL_OPS[op[1:]]

        if isinstance(value, bool) or value is None:
            self.params.append(value)
            return f"{column} {sql_op} %s"
        self.params.append(value)
        return f"{column} {sql_op} %s"

    def _in(self, column: str, op: str, value: Any) -> str:
        if value is None:
            return "TRUE" if op == "not in" else "FALSE"
        values = list(value)
        if not values:
            return "FALSE" if op == "in" else "TRUE"
        placeholders = ", ".join(["%s"] * len(values))
        self.params.extend(values)
        keyword = "IN" if op == "in" else "NOT IN"
        return f"{column} {keyword} ({placeholders})"

    def _hierarchy(self, field: Any, op: str, value: Any) -> str:
        raw = value if isinstance(value, (list, tuple, set)) else [value]
        ids = [int(item) for item in raw if item is not None]
        if not ids:
            return "FALSE"
        self.params.append(ids)
        if isinstance(field, f.Many2many):
            comodel = self.model.env[field.comodel]
            owner, target = field.relation_columns(self.model)
            relation = (
                f'"{self.model._schema or "core"}"."{field.relation_name(self.model)}"'
            )
            tree = self._tree_sql(comodel, op)
            return (
                f"EXISTS (SELECT 1 FROM {relation} "
                f"WHERE {owner} = id AND {target} IN ({tree}))"
            )
        if isinstance(field, f.Many2one) and field.comodel != self.model._name:
            comodel = self.model.env[field.comodel]
            return f'"{field.name}" IN ({self._tree_sql(comodel, op)})'
        return f"id IN ({self._tree_sql(self.model, op)})"

    def _tree_sql(self, model, op: str) -> str:
        if "parent_id" not in model._fields:
            raise DomainError(f"{model._name} is not hierarchical")
        schema = model._schema or "core"
        table = f'"{schema}"."{model.table_name()}"'
        if op == "child_of":
            return (
                f"WITH RECURSIVE tree AS ("
                f"SELECT id FROM {table} WHERE id = ANY(%s) "
                f"UNION SELECT child.id FROM {table} child "
                f"JOIN tree ON child.parent_id = tree.id"
                f") SELECT id FROM tree"
            )
        return (
            f"WITH RECURSIVE tree AS ("
            f"SELECT id FROM {table} WHERE id = ANY(%s) "
            f"UNION SELECT parent.id FROM {table} parent "
            f"JOIN tree ON parent.id = tree.parent_id"
            f") SELECT id FROM tree"
        )

    def _many2many(self, field: f.Many2many, op: str, value: Any) -> str:
        if op not in {"=", "!=", "in", "not in"}:
            raise DomainError(f"operator {op!r} is not supported on {field.name}")
        owner, target = field.relation_columns(self.model)
        relation = (
            f'"{self.model._schema or "core"}"."{field.relation_name(self.model)}"'
        )
        linked = f"EXISTS (SELECT 1 FROM {relation} WHERE {owner} = id"
        negative = op in {"!=", "not in"}
        if value is None:
            return f"{linked})" if negative else f"NOT {linked})"
        values = list(value) if op in {"in", "not in"} else [value]
        if not values:
            return "TRUE" if negative else "FALSE"
        placeholders = ", ".join(["%s"] * len(values))
        self.params.extend(values)
        condition = f"{linked} AND {target} IN ({placeholders}))"
        return f"NOT {condition}" if negative else condition

    def _column(self, name: str) -> str:
        if name == "id":
            return "id"
        if name not in self.model._fields:
            raise DomainError(f"{self.model._name} has no field {name!r}")
        return f'"{name}"'


def order_by(model, order: str | None) -> str:
    """Translate an Odoo-style order string into safe SQL."""
    raw = order or model._order or "id"
    parts: list[str] = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        descending = chunk.startswith("-")
        name = chunk[1:] if descending else chunk
        if name != "id" and name not in model._fields:
            raise DomainError(f"{model._name} cannot order by {name!r}")
        direction = "DESC" if descending else "ASC"
        parts.append(('"id"' if name == "id" else f'"{name}"') + f" {direction}")
    return ", ".join(parts) or '"id" ASC'


def domain_matches_values(domain: Sequence[Any], values: dict[str, Any]) -> bool:
    """Evaluate a prefix domain against an unsaved row.

    Used to apply create rules before the row exists. Only the operators that
    make sense for a new record are enforced; anything richer returns True so a
    create is never blocked on a comparison the evaluator cannot model.
    """
    tokens = list(domain)

    def parse(index: int) -> tuple[bool, int]:
        if index >= len(tokens):
            return True, index + 1
        token = tokens[index]
        if token == "&":
            left, nxt = parse(index + 1)
            right, nxt = parse(nxt)
            return (left and right), nxt
        if token == "|":
            left, nxt = parse(index + 1)
            right, nxt = parse(nxt)
            return (left or right), nxt
        if token == "!":
            value, nxt = parse(index + 1)
            return (not value), nxt
        if not isinstance(token, (tuple, list)) or len(token) != 3:
            return True, index + 1
        name, operator, expected = token
        actual = values.get(name)

        def normalise(value: Any) -> Any:
            # A false many2one is stored as NULL; compare them as one value.
            return None if value is False else value

        if operator == "=":
            matched = normalise(actual) == normalise(expected)
        elif operator == "!=":
            matched = normalise(actual) != normalise(expected)
        elif operator == "in":
            matched = normalise(actual) in [normalise(v) for v in (expected or [])]
        elif operator == "not in":
            matched = normalise(actual) not in [normalise(v) for v in (expected or [])]
        else:
            matched = True
        return matched, index + 1

    result, _ = parse(0)
    return result
