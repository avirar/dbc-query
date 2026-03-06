#!/usr/bin/env python3
"""
Direct query script for WoW DBC and SQL data.
Bypasses the MCP server requirement.
"""

import json
import sys
import os
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

# Database configuration
DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = os.environ.get("DB_PORT", "3306")
DB_USER = os.environ.get("DB_USER", "acore")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "abc")

# Table to primary key mapping (not all tables use "ID" as PK)
TABLE_PRIMARY_KEYS = {
    "gameobject_template": "entry",
    "creature_display_info": "display_id",
}


def get_column_names(table_name: str, database: str) -> List[str]:
    """Get column names for a table."""
    try:
        cmd = [
            "mysql",
            "-h",
            DB_HOST,
            "-P",
            DB_PORT,
            "-u",
            DB_USER,
            f"-p{DB_PASSWORD}",
            "-D",
            database,
            "-e",
            f"DESCRIBE `{table_name}`",
            "--batch",
            "--skip-column-names",
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

        if result.returncode != 0:
            return []

        columns = []
        for line in result.stdout.strip().split("\n"):
            if line:
                parts = line.split("\t")
                if parts:
                    columns.append(parts[0])

        return columns

    except Exception:
        return []


def query_sql(
    table_name: str,
    database: str,
    id_val: Optional[int] = None,
    filter_dict: Optional[Dict[str, Any]] = None,
    limit: int = 10,
) -> Dict[str, Any]:
    """Query SQL database directly."""

    try:
        # Get primary key for table
        pk_column = TABLE_PRIMARY_KEYS.get(table_name, "ID")

        sql_parts = [f"SELECT * FROM `{table_name}`"]

        where_clauses = []
        if id_val is not None:
            where_clauses.append(f"`{pk_column}` = {id_val}")

        # Add filter conditions
        if filter_dict:
            for column, value in filter_dict.items():
                if isinstance(value, str):
                    escaped_value = value.replace("'", "''")
                    where_clauses.append(f"`{column}` = '{escaped_value}'")
                else:
                    where_clauses.append(f"`{column}` = {value}")

        if where_clauses:
            sql_parts.append("WHERE " + " AND ".join(where_clauses))

        sql_parts.append(f"LIMIT {limit}")
        sql = " ".join(sql_parts)

        cmd = [
            "mysql",
            "-h",
            DB_HOST,
            "-P",
            DB_PORT,
            "-u",
            DB_USER,
            f"-p{DB_PASSWORD}",
            "-D",
            database,
            "-e",
            sql,
            "--batch",
            "--skip-column-names",
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode != 0:
            return {"error": result.stderr.strip(), "data": []}

        # Get column names
        columns = get_column_names(table_name, database)

        # Parse TSV output
        lines = result.stdout.strip().split("\n")
        data = []
        for line in lines:
            if line:
                values = line.split("\t")
                # Try to convert to int if possible
                converted = []
                for v in values:
                    try:
                        converted.append(int(v))
                    except ValueError:
                        converted.append(v)

                if columns:
                    row_dict = {
                        col: converted[i]
                        for i, col in enumerate(columns)
                        if i < len(converted)
                    }
                    data.append(row_dict)
                else:
                    data.append(converted)

        return {"data": data, "row_count": len(data), "columns": columns}

    except Exception as e:
        return {"error": str(e), "data": []}


def main():
    """Main entry point."""
    if len(sys.argv) < 3:
        print(
            "Usage: query_direct.py <table> <database> [--id <val>] [--filter '<col>=<val>' ...] [--limit <val>]"
        )
        print("Examples:")
        print("  query_direct.py gameobject_template acore_world --id 161557")
        print("  query_direct.py quest_template acore_world --id 3904")
        print(
            "  query_direct.py gameobject_template acore_world --filter 'name=Milly' --limit 10"
        )
        sys.exit(1)

    table = sys.argv[1]
    database = sys.argv[2]

    # Parse optional arguments
    query_id: Optional[int] = None
    limit = 1
    filters: Dict[str, Any] = {}

    i = 3
    while i < len(sys.argv):
        if sys.argv[i] == "--id" and i + 1 < len(sys.argv):
            query_id = int(sys.argv[i + 1])
            i += 2
        elif sys.argv[i] == "--filter" and i + 1 < len(sys.argv):
            # Parse filter like 'column=value'
            filter_str = sys.argv[i + 1]
            if "=" in filter_str:
                col, val = filter_str.split("=", 1)
                # Try to convert to int
                try:
                    filters[col.strip()] = int(val.strip())
                except ValueError:
                    filters[col.strip()] = val.strip()
            i += 2
        elif sys.argv[i] == "--limit" and i + 1 < len(sys.argv):
            limit = int(sys.argv[i + 1])
            i += 2
        else:
            i += 1

    result = query_sql(
        table, database, id_val=query_id, filter_dict=filters, limit=limit
    )

    # Pretty print JSON output
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
