#!/usr/bin/env python3
"""
MCP (Model Context Protocol) server for querying WoW DBC files.

This server provides tools for querying WDBC format DBC files through
the MCP protocol, allowing AI assistants to access game data directly.
"""

import json
import sys
import os
from pathlib import Path
from typing import Dict, Any, List, Optional
from dbc_reader import WDBCReader
from format_parser import FormatParser


class DBCQueryMCP:
    """MCP server for DBC file queries."""

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

        # Initialize format parser
        self.format_parser = FormatParser(self.format_file)
        self.format_parser.parse()

        # Cache for loaded DBCs
        self.dbc_cache: Dict[str, WDBCReader] = {}

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
            return {"result": record}

        # Get record by row index
        if "row_index" in args:
            record = reader.get_record(args["row_index"])
            if record is None:
                return {"result": None, "message": f"No record found at row index {args['row_index']}"}
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
