"""Entity-relationship diagrams generated from a service's SQLAlchemy tables.

The diagram is derived from the same table definitions the migrations are tested
against, so it cannot drift from the real schema: each service commits the generated
Mermaid file and a test regenerates it and fails when the committed copy differs.

    print(mermaid_erd(metadata, messaging_metadata, title="market_db"))

Output is deterministic: tables sorted by name, columns in definition order,
relationships sorted, one foreign key per relationship line.
"""

from collections.abc import Mapping

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import TypeEngine


def _type_name(column_type: TypeEngine[object]) -> tuple[str, str]:
    """Mermaid type word and an optional detail (precision) for the comment."""
    if isinstance(column_type, Numeric) and not isinstance(column_type, Float):
        detail = (
            f"{column_type.precision},{column_type.scale}"
            if column_type.precision is not None
            else ""
        )
        return "numeric", detail
    if isinstance(column_type, Float):
        return "float8", ""
    if isinstance(column_type, Uuid):
        return "uuid", ""
    if isinstance(column_type, BigInteger):
        return "bigint", ""
    if isinstance(column_type, Integer):
        return "int", ""
    if isinstance(column_type, Boolean):
        return "bool", ""
    if isinstance(column_type, DateTime):
        return ("timestamptz" if column_type.timezone else "timestamp"), ""
    if isinstance(column_type, Date):
        return "date", ""
    if isinstance(column_type, JSONB):
        return "jsonb", ""
    if isinstance(column_type, Text | String):
        return "text", ""
    return type(column_type).__name__.lower(), ""


def _single_column_unique(table: Table) -> set[str]:
    names = {c.name for c in table.columns if c.unique}
    for constraint in table.constraints:
        if isinstance(constraint, UniqueConstraint) and len(constraint.columns) == 1:
            names.update(c.name for c in constraint.columns)
    return names


def _column_line(table: Table, column: Column[object], unique: set[str]) -> str:
    type_word, detail = _type_name(column.type)
    keys = []
    if column.primary_key:
        keys.append("PK")
    if column.foreign_keys:
        keys.append("FK")
    if column.name in unique and not column.primary_key:
        keys.append("UK")
    notes = [n for n in (detail, "" if column.nullable is False else "optional") if n]
    if column.primary_key:
        notes = [n for n in notes if n != "optional"]
    line = f"        {type_word} {column.name}"
    if keys:
        line += " " + ", ".join(keys)
    if notes:
        line += f' "{"; ".join(notes)}"'
    return line


def mermaid_erd(
    *metadatas: MetaData,
    title: str | None = None,
    exclude: frozenset[str] = frozenset(),
    references: Mapping[tuple[str, str], str] | None = None,
) -> str:
    """A Mermaid ``erDiagram`` of every table in ``metadatas``.

    ``references`` adds dotted lines for documented references that are deliberately
    not foreign keys (for example into a hypertable), keyed by (parent, child) with the
    column name as the label.
    """
    tables: dict[str, Table] = {}
    for metadata in metadatas:
        for name, table in metadata.tables.items():
            if name not in exclude:
                tables[name] = table

    lines: list[str] = []
    if title:
        lines += ["---", f"title: {title}", "---"]
    lines.append("erDiagram")

    relationships: list[str] = []
    for name in sorted(tables):
        table = tables[name]
        for column in table.columns:
            for foreign_key in sorted(column.foreign_keys, key=lambda fk: fk.target_fullname):
                parent = foreign_key.column.table.name
                if parent not in tables:
                    continue
                left = "|o" if column.nullable else "||"
                relationships.append(f'    {parent} {left}--o{{ {name} : "{column.name}"')
    for (parent, child), label in sorted((references or {}).items()):
        if parent in tables and child in tables:
            relationships.append(f'    {parent} ||..o{{ {child} : "{label}"')
    lines += sorted(relationships)

    for name in sorted(tables):
        table = tables[name]
        unique = _single_column_unique(table)
        lines.append(f"    {name} {{")
        lines += [_column_line(table, column, unique) for column in table.columns]
        lines.append("    }")
    return "\n".join(lines) + "\n"
