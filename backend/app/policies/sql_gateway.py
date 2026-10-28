"""Restricted SQL front door. SQLGlot is used ONLY as a parser; the user's SQL text
is never executed. Supported shape (everything else is rejected):

  SELECT <columns | *> FROM customers
  [WHERE col <op> literal [AND ...]]  (op: = != < <= > >=)
  [ORDER BY col [ASC|DESC]] [LIMIT n<=50]

Joins, subqueries, CTEs, UNION, GROUP BY, DISTINCT, functions, expressions,
aliases and comments are rejected rather than guessed at."""
from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

MAX_LIMIT = 50
ALLOWED_TABLES = {"customers"}
OPS = {exp.EQ: "=", exp.NEQ: "!=", exp.GT: ">", exp.GTE: ">=", exp.LT: "<", exp.LTE: "<="}


class UnsupportedQuery(ValueError):
    pass


@dataclass
class ParsedQuery:
    table: str
    columns: list[str]  # empty list == SELECT *
    star: bool = False
    filters: list[tuple[str, str, object]] = field(default_factory=list)
    order_by: tuple[str, bool] | None = None  # (column, descending)
    limit: int = MAX_LIMIT


def _col(node) -> str:
    if not isinstance(node, exp.Column) or node.table or node.args.get("join_mark"):
        raise UnsupportedQuery("Only plain column names are supported (no qualified names or expressions).")
    return node.name.lower()


def _literal(node):
    if isinstance(node, exp.Neg) and isinstance(node.this, exp.Literal):
        v = _literal(node.this)
        return -v
    if not isinstance(node, exp.Literal):
        raise UnsupportedQuery("Filter values must be literals.")
    if node.is_string:
        return node.this
    try:
        return int(node.this)
    except ValueError:
        return float(node.this)


def _flatten_and(node) -> list:
    if isinstance(node, exp.And):
        return _flatten_and(node.left) + _flatten_and(node.right)
    if isinstance(node, exp.Paren):
        return _flatten_and(node.this)
    return [node]


def parse_query(sql: str) -> ParsedQuery:
    if not sql or len(sql) > 500:
        raise UnsupportedQuery("Query is empty or too long.")
    if "--" in sql or "/*" in sql or ";" in sql.strip().rstrip(";"):
        raise UnsupportedQuery("Comments and multiple statements are not supported.")
    try:
        stmts = sqlglot.parse(sql, read="postgres")
    except SqlglotError:
        raise UnsupportedQuery("Could not parse the query.") from None
    if len(stmts) != 1 or not isinstance(stmts[0], exp.Select):
        raise UnsupportedQuery("Only a single SELECT statement is supported.")
    q: exp.Select = stmts[0]

    allowed_keys = {"expressions", "from", "where", "order", "limit"}
    extra = [k for k, v in q.args.items() if v and k not in allowed_keys]
    if extra:
        raise UnsupportedQuery(f"Unsupported clause: {', '.join(sorted(extra))}.")
    if any(q.find(n) for n in (exp.Subquery, exp.Join, exp.Union, exp.Func)) :
        raise UnsupportedQuery("Joins, subqueries, set operations and functions are not supported.")

    frm = q.args.get("from")
    table = frm.this if frm is not None else None
    if not isinstance(table, exp.Table) or table.args.get("db") or table.alias:
        raise UnsupportedQuery("Query must select from a single un-aliased table.")
    if table.name.lower() not in ALLOWED_TABLES:
        raise UnsupportedQuery("Table is not available through the gateway.")

    parsed = ParsedQuery(table=table.name.lower(), columns=[])
    for e in q.expressions:
        if isinstance(e, exp.Star):
            parsed.star = True
        else:
            parsed.columns.append(_col(e))
    if parsed.star and parsed.columns:
        raise UnsupportedQuery("Mixing * with named columns is not supported.")
    if not parsed.star and not parsed.columns:
        raise UnsupportedQuery("No columns selected.")

    where = q.args.get("where")
    if where is not None:
        for cond in _flatten_and(where.this):
            op = OPS.get(type(cond))
            if op is None:
                raise UnsupportedQuery("Only AND-ed comparisons (=, !=, <, <=, >, >=) are supported in WHERE.")
            parsed.filters.append((_col(cond.left), op, _literal(cond.right)))

    order = q.args.get("order")
    if order is not None:
        if len(order.expressions) != 1:
            raise UnsupportedQuery("Only a single ORDER BY column is supported.")
        o = order.expressions[0]
        parsed.order_by = (_col(o.this), bool(o.args.get("desc")))

    limit = q.args.get("limit")
    if limit is not None:
        n = _literal(limit.expression)
        if not isinstance(n, int) or n < 1:
            raise UnsupportedQuery("LIMIT must be a positive integer.")
        parsed.limit = min(n, MAX_LIMIT)
    return parsed
