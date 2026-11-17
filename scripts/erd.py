"""Print the database ERD as a Mermaid diagram, generated from the SQLAlchemy models.

Run from services/api so the app imports:
    cd services/api && .venv/bin/python ../../scripts/erd.py > erd.mmd
Only key columns are shown (primary and foreign keys); every column is in the models.
"""

import os
import sys

# The models import settings; any syntactically valid URL will do, nothing connects.
os.environ.setdefault("DATABASE_URL", "postgresql://erd:erd@localhost/erd")
sys.path.insert(0, os.getcwd())

import app.main  # noqa: E402, F401  # registers every module's models on Base
from app.core.db import Base  # noqa: E402


def main() -> None:
    lines = ["erDiagram"]
    for table in Base.metadata.sorted_tables:
        lines.append(f"    {table.name} {{")
        for column in table.columns:
            keys = (["PK"] if column.primary_key else []) + (["FK"] if column.foreign_keys else [])
            if keys:
                type_name = type(column.type).__name__.lower()
                lines.append(f"        {type_name} {column.name} {','.join(keys)}")
        lines.append("    }")
    for table in Base.metadata.sorted_tables:
        for key in sorted(table.foreign_keys, key=lambda fk: fk.parent.name):
            # A nullable key: the row may have no parent. Either way a parent has 0..n rows.
            parent = "|o" if key.parent.nullable else "||"
            lines.append(
                f'    {key.column.table.name} {parent}--o{{ {table.name} : "{key.parent.name}"'
            )
    print("\n".join(lines))


if __name__ == "__main__":
    main()
