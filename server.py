#!/usr/bin/env python3
"""
MCP (Model Context Protocol) server for querying WoW DBC files and SQL datastores.

Provides access to all AzerothCore datastores in the exact same manner as the
server loads them: DBC binary files with SQL overlays, SQL-only ObjectMgr stores,
and SQL manager stores. Includes cross-reference lookup for linking C++ structs
to their underlying data sources.
"""

import json
import sys
import os
import re
import subprocess
import difflib
from pathlib import Path
from typing import Dict, Any, List, Optional, Set, Tuple, Union
from dbc_reader import WDBCReader
from format_parser import FormatParser


class DBCQueryMCP:
    """MCP server for DBC/SQL datastore queries."""

    def __init__(self):
        self.dbc_path = Path(os.environ.get(
            'DBC_PATH',
            '/root/azerothcore-wotlk/env/dist/bin/dbc'
        ))
        self.format_file = os.environ.get(
            'DBC_FORMAT_FILE',
            '/root/azerothcore-wotlk/src/server/shared/DataStores/DBCfmt.h'
        )
        self.db_host = os.environ.get('DB_HOST', '')
        self.db_port = os.environ.get('DB_PORT', '3306')
        self.db_user = os.environ.get('DB_USER', '')
        self.db_password = os.environ.get('DB_PASSWORD', '')
        self.db_name = os.environ.get('DB_NAME', 'acore_world')
        self.db_available = False

        if not self.db_host or not self.db_user:
            self._auto_detect_db_config()

        self.format_parser = FormatParser(self.format_file)
        self.format_parser.parse()

        self.registry = self._load_registry()
        self.dbc_cache: Dict[str, WDBCReader] = {}
        self._pk_cache: Dict[str, str] = {}
        self._schema_cache: Dict[str, Optional[List[Dict]]] = {}
        self._all_tables_cache: Set[str] = set()

        self._db_tables_cache: Dict[str, Set[str]] = {}
        self._table_to_db_cache: Dict[str, List[str]] = {}
        self._db_priority_order = ['acore_world', 'acore_characters', 'acore_auth', 'acore_playerbots']

        self._check_db_connection()
        self._discover_all_tables()

    def _auto_detect_db_config(self):
        for conf_path in [
            '/root/azerothcore-wotlk/env/dist/etc/worldserver.conf',
            os.path.expanduser('~/azerothcore-wotlk/env/dist/etc/worldserver.conf'),
        ]:
            conf = Path(conf_path)
            if not conf.exists():
                continue
            try:
                text = conf.read_text()
                m = re.search(r'^WorldDatabaseInfo\s*=\s*"([^"]+)"', text, re.MULTILINE)
                if m:
                    parts = m.group(1).split(';')
                    if len(parts) >= 5:
                        self.db_host = parts[0]
                        self.db_port = parts[1]
                        self.db_user = parts[2]
                        self.db_password = parts[3]
                        self.db_name = parts[4]
                        print(f"Auto-detected DB config from {conf_path}", file=sys.stderr)
                        return
            except Exception:
                continue
        self.db_host = self.db_host or 'localhost'
        self.db_user = self.db_user or 'root'
        self.db_password = self.db_password or ''

    def _check_db_connection(self):
        rows, error = self._query_database("SELECT 1 AS test")
        if error:
            print(f"Warning: Database connection failed: {error}", file=sys.stderr)
            print(f"  DB config: {self.db_user}@{self.db_host}:{self.db_port}/{self.db_name}", file=sys.stderr)
            print(f"  SQL queries will fail. Set DB_HOST, DB_USER, DB_PASSWORD, DB_NAME env vars.", file=sys.stderr)
            self.db_available = False
        else:
            self.db_available = True
            print(f"Database connected: {self.db_user}@{self.db_host}:{self.db_port}/{self.db_name}", file=sys.stderr)

    def _disconnect_from_db(self, db_name: str):
        try:
            subprocess.run([
                "mysql", "-h", self.db_host, "-P", self.db_port,
                "-u", self.db_user, f"-p{self.db_password}",
                "-D", db_name, "-e", "KILL CONNECTION ID(); -- no-op on disconnect"
            ], capture_output=True, timeout=5)
        except Exception:
            pass

    def _load_all_tables(self):
        """Clear table cache for reloading."""
        self._all_tables_cache.clear()

    def _discover_all_tables(self):
        """Discover all tables across all AzerothCore databases and build routing cache."""
        if not self.db_available:
            print("Skipping table discovery (database unavailable)", file=sys.stderr)
            return

        databases = ['acore_world', 'acore_characters', 'acore_auth', 'acore_playerbots']
        total_tables = 0

        for db in databases:
            rows, error = self._query_database("SHOW TABLES", db_name=db)
            if error:
                print(f"  {db}: unavailable ({error[:50]}...)", file=sys.stderr)
                continue

            tables = set()
            for row in rows:
                table = list(row.values())[0].lower()
                tables.add(table)
                self._all_tables_cache.add(table)
                self._db_tables_cache[db] = tables

                if table not in self._table_to_db_cache:
                    self._table_to_db_cache[table] = []
                self._table_to_db_cache[table].append(db)

            total_tables += len(tables)
            print(f"  {db}: {len(tables)} tables", file=sys.stderr)

        for table, dbs in self._table_to_db_cache.items():
            if len(dbs) > 1:
                self._table_to_db_cache[table] = sorted(dbs, key=lambda x: self._db_priority_order.index(x) if x in self._db_priority_order else 999)

        print(f"Discovered {total_tables} tables across {len(self._db_tables_cache)} databases", file=sys.stderr)

    def _resolve_table_database(self, table_name: str, current_db: str = None) -> Optional[str]:
        """Resolve table name to correct database using cache and priority order."""
        table_lower = table_name.lower()

        if table_lower in self._table_to_db_cache:
            candidates = self._table_to_db_cache[table_lower]
            if current_db and current_db in candidates:
                return current_db

            for db in self._db_priority_order:
                if db in candidates:
                    return db
            return candidates[0] if candidates else None

        if current_db and self._db_tables_cache.get(current_db, set()) and table_lower in self._db_tables_cache[current_db]:
            return current_db

        return None

    def _suggest_similar_tables(self, table_name: str) -> List[str]:
        """Suggest similar table names using prefix/suffix/substring matching."""
        table_lower = table_name.lower()
        suggestions = set()

        exact_matches = difflib.get_close_matches(table_lower, self._all_tables_cache, n=5, cutoff=0.6)
        for t in exact_matches:
            suggestions.add(t)

        words = table_lower.replace('_', ' ').split()
        for word in words:
            if len(word) >= 3:
                prefix_matches = [t for t in self._all_tables_cache if t.startswith(word)]
                suffix_matches = [t for t in self._all_tables_cache if t.endswith(word)]
                substr_matches = [t for t in self._all_tables_cache if word in t.replace('_', ' ')]
                suggestions.update(prefix_matches[:5])
                suggestions.update(suffix_matches[:5])
                suggestions.update(substr_matches[:5])

        if len(suggestions) == 0:
            words = table_lower.split('_')
            for i, w1 in enumerate(words):
                for w2 in words[i+1:]:
                    combined = w1 + w2
                    if len(combined) >= 4:
                        close_matches = [t for t in self._all_tables_cache if combined in t.replace('_', ' ') or t.startswith(w1)]
                        suggestions.update(close_matches[:3])

        sorted_suggestions = sorted(suggestions, key=lambda x: difflib.SequenceMatcher(None, table_lower, x).ratio(), reverse=True)

        return list(sorted(set(sorted_suggestions[:5])))

    def _load_registry(self) -> Dict[str, Any]:
        registry_file = Path(__file__).parent / "datastore_registry.json"
        if not registry_file.exists():
            print(f"Warning: {registry_file} not found", file=sys.stderr)
            return {"entries": {}, "indices": {}}
        try:
            with open(registry_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Warning: Could not load registry: {e}", file=sys.stderr)
            return {"entries": {}, "indices": {}}

    def _resolve_entry(self, name: str) -> Optional[Tuple[str, Dict]]:
        """Resolve a name to (struct_name, entry) using all lookup indices."""
        entries = self.registry.get("entries", {})
        indices = self.registry.get("indices", {})

        # Direct struct name lookup
        if name in entries:
            return name, entries[name]

        # Try each index
        for idx_name in ["by_sql_table", "by_dbc_name", "by_dbc_file", "by_store_variable"]:
            idx = indices.get(idx_name, {})
            if name in idx:
                struct_name = idx[name]
                if struct_name in entries:
                    return struct_name, entries[struct_name]

        # Try with "Entry" suffix for DBC names
        if name + "Entry" in entries:
            return name + "Entry", entries[name + "Entry"]

        # Try stripping "Entry" suffix
        if name.endswith("Entry"):
            stripped = name[:-5]
            if stripped in entries:
                return stripped, entries[stripped]
            for idx in indices.values():
                if stripped in idx:
                    struct_name = idx[stripped]
                    if struct_name in entries:
                        return struct_name, entries[struct_name]

        return None

    def _suggest_alternative(self, name: str) -> Optional[str]:
        """Build a suggestion string when a name isn't found in DBC files."""
        resolved = self._resolve_entry(name)
        if not resolved:
            return None

        struct_name, entry = resolved
        category = entry.get("category", "")
        sql_table = entry.get("sql_table", "")
        dbc_file = entry.get("dbc_name", "")

        parts = [f"'{name}' is not a DBC file."]
        if category == "sql_objectmgr":
            parts.append(f"It is a SQL ObjectMgr store (table: {sql_table}).")
            parts.append(f"Use query_game_data(dbc_name='{name}') to query it, or lookup_datastore(query='{name}') for metadata.")
        elif category == "sql_manager":
            mgr = entry.get("manager_singleton", "")
            parts.append(f"It is a SQL Manager store (table: {sql_table}, manager: {mgr}).")
            parts.append(f"Use query_game_data(dbc_name='{name}') to query it, or lookup_datastore(query='{name}') for metadata.")
        elif category == "dbc_backed":
            parts.append(f"It is DBC-backed ({dbc_file}.dbc, SQL overlay: {sql_table}).")
            parts.append(f"Use query_game_data(dbc_name='{dbc_file}') for merged DBC+SQL data.")
        return " ".join(parts)

    def _load_dbc(self, dbc_name: str) -> WDBCReader:
        if dbc_name in self.dbc_cache:
            return self.dbc_cache[dbc_name]

        format_string = self.format_parser.get_format(dbc_name)
        if not format_string:
            raise ValueError(f"No format found for DBC: {dbc_name}")

        # Try exact path first, then case-insensitive search
        dbc_file = self.dbc_path / f"{dbc_name}.dbc"
        if not dbc_file.exists():
            # Case-insensitive search for matching .dbc file
            dbc_name_lower = dbc_name.lower()
            for f in self.dbc_path.glob("*.dbc"):
                if f.stem.lower() == dbc_name_lower:
                    dbc_file = f
                    break

        if not dbc_file.exists():
            raise FileNotFoundError(f"DBC file not found: {self.dbc_path / dbc_name}.dbc")

        reader = WDBCReader(str(dbc_file), format_string)
        reader.read()
        self.dbc_cache[dbc_name] = reader
        return reader

    def _query_database(self, sql: str, db_name: Union[str, None] = None) -> Tuple[Optional[List[Dict]], Optional[str]]:
        db = db_name or self.db_name
        try:
            cmd = [
                "mysql",
                "-h", self.db_host,
                "-P", self.db_port,
                "-u", self.db_user,
                f"-p{self.db_password}",
                "-D", db,
                "-e", sql,
                "--batch",
                "--skip-column-names"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)

            if result.returncode != 0:
                return None, result.stderr.strip()

            # Get column names
            cmd_with_headers = cmd.copy()
            cmd_with_headers.remove("--skip-column-names")
            header_result = subprocess.run(cmd_with_headers, capture_output=True, text=True, timeout=15)

            columns = []
            if header_result.returncode == 0:
                first_line = header_result.stdout.strip().split('\n')[0]
                columns = [c.strip() for c in first_line.split('\t')]

            rows = []
            for line in result.stdout.strip().split('\n'):
                if line:
                    values = line.split('\t')
                    row = {}
                    for i, val in enumerate(values):
                        col_name = columns[i] if i < len(columns) else str(i)
                        # Try to convert numeric values
                        try:
                            row[col_name] = int(val)
                        except ValueError:
                            try:
                                row[col_name] = float(val)
                            except ValueError:
                                row[col_name] = val
                    rows.append(row)

            return rows, None

        except subprocess.TimeoutExpired:
            return None, "Database query timed out"
        except Exception as e:
            return None, str(e)

    def list_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "query_dbc",
                "description": "Query World of Warcraft DBC binary files ONLY. For SQL-only datastores (quest_template, creature_template, smart_scripts, etc.), use query_game_data instead. Can retrieve specific records by ID or row index, filter records by field values, and select specific columns.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "dbc_name": {
                            "type": "string",
                            "description": "Name of the DBC file (without .dbc extension). Examples: 'Spell', 'SkillLineAbility', 'AreaTable', 'Item', 'Talent'"
                        },
                        "id": {
                            "type": "number",
                            "description": "Get record by ID field value (field 0). Mutually exclusive with row_index and filter."
                        },
                        "row_index": {
                            "type": "number",
                            "description": "Get record by row index (0-based). Mutually exclusive with id and filter."
                        },
                        "filter": {
                            "type": "object",
                            "description": "Filter records by field values. Keys are field indices (as strings), values are the values to match. Example: {'2': 2567} to find records where field 2 equals 2567.",
                            "additionalProperties": True
                        },
                        "columns": {
                            "type": "array",
                            "items": {"type": "number"},
                            "description": "Select specific field indices to return. If omitted, all fields are returned."
                        },
                        "limit": {
                            "type": "number",
                            "description": "Maximum number of records to return (default: 100, max: 1000)"
                        },
                        "info": {
                            "type": "boolean",
                            "description": "If true, return DBC file information instead of records"
                        }
                    },
                    "required": ["dbc_name"]
                }
            },
            {
                "name": "list_dbcs",
                "description": "List available DBC binary files and their formats. DBC files only — does NOT include SQL-only tables like quest_template, creature_template, etc. Use list_stores to see all datastores including SQL tables.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "search": {
                            "type": "string",
                            "description": "Optional search term to filter DBC names"
                        }
                    }
                }
            },
            {
                "name": "describe_fields",
                "description": "Get field names, types, and descriptions for a DBC-backed datastore. Works for DBC files like Spell, Item, AreaTable. For SQL-only datastores (quest_template, creature_template), use lookup_datastore to get field info. Returns field mappings from AzerothCore source code.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "dbc_name": {
                            "type": "string",
                            "description": "Name of the DBC file or datastore (without .dbc extension). Examples: 'Spell', 'SkillLineAbility', 'Item'. For SQL tables, try lookup_datastore instead."
                        }
                    },
                    "required": ["dbc_name"]
                }
            },
            {
                "name": "query_game_data",
                "description": "Unified game data query for ALL AzerothCore datastores: DBC binary files with SQL overlays, SQL ObjectMgr tables (quest_template, creature_template, item_template, etc.), and SQL Manager tables (spell_proc_event, smart_scripts, conditions, etc.). Use this as the primary query tool — it handles all datastore types. Use lookup_datastore first if unsure which name to use.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "dbc_name": {
                            "type": "string",
                            "description": "Name of the datastore. Can be a DBC name ('Spell'), SQL table name ('quest_template', 'creature_template', 'smart_scripts'), or C++ struct name ('SpellEntry'). Use lookup_datastore to find the correct name."
                        },
                        "id": {
                            "type": "number",
                            "description": "Get record by ID field value (field 0). Mutually exclusive with row_index and filter."
                        },
                        "row_index": {
                            "type": "number",
                            "description": "Get record by row index (0-based). Mutually exclusive with id and filter."
                        },
                        "filter": {
                            "type": "object",
                            "description": "Filter records by field values. For DBC stores, keys are field indices (as strings). For SQL stores, keys are column names. Example: {'2': 2567} for DBC, {'QuestID': 3904} for SQL.",
                            "additionalProperties": True
                        },
                        "columns": {
                            "type": "array",
                            "items": {"type": "number"},
                            "description": "Select specific field indices to return (DBC stores only). If omitted, all fields are returned."
                        },
                        "limit": {
                            "type": "number",
                            "description": "Maximum number of records to return (default: 100)"
                        }
                    },
                    "required": ["dbc_name"]
                }
            },
            {
                "name": "lookup_datastore",
                "description": "Look up AzerothCore datastore metadata by C++ struct name, SQL table name, DBC file name, or store variable name. Returns the full cross-reference: C++ struct, DBC file, SQL table, store variable, manager singleton, field definitions, and source file locations. IMPORTANT: Call this BEFORE writing SQL queries to discover column names. Returns sql_columns for SQL tables.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Name to look up. Examples: 'SpellEntry', 'creature_template', 'gameobject_template', 'sSpellStore', 'smart_scripts'"
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "execute_sql",
                "description": "Execute a SQL query on the AzerothCore database (acore_world by default). Use for querying SQL-only stores like creature_template, item_template, quest_template, spell_proc_event, smart_scripts, conditions, etc. Prefer query_game_data for simple lookups — use this for complex joins or aggregations. TIP: Use lookup_datastore first to discover table column names.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "sql": {
                            "type": "string",
                            "description": "SQL query to execute on the acore_world database"
                        }
                    },
                    "required": ["sql"]
                }
            },
            {
                "name": "list_stores",
                "description": "List all AzerothCore datastores (DBC-backed, SQL-only ObjectMgr, and SQL Manager stores). Returns categorized list with metadata for discovering available data sources.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "enum": ["all", "dbc_backed", "sql_objectmgr", "sql_manager"],
                            "description": "Filter by datastore category (default: all)"
                        },
                        "search": {
                            "type": "string",
                            "description": "Filter results by name (matches struct, table, or DBC file name)"
                        }
                    }
                }
            }
        ]

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        try:
            handlers = {
                "query_dbc": self._query_dbc,
                "list_dbcs": self._list_dbcs,
                "describe_fields": self._describe_fields,
                "query_game_data": self._query_game_data,
                "lookup_datastore": self._lookup_datastore,
                "execute_sql": self._execute_sql,
                "list_stores": self._list_stores,
            }
            handler = handlers.get(name)
            if handler:
                return handler(arguments)
            return {"error": f"Unknown tool: {name}", "isError": True}
        except Exception as e:
            return {"error": str(e), "isError": True}

    # --- Tool implementations ---

    def _query_dbc(self, args: Dict[str, Any]) -> Dict[str, Any]:
        dbc_name = args.get("dbc_name")
        if not dbc_name:
            return {"error": "dbc_name is required", "isError": True}

        try:
            reader = self._load_dbc(dbc_name)
        except (ValueError, FileNotFoundError) as e:
            suggestion = self._suggest_alternative(dbc_name)
            error = str(e)
            if suggestion:
                error += f" {suggestion}"
            return {"error": error, "isError": True}

        if args.get("info"):
            return {"result": reader.get_info()}

        if "id" in args:
            record = reader.get_record_by_id(args["id"])
            if record is None:
                return {"result": None, "message": f"No record found with ID {args['id']}"}
            columns = args.get("columns")
            if columns:
                record = {idx: record.get(idx) for idx in columns}
            return {"result": record}

        if "row_index" in args:
            record = reader.get_record(args["row_index"])
            if record is None:
                return {"result": None, "message": f"No record found at row index {args['row_index']}"}
            columns = args.get("columns")
            if columns:
                record = {idx: record.get(idx) for idx in columns}
            return {"result": record}

        filter_dict = None
        if "filter" in args:
            filter_dict = {int(k): v for k, v in args["filter"].items()}

        columns = args.get("columns")
        limit = min(args.get("limit", 100), 1000)

        results = reader.query(filter_dict=filter_dict, columns=columns)

        if len(results) > limit:
            results = results[:limit]
            truncated = True
        else:
            truncated = False

        return {"result": results, "count": len(results), "truncated": truncated}

    def _list_dbcs(self, args: Dict[str, Any]) -> Dict[str, Any]:
        available = self.format_parser.list_available()

        search = args.get("search", "").lower()
        if search:
            available = [name for name in available if search in name.lower()]

        dbc_files = sorted([f.stem for f in self.dbc_path.glob("*.dbc")])

        result_list = []
        for name in available:
            fmt = self.format_parser.get_format(name)
            field_count = len(fmt) if fmt else 0
            record_size = self.format_parser.get_record_size(fmt) if fmt else 0

            file_exists = any(name.lower() == f.lower() or
                            name.lower() + "entry" == f.lower() or
                            name.lower().replace("entry", "") == f.lower()
                            for f in dbc_files)

            # Check registry for SQL overlay info
            entries = self.registry.get("entries", {})
            sql_table = ""
            for entry in entries.values():
                if entry.get("dbc_name", "").lower() == name.lower():
                    sql_table = entry.get("sql_table", "")
                    break

            result_list.append({
                "name": name,
                "format": fmt[:60] + "..." if len(fmt) > 60 else fmt,
                "field_count": field_count,
                "record_size": record_size,
                "file_exists": file_exists,
                "sql_overlay": sql_table
            })

        resp = {"result": result_list, "count": len(result_list)}

        if search and not result_list:
            resp["hint"] = f"No DBC files match '{search}'. Use list_stores(search='{search}') to search all datastores including SQL tables."

        return resp

    def _describe_fields(self, args: Dict[str, Any]) -> Dict[str, Any]:
        dbc_name = args.get("dbc_name")
        if not dbc_name:
            return {"error": "dbc_name is required", "isError": True}

        format_string = self.format_parser.get_format(dbc_name)
        if not format_string:
            suggestion = self._suggest_alternative(dbc_name)
            error = f"No format found for DBC: {dbc_name}."
            if suggestion:
                error += f" {suggestion}"
            else:
                error += " Use list_stores(search='<name>') to find available datastores."
            return {"error": error, "isError": True}

        # Look up in registry for enriched info
        resolved = self._resolve_entry(dbc_name)
        reg_entry = resolved[1] if resolved else None
        reg_fields = reg_entry.get("fields", {}) if reg_entry else {}

        fields = []
        for idx in range(len(format_string)):
            format_char = format_string[idx] if idx < len(format_string) else 'x'

            type_map = {
                'i': 'uint32', 'n': 'uint32', 'd': 'uint32', 'l': 'uint32',
                'f': 'float', 's': 'string', 'b': 'uint8',
                'x': 'unused', 'X': 'unused'
            }
            field_type = type_map.get(format_char, 'unknown')

            idx_str = str(idx)
            reg_field = reg_fields.get(idx_str, {})
            if reg_field:
                field_name = reg_field["name"]
                struct_type = reg_field.get("type", field_type)
                sql_col = reg_field.get("sql_column", "")
                notes = reg_field.get("notes", "")
            else:
                field_name = f"Field{idx}"
                struct_type = field_type
                sql_col = ""
                notes = ""

            fields.append({
                "index": idx,
                "name": field_name,
                "type": struct_type,
                "sql_column": sql_col,
                "format_char": format_char,
                "notes": notes,
                "has_mapping": bool(reg_field)
            })

        result = {
            "dbc": dbc_name,
            "field_count": len(fields),
            "mapped_fields": len([f for f in fields if f["has_mapping"]]),
            "unmapped_fields": len(fields) - len([f for f in fields if f["has_mapping"]]),
            "fields": fields
        }

        if reg_entry:
            result["metadata"] = {
                "c_struct": reg_entry.get("c_struct", ""),
                "sql_table": reg_entry.get("sql_table", ""),
                "store_variable": reg_entry.get("store_variable", ""),
                "category": reg_entry.get("category", ""),
                "access_pattern": f"{reg_entry.get('store_variable', '')}.LookupEntry(id)"
            }

        return {"result": result}

    def _query_game_data(self, args: Dict[str, Any]) -> Dict[str, Any]:
        dbc_name = args.get("dbc_name")
        if not dbc_name:
            return {"error": "dbc_name is required", "isError": True}

        resolved = self._resolve_entry(dbc_name)
        if resolved:
            struct_name, entry = resolved
            category = entry.get("category", "")

            if category == "dbc_backed":
                return self._query_game_data_dbc(args, entry)
            elif category in ("sql_objectmgr", "sql_manager"):
                return self._query_game_data_sql(args, entry)
        
        # Fallback: try as raw DBC name
        return self._query_game_data_dbc(args, None)

    def _query_game_data_dbc(self, args: Dict[str, Any], reg_entry: Optional[Dict]) -> Dict[str, Any]:
        dbc_name = args.get("dbc_name")

        dbc_result = None
        dbc_error = None
        db_result = None
        db_error = None

        # Step 1: Try DBC query
        try:
            dbc_result = self._query_dbc(args)
            if "error" in dbc_result:
                dbc_error = dbc_result["error"]
                dbc_result = None
            else:
                dbc_result = dbc_result.get("result")
        except Exception as e:
            dbc_error = str(e)

        # Step 2: Try database query if we have an SQL overlay table
        sql_table = reg_entry.get("sql_table", "") if reg_entry else ""
        if sql_table:
            sql = f"SELECT * FROM {sql_table}"
            if "id" in args:
                sql += f" WHERE ID = {args['id']}"
            sql += f" LIMIT {args.get('limit', 100)}"
            db_result, db_error = self._query_database(sql)

        # Step 3: Merge results
        if db_result and not dbc_result:
            source = "database"
            merged = db_result
        elif dbc_result and not db_result:
            source = "dbc"
            merged = dbc_result
        elif dbc_result and db_result:
            source = "hybrid"
            merged = dbc_result
        else:
            return {
                "error": f"No data found. DBC: {dbc_error or 'N/A'}, DB: {db_error or 'N/A'}",
                "isError": True
            }

        metadata = {
            "source": source,
            "dbc_exists": dbc_result is not None,
            "db_table": sql_table,
            "db_exists": db_result is not None
        }
        if reg_entry:
            metadata["c_struct"] = reg_entry.get("c_struct", "")
            metadata["store_variable"] = reg_entry.get("store_variable", "")
            metadata["access_pattern"] = f"{reg_entry.get('store_variable', '')}.LookupEntry(id)"

        return {"result": merged, "metadata": metadata}

    def _query_game_data_sql(self, args: Dict[str, Any], reg_entry: Dict) -> Dict[str, Any]:
        sql_table = reg_entry.get("sql_table", "")
        if not sql_table:
            return {"error": f"No SQL table for {reg_entry.get('c_struct', 'unknown')}", "isError": True}

        if not self.db_available:
            return {
                "error": f"Database not available ({self.db_user}@{self.db_host}:{self.db_port}/{self.db_name}). Check DB credentials in MCP server environment config.",
                "isError": True
            }

        # Smart routing: resolve table to correct database
        target_db = self._resolve_table_database(sql_table, self.db_name)
        if target_db:
            print(f"Routing query_game_data to {target_db} for table '{sql_table}'", file=sys.stderr)

        sql = f"SELECT * FROM {sql_table}"

        where_clauses = []
        if "id" in args:
            pk_col = self._find_primary_key(reg_entry)
            where_clauses.append(f"{pk_col} = {args['id']}")

        if "filter" in args:
            for col, val in args["filter"].items():
                if isinstance(val, str):
                    where_clauses.append(f"{col} = '{val}'")
                else:
                    where_clauses.append(f"{col} = {val}")

        if where_clauses:
            sql += " WHERE " + " AND ".join(where_clauses)
        sql += f" LIMIT {args.get('limit', 100)}"

        rows, db_error = self._query_database(sql, db_name=target_db)
        if db_error:
            error_msg = f"Database error: {db_error}"
            col_match = re.search(r"Unknown column '([^']+)' in '([^']*)'", db_error)
            if not col_match:
                col_match = re.search(r"Unknown column '([^']+)'", db_error)
            if col_match:
                bad_col = col_match.group(1)
                suggestion = self._suggest_column(sql_table, bad_col)
                if suggestion:
                    error_msg += f"\n{suggestion}"
                error_msg += f"\nUse lookup_datastore(query='{sql_table}') for full schema."
            elif "Unknown table" in db_error or "doesn't exist" in db_error:
                bad_table = sql_table
                db_close = [t for t in self._all_tables_cache if bad_table.lower() in t or t in bad_table.lower()]
                if db_close:
                    error_msg += f"\nDid you mean: {', '.join(db_close[:5])}?"
                error_msg += f"\nUse lookup_datastore(query='{bad_table}') to verify table and get schema."
            return {"error": error_msg, "isError": True}

        metadata = {
            "source": "database",
            "category": reg_entry.get("category", ""),
            "sql_table": sql_table,
            "c_struct": reg_entry.get("c_struct", ""),
            "store_variable": reg_entry.get("store_variable", ""),
        }
        pk_col = self._find_primary_key(reg_entry)
        metadata["primary_key"] = pk_col
        if rows:
            metadata["columns"] = list(rows[0].keys())
        elif self.db_available:
            schema = self._get_table_schema(sql_table)
            if schema:
                metadata["columns"] = [c["COLUMN_NAME"] for c in schema]
        mgr = reg_entry.get("manager_singleton", "")
        if mgr:
            metadata["manager_singleton"] = mgr
            metadata["access_pattern"] = f"{mgr}->Get{reg_entry.get('c_struct', '')}Data()"

        if not rows:
            table = sql_table
            if 'loot_template' in table.lower() and args.get("filter"):
                hint = "No results. For quest items, try gameobject_questitem or creature_questitem tables.\n"
                hint += "Use lookup_datastore(query='gameobject_questitem') to see schema."
                return {"result": [], "count": 0, "hint": hint, "metadata": metadata}

        return {"result": rows or [], "count": len(rows or []), "metadata": metadata}

    def _find_primary_key(self, reg_entry: Dict) -> str:
        """Try to determine the primary key column name from registry fields."""
        fields = reg_entry.get("fields", {})
        if "0" in fields:
            f = fields["0"]
            col = f.get("sql_column", "") or f.get("name", "")
            if col:
                return col
        sql_table = reg_entry.get("sql_table", "")
        if sql_table and self.db_available and sql_table not in self._pk_cache:
            schema = self._get_table_schema(sql_table)
            if schema:
                for c in schema:
                    if c.get("is_primary_key"):
                        self._pk_cache[sql_table] = c["COLUMN_NAME"]
                        break
                else:
                    self._pk_cache[sql_table] = schema[0]["COLUMN_NAME"] if schema else "entry"
            else:
                self._pk_cache[sql_table] = "entry"
        return self._pk_cache.get(sql_table, "entry")

    def _get_table_schema(self, table_name: str) -> Optional[List[Dict]]:
        """Get column info from INFORMATION_SCHEMA, cached per table."""
        if not self.db_available:
            return None
        if table_name in self._schema_cache:
            return self._schema_cache[table_name]
        self._schema_cache[table_name] = None
        pk_rows, _ = self._query_database(
            f"SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE "
            f"WHERE TABLE_SCHEMA = '{self.db_name}' AND TABLE_NAME = '{table_name}' "
            f"AND CONSTRAINT_NAME = 'PRIMARY'"
        )
        pk_col = pk_rows[0]["COLUMN_NAME"] if pk_rows else None
        rows, _ = self._query_database(
            f"SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_KEY "
            f"FROM INFORMATION_SCHEMA.COLUMNS "
            f"WHERE TABLE_SCHEMA = '{self.db_name}' AND TABLE_NAME = '{table_name}' "
            f"ORDER BY ORDINAL_POSITION"
        )
        if rows:
            for r in rows:
                r["is_primary_key"] = (r["COLUMN_NAME"] == pk_col) if pk_col else (r.get("COLUMN_KEY") == "PRI")
            self._schema_cache[table_name] = rows[:50]
        return self._schema_cache[table_name]

    def _suggest_column(self, table_name: str, bad_col: str) -> Optional[str]:
        """Find similar column names when a query fails on Unknown column."""
        schema = self._get_table_schema(table_name)
        if not schema:
            return None
        columns = [c["COLUMN_NAME"] for c in schema]
        bad_lower = bad_col.lower()
        suggestions = [c for c in columns if c.lower() == bad_lower]
        if not suggestions:
            suggestions = [c for c in columns if bad_lower in c.lower() or c.lower() in bad_lower]
        if not suggestions:
            suggestions = [c for c in columns if c.lower().startswith(bad_lower[:3])]
        if suggestions:
            return f"Column '{bad_col}' not found in '{table_name}'. Similar columns: {', '.join(suggestions[:8])}. All columns: {', '.join(columns[:30])}"
        return f"Column '{bad_col}' not found in '{table_name}'. Available columns: {', '.join(columns[:30])}"

    def _lookup_datastore(self, args: Dict[str, Any]) -> Dict[str, Any]:
        query = args.get("query", "").strip()
        if not query:
            return {"error": "query is required", "isError": True}

        resolved = self._resolve_entry(query)
        if not resolved:
            # Try fuzzy search
            entries = self.registry.get("entries", {})
            matches = []
            q_lower = query.lower()
            for struct_name, entry in entries.items():
                if (q_lower in struct_name.lower() or
                    q_lower in entry.get("sql_table", "").lower() or
                    q_lower in entry.get("dbc_file", "").lower() or
                    q_lower in entry.get("dbc_name", "").lower()):
                    matches.append(struct_name)
            
            if not matches:
                return {"result": {"matches": [], "message": f"No datastore found matching '{query}'"}}
            
            results = []
            for struct_name in matches[:10]:
                entry = entries[struct_name]
                results.append(self._build_lookup_result(struct_name, entry))
            return {"result": {"matches": results, "count": len(results)}}

        struct_name, entry = resolved
        result = self._build_lookup_result(struct_name, entry)
        return {"result": {"matches": [result], "count": 1, "exact": True}}

    def _build_lookup_result(self, struct_name: str, entry: Dict) -> Dict[str, Any]:
        category = entry.get("category", "")
        result = {
            "c_struct": struct_name,
            "category": category,
            "sql_table": entry.get("sql_table", ""),
            "sql_database": entry.get("sql_database", "db_world"),
            "store_variable": entry.get("store_variable", ""),
            "header_file": entry.get("header_file", ""),
            "field_count": len(entry.get("fields", {})),
        }

        if category == "dbc_backed":
            result["dbc_file"] = entry.get("dbc_file", "")
            result["dbc_name"] = entry.get("dbc_name", "")
            result["format_variable"] = entry.get("format_variable", "")
            result["store_type"] = entry.get("store_type", "")
            result["hints"] = {
                "loading": f"Loaded from {entry.get('dbc_file', '')} via DBCStorage, with SQL overlay from {entry.get('sql_table', '')}",
                "access_pattern": f"{entry.get('store_variable', '')}.LookupEntry(id) -> {struct_name} const*"
            }
        elif category == "sql_objectmgr":
            result["loader_function"] = entry.get("loader_function", "")
            result["container_type"] = entry.get("container_type", "")
            result["hints"] = {
                "loading": f"Loaded via {entry.get('loader_function', 'ObjectMgr::Load*()')} from SQL table {entry.get('sql_table', '')}",
                "access_pattern": f"sObjectMgr->Get{struct_name}(id)"
            }
        elif category == "sql_manager":
            result["manager_singleton"] = entry.get("manager_singleton", "")
            result["manager_class"] = entry.get("manager_class", "")
            result["container_type"] = entry.get("container_type", "")
            singleton = entry.get("manager_singleton", "")
            result["hints"] = {
                "loading": f"Loaded by {entry.get('manager_class', '')} ({singleton}) from SQL table {entry.get('sql_table', '')}",
                "access_pattern": f"{singleton}->Get{struct_name}()" if singleton else "Direct SQL query"
            }

        # Include field summary (first 10)
        fields = entry.get("fields", {})
        if fields:
            sample = list(fields.items())[:10]
            result["fields_sample"] = [
                {"key": k, "name": v.get("name", ""), "type": v.get("type", "")}
                for k, v in sample
            ]

        sql_table = entry.get("sql_table", "")
        if sql_table and self.db_available:
            schema = self._get_table_schema(sql_table)
            if schema:
                result["sql_columns"] = [
                    {
                        "name": c["COLUMN_NAME"],
                        "type": c["DATA_TYPE"],
                        "is_primary_key": c.get("is_primary_key", False),
                    }
                    for c in schema
                ]

        return result

    def _extract_tables_from_sql(self, sql: str) -> List[str]:
        """Extract table names from SQL query."""
        tables = []
        
        from_matches = re.finditer(r'\bFROM\s+`?(\w+)`?', sql, re.IGNORECASE)
        for match in from_matches:
            tables.append(match.group(1))
        
        join_matches = re.finditer(r'\bJOIN\s+`?(\w+)`?', sql, re.IGNORECASE)
        for match in join_matches:
            tables.append(match.group(1))
        
        return tables

    def _execute_sql(self, args: Dict[str, Any]) -> Dict[str, Any]:
        sql = args.get("sql", "").strip()
        if not sql:
            return {"error": "sql is required", "isError": True}

        if not self.db_available:
            return {
                "error": f"Database not available ({self.db_user}@{self.db_host}:{self.db_port}/{self.db_name}). Check DB credentials in MCP server environment config.",
                "isError": True
            }

        # Safety: block destructive statements
        sql_upper = sql.upper().strip()
        for forbidden in ["DROP ", "TRUNCATE ", "ALTER ", "GRANT ", "REVOKE "]:
            if sql_upper.startswith(forbidden):
                return {"error": f"Forbidden statement type: {forbidden.strip()}", "isError": True}

        # Smart routing: extract tables and determine correct database
        tables = self._extract_tables_from_sql(sql)
        target_db = self.db_name
        
        if tables:
            primary_table = tables[0]
            resolved_db = self._resolve_table_database(primary_table, self.db_name)
            if resolved_db:
                target_db = resolved_db
                print(f"Routing query to {target_db} for table '{primary_table}'", file=sys.stderr)

        rows, error = self._query_database(sql, db_name=target_db)
        
        if error:
            # Check for wrong database error and try all databases
            if "Unknown table" in error or "doesn't exist" in error:
                for db in self._db_priority_order:
                    if db == target_db:
                        continue
                    rows, error = self._query_database(sql, db_name=db)
                    if not error and rows is not None:
                        print(f"Retried successfully in {db}", file=sys.stderr)
                        # Update cache with correct database for this table
                        for table in tables:
                            if table.lower() in self._table_to_db_cache:
                                dbs = self._table_to_db_cache[table.lower()]
                                if db not in dbs:
                                    dbs.insert(0, db)
                            else:
                                self._table_to_db_cache[table.lower()] = [db]
                        
                        # Hint for empty results on loot template searches
                        if not rows:
                            table_match = re.search(r'FROM\s+`?(\w+)`?', sql, re.IGNORECASE)
                            if table_match:
                                tbl = table_match.group(1)
                                if 'loot_template' in tbl.lower() and re.search(r'\bITEM\s*=|ITEM\s+=\s*\d+', sql, re.IGNORECASE):
                                    msg = "No results. For quest items, try gameobject_questitem or creature_questitem tables instead of loot_template tables.\n"
                                    msg += f"Example: SELECT * FROM gameobject_questitem WHERE ItemId = <item_id>\n"
                                    msg += "Use lookup_datastore(query='gameobject_questitem') to see schema."
                                    return {"result": [], "count": 0, "hint": msg}
                        return {"result": rows or [], "count": len(rows or [])}
                
                # Build error message with suggestions
                msg = f"Database query failed: {error}"
                table_match = re.search(r"Table '(\w+)\.(\w+)' doesn't exist", error)
                if not table_match:
                    table_match = re.search(r"Unknown table '([^']+)'", error)
                if table_match:
                    bad_table = table_match.group(2) if table_match.lastindex >= 2 else table_match.group(1)
                    
                    # Try all databases for suggestions
                    suggestions = self._suggest_similar_tables(bad_table)
                    if suggestions:
                        suggestion_info = []
                        for s in suggestions[:5]:
                            db_list = self._table_to_db_cache.get(s, [])
                            db_str = ", ".join(db_list) if db_list else "unknown"
                            suggestion_info.append(f"{s} ({db_str})")
                        msg += f"\n\nDid you mean: {', '.join(suggestion_info)}?"
                    
                    msg += f"\n\nUse lookup_datastore(query='{bad_table}') to verify the table name and get column schema."
                    msg += f"\nNote: Searched databases: {', '.join(self._db_priority_order)}"
            
            elif "Unknown column" in error:
                msg = f"Database query failed: {error}"
                col_match = re.search(r"Unknown column '([^']+)' in '([^']*)'", error)
                if not col_match:
                    col_match = re.search(r"Unknown column '([^']+)'", error)
                if col_match:
                    bad_col = col_match.group(1)
                    from_match = re.search(r'\bFROM\s+`?(\w+)`?', sql, re.IGNORECASE)
                    table_hint = from_match.group(1) if from_match else ""
                    if table_hint and table_hint.upper() not in ("SELECT", "DUAL"):
                        suggestion = self._suggest_column(table_hint, bad_col)
                        if suggestion:
                            msg += f"\n{suggestion}"
                        msg += f"\nUse lookup_datastore(query='{table_hint}') for full schema."
            
            elif "Access denied" in error or "connect" in error.lower() or "Can't connect" in error:
                msg = f"Database query failed: {error}"
                msg += " Check DB_HOST, DB_PORT, DB_USER, DB_PASSWORD environment variables."
            
            else:
                msg = f"Database query failed: {error}"
            
            return {"error": msg, "isError": True}

        # Hint for empty results on loot template searches
        if not rows:
            table_match = re.search(r'FROM\s+`?(\w+)`?', sql, re.IGNORECASE)
            if table_match:
                tbl = table_match.group(1)
                if 'loot_template' in tbl.lower() and re.search(r'\bITEM\s*=|ITEM\s+=\s*\d+', sql, re.IGNORECASE):
                    msg = "No results. For quest items, try gameobject_questitem or creature_questitem tables instead of loot_template tables.\n"
                    msg += f"Example: SELECT * FROM gameobject_questitem WHERE ItemId = <item_id>\n"
                    msg += "Use lookup_datastore(query='gameobject_questitem') to see schema."
                    return {"result": [], "count": 0, "hint": msg}

        return {"result": rows or [], "count": len(rows or [])}

    def _list_stores(self, args: Dict[str, Any]) -> Dict[str, Any]:
        category_filter = args.get("category", "all")
        search = args.get("search", "").lower()

        entries = self.registry.get("entries", {})
        results = []

        for struct_name, entry in entries.items():
            cat = entry.get("category", "")
            if category_filter != "all" and cat != category_filter:
                continue

            if search:
                searchable = " ".join([
                    struct_name.lower(),
                    entry.get("sql_table", "").lower(),
                    entry.get("dbc_file", "").lower(),
                    entry.get("dbc_name", "").lower(),
                    entry.get("manager_singleton", "").lower()
                ])
                if search not in searchable:
                    continue

            item = {
                "c_struct": struct_name,
                "category": cat,
                "sql_table": entry.get("sql_table", ""),
                "fields": len(entry.get("fields", {}))
            }

            if cat == "dbc_backed":
                item["dbc_file"] = entry.get("dbc_file", "")
                item["store_variable"] = entry.get("store_variable", "")
            elif cat == "sql_objectmgr":
                item["store_variable"] = entry.get("store_variable", "")
            elif cat == "sql_manager":
                item["manager_singleton"] = entry.get("manager_singleton", "")

            results.append(item)

        return {"result": results, "count": len(results)}

    # --- MCP protocol ---

    def run(self):
        while True:
            try:
                line = sys.stdin.readline()
                if not line:
                    break

                request = json.loads(line)

                if request.get("method") == "initialize":
                    response = {
                        "jsonrpc": "2.0",
                        "id": request.get("id"),
                        "result": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {"tools": {}},
                            "serverInfo": {
                                "name": "dbc-query",
                                "version": "2.0.0"
                            }
                        }
                    }
                elif request.get("method") == "tools/list":
                    response = {
                        "jsonrpc": "2.0",
                        "id": request.get("id"),
                        "result": {"tools": self.list_tools()}
                    }
                elif request.get("method") == "tools/call":
                    params = request.get("params", {})
                    tool_name = params.get("name")
                    tool_args = params.get("arguments", {})
                    result = self.call_tool(tool_name, tool_args)
                    response = {
                        "jsonrpc": "2.0",
                        "id": request.get("id"),
                        "result": {
                            "content": [{"type": "text", "text": json.dumps(result, indent=2)}]
                        }
                    }
                else:
                    response = {
                        "jsonrpc": "2.0",
                        "id": request.get("id"),
                        "error": {"code": -32601, "message": f"Method not found: {request.get('method')}"}
                    }

                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()

            except json.JSONDecodeError as e:
                sys.stdout.write(json.dumps({
                    "jsonrpc": "2.0", "id": None,
                    "error": {"code": -32700, "message": str(e)}
                }) + "\n")
                sys.stdout.flush()
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"Error: {e}", file=sys.stderr)


def main():
    server = DBCQueryMCP()
    server.run()


if __name__ == "__main__":
    main()
