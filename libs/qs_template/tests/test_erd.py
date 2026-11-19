"""ERD generation: deterministic Mermaid output straight from the table definitions."""

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    Numeric,
    Table,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB

from qs_template.erd import mermaid_erd

metadata = MetaData()
Table(
    "parent",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("code", Text, nullable=False, unique=True),
    Column("price", Numeric(23, 8), nullable=False),
    Column("ratio", Float),
)
Table(
    "child",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("parent_id", Uuid, ForeignKey("parent.id"), nullable=False),
    Column("other_parent_id", Uuid, ForeignKey("parent.id")),
    Column("payload", JSONB, nullable=False),
    Column("seen_at", DateTime(timezone=True)),
)


def test_the_diagram_lists_tables_columns_keys_and_relationships() -> None:
    assert mermaid_erd(metadata, title="sample") == (
        "---\n"
        "title: sample\n"
        "---\n"
        "erDiagram\n"
        '    parent |o--o{ child : "other_parent_id"\n'
        '    parent ||--o{ child : "parent_id"\n'
        "    child {\n"
        "        int id PK\n"
        "        uuid parent_id FK\n"
        '        uuid other_parent_id FK "optional"\n'
        "        jsonb payload\n"
        '        timestamptz seen_at "optional"\n'
        "    }\n"
        "    parent {\n"
        "        uuid id PK\n"
        "        text code UK\n"
        '        numeric price "23,8"\n'
        '        float8 ratio "optional"\n'
        "    }\n"
    )


def test_output_is_identical_on_every_run_and_honours_exclusions() -> None:
    assert mermaid_erd(metadata) == mermaid_erd(metadata)
    assert "child" not in mermaid_erd(metadata, exclude=frozenset({"child"}))


def test_documented_references_are_drawn_as_dotted_lines() -> None:
    diagram = mermaid_erd(metadata, references={("parent", "child"): "parent_code"})
    assert '    parent ||..o{ child : "parent_code"' in diagram
