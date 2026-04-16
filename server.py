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
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
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
        self.db_host = os.environ.get('DB_HOST', 'localhost')
        self.db_port = os.environ.get('DB_PORT', '3306')
        self.db_user = os.environ.get('DB_USER', 'root')
        self.db_password = os.environ.get('DB_PASSWORD', 'password')
        self.db_name = os.environ.get('DB_NAME', 'acore_world')

        self.format_parser = FormatParser(self.format_file)
        self.format_parser.parse()

        self.registry = self._load_registry()
        self.dbc_cache: Dict[str, WDBCReader] = {}

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

    def _load_dbc(self, dbc_name: str) -> WDBCReader:
        if dbc_name in self.dbc_cache:
            return self.dbc_cache[dbc_name]

        format_string = self.format_parser.get_format(dbc_name)
        if not format_string:
            raise ValueError(f"No format found for DBC: {dbc_name}")

        dbc_file = self.dbc_path / f"{dbc_name}.dbc"
        reader = WDBCReader(str(dbc_file), format_string)
        reader.read()
        self.dbc_cache[dbc_name] = reader
        return reader

    def _query_database(self, sql: str, db_name: Optional[str] = None) -> Tuple[Optional[List[Dict]], Optional[str]]:
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
                "description": "Query World of Warcraft DBC files. Can retrieve specific records by ID or row index, filter records by field values, and select specific columns.",
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
                "description": "List all available DBC files and their formats",
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
                "description": "Get field names, types, and descriptions for a DBC file. Returns field mappings extracted from AzerothCore source code, making it easy to understand what each field index represents.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "dbc_name": {
                            "type": "string",
                            "description": "Name of the DBC file (without .dbc extension). Examples: 'Spell', 'SkillLineAbility', 'Item'"
                        }
                    },
                    "required": ["dbc_name"]
                }
            },
            {
                "name": "query_game_data",
                "description": "Unified game data query that combines DBC files and database tables, mimicking AzerothCore's server loading behavior. Queries DBC file first, then checks database table for overlays/overrides. Returns data with metadata about the source. Use this for reliable, server-accurate data.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "dbc_name": {
                            "type": "string",
                            "description": "Name of the DBC/data source (without .dbc extension). Examples: 'Spell', 'Achievement_Category', 'LFGDungeons'"
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
                            "description": "Filter records by field values. Keys are field indices (as strings), values are the values to match.",
                            "additionalProperties": True
                        },
                        "columns": {
                            "type": "array",
                            "items": {"type": "number"},
                            "description": "Select specific field indices to return. If omitted, all fields are returned."
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
                "description": "Look up AzerothCore datastore metadata by C++ struct name, SQL table name, DBC file name, or store variable name. Returns the full cross-reference: C++ struct, DBC file, SQL table, store variable, manager singleton, field definitions, and source file locations. Essential for linking code references to underlying data.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Name to look up. Examples: 'SpellEntry', 'creature_template', 'Spell.dbc', 'sSpellStore', 'smart_scripts'"
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "execute_sql",
                "description": "Execute a SQL query on the AzerothCore database (acore_world by default). Use for querying SQL-only stores like creature_template, item_template, quest_template, spell_proc_event, smart_scripts, conditions, etc.",
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
            return {"error": str(e), "isError": True}

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

        result = []
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

            result.append({
                "name": name,
                "format": fmt[:60] + "..." if len(fmt) > 60 else fmt,
                "field_count": field_count,
                "record_size": record_size,
                "file_exists": file_exists,
                "sql_overlay": sql_table
            })

        return {"result": result, "count": len(result)}

    def _describe_fields(self, args: Dict[str, Any]) -> Dict[str, Any]:
        dbc_name = args.get("dbc_name")
        if not dbc_name:
            return {"error": "dbc_name is required", "isError": True}

        format_string = self.format_parser.get_format(dbc_name)
        if not format_string:
            return {"error": f"No format found for DBC: {dbc_name}", "isError": True}

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
            sql_db = reg_entry.get("sql_database", "acore_world")
            sql = f"SELECT * FROM {sql_table}"
            if "id" in args:
                sql += f" WHERE ID = {args['id']}"
            sql += f" LIMIT {args.get('limit', 100)}"
            db_result, db_error = self._query_database(sql, sql_db)

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

        sql_db = reg_entry.get("sql_database", "acore_world")
        sql = f"SELECT * FROM {sql_table}"

        if "id" in args:
            sql += f" WHERE entry = {args['id']}"
        sql += f" LIMIT {args.get('limit', 100)}"

        rows, db_error = self._query_database(sql, sql_db)
        if db_error:
            return {"error": f"Database error: {db_error}", "isError": True}

        metadata = {
            "source": "database",
            "category": reg_entry.get("category", ""),
            "sql_table": sql_table,
            "c_struct": reg_entry.get("c_struct", ""),
            "store_variable": reg_entry.get("store_variable", ""),
        }
        mgr = reg_entry.get("manager_singleton", "")
        if mgr:
            metadata["manager_singleton"] = mgr
            metadata["access_pattern"] = f"{mgr}->Get{reg_entry.get('c_struct', '')}Data()"

        return {"result": rows or [], "count": len(rows or []), "metadata": metadata}

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

        return result

    def _execute_sql(self, args: Dict[str, Any]) -> Dict[str, Any]:
        sql = args.get("sql", "").strip()
        if not sql:
            return {"error": "sql is required", "isError": True}

        # Safety: block destructive statements
        sql_upper = sql.upper().strip()
        for forbidden in ["DROP ", "TRUNCATE ", "ALTER ", "GRANT ", "REVOKE "]:
            if sql_upper.startswith(forbidden):
                return {"error": f"Forbidden statement type: {forbidden.strip()}", "isError": True}

        rows, error = self._query_database(sql)
        if error:
            return {"error": error, "isError": True}

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
