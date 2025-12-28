#!/usr/bin/env python3
"""
MCP (Model Context Protocol) server for querying WoW DBC files.

This server provides tools for querying WDBC format DBC files through
the MCP protocol, allowing AI assistants to access game data directly.
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
    """MCP server for DBC file queries."""

    # Mapping from DBC file names to database table names
    # Extracted from AzerothCore DBCStores.cpp LOAD_DBC calls
    DBC_TO_DB_TABLE = {
        "Achievement": "achievement_dbc",
        "Achievement_Category": "achievement_category_dbc",
        "Achievement_Criteria": "achievement_criteria_dbc",
        "AreaTable": "areatable_dbc",
        "Spell": "spell_dbc",
        "SkillLineAbility": "skilllineability_dbc",
        "LFGDungeons": "lfgdungeons_dbc",
        "RandPropPoints": "randproppoints_dbc",
        "SpellCastTimes": "spellcasttimes_dbc",
        # Add more mappings as needed
    }

    def __init__(self):
        """Initialize the MCP server."""
        # Get configuration from environment
        self.dbc_path = Path(os.environ.get(
            'DBC_PATH',
            '/root/azerothcore-wotlk/env/dist/bin/dbc'
        ))
        self.format_file = os.environ.get(
            'DBC_FORMAT_FILE',
            '/root/azerothcore-wotlk/src/server/shared/DataStores/DBCfmt.h'
        )

        # Database configuration (for unified queries)
        self.db_host = os.environ.get('DB_HOST', 'localhost')
        self.db_port = os.environ.get('DB_PORT', '3306')
        self.db_user = os.environ.get('DB_USER', 'root')
        self.db_password = os.environ.get('DB_PASSWORD', 'password')
        self.db_name = os.environ.get('DB_NAME', 'acore_world')

        # Initialize format parser
        self.format_parser = FormatParser(self.format_file)
        self.format_parser.parse()

        # Load field name mappings
        self.field_mappings = self._load_field_mappings()

        # Cache for loaded DBCs
        self.dbc_cache: Dict[str, WDBCReader] = {}

    def _load_field_mappings(self) -> Dict[str, Dict[str, Dict[str, str]]]:
        """
        Load field name mappings from field_mappings.json.

        Returns:
            Dictionary mapping DBC names to field info
        """
        mapping_file = Path(__file__).parent / "field_mappings.json"

        if not mapping_file.exists():
            print(f"Warning: field_mappings.json not found at {mapping_file}", file=sys.stderr)
            return {}

        try:
            with open(mapping_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Warning: Could not load field mappings: {e}", file=sys.stderr)
            return {}

    def _load_dbc(self, dbc_name: str) -> WDBCReader:
        """
        Load a DBC file (with caching).

        Args:
            dbc_name: Name of the DBC file (without .dbc extension)

        Returns:
            WDBCReader instance

        Raises:
            ValueError: If format not found
            FileNotFoundError: If DBC file not found
        """
        # Check cache
        if dbc_name in self.dbc_cache:
            return self.dbc_cache[dbc_name]

        # Get format
        format_string = self.format_parser.get_format(dbc_name)
        if not format_string:
            raise ValueError(f"No format found for DBC: {dbc_name}")

        # Load DBC
        dbc_file = self.dbc_path / f"{dbc_name}.dbc"
        reader = WDBCReader(str(dbc_file), format_string)
        reader.read()

        # Cache it
        self.dbc_cache[dbc_name] = reader

        return reader

    def list_tools(self) -> List[Dict[str, Any]]:
        """
        List available MCP tools.

        Returns:
            List of tool definitions
        """
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
            }
        ]

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a tool call.

        Args:
            name: Tool name
            arguments: Tool arguments

        Returns:
            Tool result
        """
        try:
            if name == "query_dbc":
                return self._query_dbc(arguments)
            elif name == "list_dbcs":
                return self._list_dbcs(arguments)
            elif name == "describe_fields":
                return self._describe_fields(arguments)
            elif name == "query_game_data":
                return self._query_game_data(arguments)
            else:
                return {
                    "error": f"Unknown tool: {name}",
                    "isError": True
                }
        except Exception as e:
            return {
                "error": str(e),
                "isError": True
            }

    def _query_dbc(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Query a DBC file."""
        dbc_name = args.get("dbc_name")
        if not dbc_name:
            return {"error": "dbc_name is required", "isError": True}

        # Load DBC
        try:
            reader = self._load_dbc(dbc_name)
        except (ValueError, FileNotFoundError) as e:
            return {"error": str(e), "isError": True}

        # Return info if requested
        if args.get("info"):
            return {"result": reader.get_info()}

        # Get record by ID
        if "id" in args:
            record = reader.get_record_by_id(args["id"])
            if record is None:
                return {"result": None, "message": f"No record found with ID {args['id']}"}

            # Apply column selection if specified
            columns = args.get("columns")
            if columns:
                record = {idx: record.get(idx) for idx in columns}

            return {"result": record}

        # Get record by row index
        if "row_index" in args:
            record = reader.get_record(args["row_index"])
            if record is None:
                return {"result": None, "message": f"No record found at row index {args['row_index']}"}

            # Apply column selection if specified
            columns = args.get("columns")
            if columns:
                record = {idx: record.get(idx) for idx in columns}

            return {"result": record}

        # Query with filter
        filter_dict = None
        if "filter" in args:
            # Convert string keys to integers
            filter_dict = {int(k): v for k, v in args["filter"].items()}

        columns = args.get("columns")
        limit = min(args.get("limit", 100), 1000)  # Cap at 1000

        results = reader.query(filter_dict=filter_dict, columns=columns)

        # Apply limit
        if len(results) > limit:
            results = results[:limit]
            truncated = True
        else:
            truncated = False

        return {
            "result": results,
            "count": len(results),
            "truncated": truncated
        }

    def _list_dbcs(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """List available DBC files."""
        available = self.format_parser.list_available()

        # Apply search filter
        search = args.get("search", "").lower()
        if search:
            available = [name for name in available if search in name.lower()]

        # Get actual DBC files
        dbc_files = sorted([f.stem for f in self.dbc_path.glob("*.dbc")])

        # Match formats to files
        result = []
        for name in available:
            fmt = self.format_parser.get_format(name)
            field_count = len(fmt) if fmt else 0
            record_size = self.format_parser.get_record_size(fmt) if fmt else 0

            # Check if file exists
            file_exists = any(name.lower() == f.lower() or
                            name.lower() + "entry" == f.lower() or
                            name.lower().replace("entry", "") == f.lower()
                            for f in dbc_files)

            result.append({
                "name": name,
                "format": fmt[:60] + "..." if len(fmt) > 60 else fmt,
                "field_count": field_count,
                "record_size": record_size,
                "file_exists": file_exists
            })

        return {
            "result": result,
            "count": len(result)
        }

    def _describe_fields(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Describe fields for a DBC file.

        Returns field names, types, and indices extracted from AzerothCore source.
        """
        dbc_name = args.get("dbc_name")
        if not dbc_name:
            return {"error": "dbc_name is required", "isError": True}

        # Get format string to know total field count
        format_string = self.format_parser.get_format(dbc_name)
        if not format_string:
            return {"error": f"No format found for DBC: {dbc_name}", "isError": True}

        # Get field mappings for this DBC
        field_info = self.field_mappings.get(dbc_name, {})

        # Build comprehensive field list
        fields = []
        for idx in range(len(format_string)):
            # Get format character for type info
            format_char = format_string[idx] if idx < len(format_string) else 'x'

            # Map format char to human-readable type
            type_map = {
                'i': 'uint32', 'n': 'uint32', 'd': 'uint32', 'l': 'uint32',
                'f': 'float',
                's': 'string',
                'b': 'uint8',
                'x': 'unused', 'X': 'unused'
            }
            field_type = type_map.get(format_char, 'unknown')

            # Get field name from mappings (if available)
            idx_str = str(idx)
            if idx_str in field_info:
                field_name = field_info[idx_str]["name"]
                # Prefer type from struct definition if available
                struct_type = field_info[idx_str].get("type", field_type)
            else:
                field_name = f"Field{idx}"
                struct_type = field_type

            fields.append({
                "index": idx,
                "name": field_name,
                "type": struct_type,
                "format_char": format_char,
                "has_mapping": idx_str in field_info
            })

        return {
            "result": {
                "dbc": dbc_name,
                "field_count": len(fields),
                "mapped_fields": len(field_info),
                "unmapped_fields": len(fields) - len(field_info),
                "fields": fields
            }
        }

    def _query_database(self, table_name: str, args: Dict[str, Any]) -> Tuple[Optional[List[Dict]], Optional[str]]:
        """
        Query a database table using mysql command-line tool.

        Args:
            table_name: Name of the database table
            args: Query arguments (id, filter, columns, limit)

        Returns:
            Tuple of (results_list, error_message)
        """
        try:
            # Build SQL query
            sql_parts = [f"SELECT * FROM {table_name}"]

            # Add WHERE clause
            where_clauses = []
            if "id" in args:
                where_clauses.append(f"ID = {args['id']}")
            elif "filter" in args:
                for field_idx, value in args["filter"].items():
                    # For database queries, we'd need field name mapping
                    # For now, assume field_0 = ID
                    if field_idx == "0":
                        where_clauses.append(f"ID = {value}")

            if where_clauses:
                sql_parts.append("WHERE " + " AND ".join(where_clauses))

            # Add LIMIT
            limit = args.get("limit", 100)
            sql_parts.append(f"LIMIT {limit}")

            sql = " ".join(sql_parts)

            # Execute query using mysql command
            cmd = [
                "mysql",
                "-h", self.db_host,
                "-P", self.db_port,
                "-u", self.db_user,
                f"-p{self.db_password}",
                "-D", self.db_name,
                "-e", sql,
                "--batch",
                "--skip-column-names"
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode != 0:
                return None, f"Database query failed: {result.stderr}"

            # Parse results (tab-separated values)
            rows = []
            for line in result.stdout.strip().split('\n'):
                if line:
                    values = line.split('\t')
                    # Create dict with numeric keys for consistency with DBC
                    row_dict = {i: val for i, val in enumerate(values)}
                    rows.append(row_dict)

            return rows, None

        except Exception as e:
            return None, f"Database query error: {str(e)}"

    def _merge_results(self, dbc_data: Optional[Dict], db_data: Optional[List[Dict]]) -> Tuple[Any, str]:
        """
        Merge DBC and database results (database takes priority).

        Args:
            dbc_data: DBC query result (single record or list)
            db_data: Database query results (list of dicts)

        Returns:
            Tuple of (merged_data, source_type)
            source_type: "dbc", "database", or "hybrid"
        """
        # If only database data exists
        if db_data and not dbc_data:
            return db_data if len(db_data) > 1 else db_data[0], "database"

        # If only DBC data exists
        if dbc_data and not db_data:
            return dbc_data, "dbc"

        # Both exist - DBC takes priority (matching server behavior)
        # Database is only used for overlay/override
        if dbc_data and db_data:
            return dbc_data, "hybrid"

        # Neither exists
        return None, "none"

    def _query_game_data(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Unified query that combines DBC and database sources.

        This mimics AzerothCore's loading behavior:
        1. Try to load from DBC file
        2. Try to load from database table (if mapped)
        3. Return unified result with metadata

        Args:
            args: Query arguments (dbc_name, id, filter, columns, limit, etc.)

        Returns:
            Result dict with data and metadata about sources
        """
        dbc_name = args.get("dbc_name")
        if not dbc_name:
            return {"error": "dbc_name is required", "isError": True}

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

        # Step 2: Try database query (if table exists)
        db_table = self.DBC_TO_DB_TABLE.get(dbc_name)
        if db_table:
            db_result, db_error = self._query_database(db_table, args)

        # Step 3: Merge results
        merged_data, source = self._merge_results(dbc_result, db_result)

        # If no data from either source
        if merged_data is None:
            return {
                "error": f"No data found from either source. DBC error: {dbc_error}, DB error: {db_error}",
                "isError": True
            }

        # Return unified result with metadata
        return {
            "result": merged_data,
            "metadata": {
                "source": source,
                "dbc_exists": dbc_result is not None,
                "db_table": db_table,
                "db_exists": db_result is not None,
                "dbc_error": dbc_error,
                "db_error": db_error
            }
        }

    def run(self):
        """Run the MCP server (stdio mode)."""
        while True:
            try:
                line = sys.stdin.readline()
                if not line:
                    break

                request = json.loads(line)

                # Handle different request types
                if request.get("method") == "initialize":
                    response = {
                        "jsonrpc": "2.0",
                        "id": request.get("id"),
                        "result": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {
                                "tools": {}
                            },
                            "serverInfo": {
                                "name": "dbc-query",
                                "version": "1.0.0"
                            }
                        }
                    }
                elif request.get("method") == "tools/list":
                    response = {
                        "jsonrpc": "2.0",
                        "id": request.get("id"),
                        "result": {
                            "tools": self.list_tools()
                        }
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
                            "content": [
                                {
                                    "type": "text",
                                    "text": json.dumps(result, indent=2)
                                }
                            ]
                        }
                    }
                else:
                    response = {
                        "jsonrpc": "2.0",
                        "id": request.get("id"),
                        "error": {
                            "code": -32601,
                            "message": f"Method not found: {request.get('method')}"
                        }
                    }

                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()

            except json.JSONDecodeError as e:
                error_response = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32700,
                        "message": f"Parse error: {str(e)}"
                    }
                }
                sys.stdout.write(json.dumps(error_response) + "\n")
                sys.stdout.flush()
            except KeyboardInterrupt:
                break
            except Exception as e:
                # Log errors to stderr
                print(f"Error: {e}", file=sys.stderr)


def main():
    """Main entry point."""
    server = DBCQueryMCP()
    server.run()


if __name__ == "__main__":
    main()
