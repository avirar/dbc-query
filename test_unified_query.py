#!/usr/bin/env python3
"""
Test script for WoW unified game data queries.
Tests both DBC and SQL database integration.
"""

import json
import os
from server import DBCQueryMCP

# Set up environment variables (override with your actual paths)
os.environ["DBC_PATH"] = "/home/luke/GIT/azerothcore-wotlk/env/dist/bin/dbc"
os.environ["DBC_FORMAT_FILE"] = (
    "/home/luke/GIT/azerothcore-wotlk/src/server/shared/DataStores/DBCfmt.h"
)
os.environ["DB_HOST"] = "localhost"
os.environ["DB_PORT"] = "3306"
os.environ["DB_USER"] = "acore"
os.environ["DB_PASSWORD"] = "abc"


def test_query_dbc():
    """Test querying DBC files directly."""
    print("=" * 60)
    print("TEST 1: Query DBC file (AreaTable)")
    print("=" * 60)

    server = DBCQueryMCP()
    result = server._query_dbc({"dbc_name": "AreaTable", "id": 1})
    print(json.dumps(result, indent=2))
    return result


def test_list_dbcs():
    """Test listing available DBC files."""
    print("\n" + "=" * 60)
    print("TEST 2: List available DBC files (search 'Area')")
    print("=" * 60)

    server = DBCQueryMCP()
    result = server._list_dbcs({"search": "Area"})
    print(json.dumps(result, indent=2))
    return result


def test_describe_fields():
    """Test field description for a DBC."""
    print("\n" + "=" * 60)
    print("TEST 3: Describe fields for AreaTable")
    print("=" * 60)

    server = DBCQueryMCP()
    result = server._describe_fields({"dbc_name": "AreaTable"})
    if "result" in result and "fields" in result["result"]:
        print(f"Total fields: {result['result']['field_count']}")
        print("First 5 fields:")
        for field in result["result"]["fields"][:5]:
            print(f"  [{field['index']}] {field['name']} ({field['type']})")
    return result


def test_query_game_data_dbc_only():
    """Test unified query with DBC only."""
    print("\n" + "=" * 60)
    print("TEST 4: Unified game data query (AreaTable)")
    print("=" * 60)

    server = DBCQueryMCP()
    result = server._query_game_data({"dbc_name": "AreaTable", "id": 1})
    print(json.dumps(result, indent=2))
    return result


def test_query_game_data_with_db():
    """Test unified query with both DBC and DB."""
    print("\n" + "=" * 60)
    print("TEST 5: Unified game data query (Spell)")
    print("=" * 60)

    server = DBCQueryMCP()
    result = server._query_game_data({"dbc_name": "Spell", "id": 1})
    print(json.dumps(result, indent=2))
    return result


def test_list_tools():
    """Test listing all available tools."""
    print("\n" + "=" * 60)
    print("TEST 6: List all MCP tools")
    print("=" * 60)

    server = DBCQueryMCP()
    tools = server.list_tools()
    for tool in tools:
        print(f"\nTool: {tool['name']}")
        print(f"  Description: {tool['description'][:100]}...")
    return tools


if __name__ == "__main__":
    try:
        test_list_tools()
        test_describe_fields()
        test_list_dbcs()
        test_query_dbc()
        test_query_game_data_dbc_only()
        test_query_game_data_with_db()

        print("\n" + "=" * 60)
        print("ALL TESTS COMPLETED")
        print("=" * 60)
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback

        traceback.print_exc()
