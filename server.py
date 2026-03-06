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
from wiki_hints import WikiHints
from structure_parser import DBCStructureParser


class DBCQueryMCP:
    """MCP server for DBC file queries."""

    DBC_TO_DB_TABLE = {
        # acore_world tables (DBC overlay tables - *_dbc tables override DBC by ID)
        "Achievement": [("achievement_dbc", "acore_world")],
        "Achievement_Category": [("achievement_category_dbc", "acore_world")],
        "Achievement_Criteria": [("achievement_criteria_dbc", "acore_world")],
        "AreaTable": [("areatable_dbc", "acore_world")],
        "Spell": [("spell_dbc", "acore_world")],
        "SkillLineAbility": [
            ("skill_line_ability", "acore_world"),
            ("skilllineability_dbc", "acore_world"),
        ],
        "LFGDungeons": [("lfgdungeons_dbc", "acore_world")],
        "RandPropPoints": [("randproppoints_dbc", "acore_world")],
        "SpellCastTimes": [("spellcasttimes_dbc", "acore_world")],
        "Lock": [("lock_dbc", "acore_world")],
        # Pure SQL template tables (no DBC equivalent - full data in SQL)
        "Quest": [("quest_template", "acore_world", True)],
        "Creature": [("creature_template", "acore_world", True)],
        "GameObject": [("gameobject_template", "acore_world", True)],
        # Item: item_dbc is the AC overlay table (often empty), item_template has full in-game data
        "Item": [("item_template", "acore_world"), ("item_dbc", "acore_world")],
        # DBC-only sources with optional SQL overlays
        "CreatureDisplayInfo": [("creaturedisplayinfo_dbc", "acore_world")],
        "LockType": [],  # LockType.dbc exists but no locktype_dbc table
        "ChatMsg": [("chatchannels_dbc", "acore_world")],
        # acore_characters tables (player data overrides)
        "PlayerXpRewarded": [("player_xp_rewarded", "acore_characters")],
    }

    # Maps table names to their primary key column name (default is "ID")
    TABLE_PRIMARY_KEYS = {
        "gameobject_template": "entry",
        "creature_template": "entry",
        "item_template": "entry",
        "quest_template": "ID",
    }

    # Pure SQL tables that have no DBC equivalent (need special handling)
    PURE_SQL_TABLES = {"quest_template", "creature_template", "gameobject_template"}

    # DBC types that use overlay pattern (SQL *_dbc tables overlay DBC by ID)
    OVERLAY_DBC_TYPES = {
        "Spell",
        "Lock",
        "Achievement",
        "AreaTable",
        "CreatureDisplayInfo",
        "LFGDungeons",
        "SkillLineAbility",
    }

    def __init__(self):
        """Initialize the MCP server."""
        # Get configuration from environment
        self.dbc_path = Path(
            os.environ.get("DBC_PATH", "/root/azerothcore-wotlk/env/dist/bin/dbc")
        )
        self.format_file = os.environ.get(
            "DBC_FORMAT_FILE",
            "/root/azerothcore-wotlk/src/server/shared/DataStores/DBCfmt.h",
        )

        # Database configuration (for unified queries)
        self.db_host = os.environ.get("DB_HOST", "localhost")
        self.db_port = os.environ.get("DB_PORT", "3306")
        self.db_user = os.environ.get("DB_USER", "acore")
        self.db_password = os.environ.get("DB_PASSWORD", "abc")

        # Initialize format parser
        self.format_parser = FormatParser(self.format_file)
        self.format_parser.parse()

        # Load field name mappings
        self.field_mappings = self._load_field_mappings()

        # Cache for loaded DBCs
        self.dbc_cache: Dict[str, WDBCReader] = {}

        # Initialize wiki hints generator
        self.wiki_hints = WikiHints()

        # Initialize structure parser (for field names from DBCStructure.h)
        self.structure_parser = DBCStructureParser()
        self.structure_file = os.environ.get(
            "DBC_STRUCTURE_FILE",
            "/home/luke/GIT/azerothcore-wotlk/src/server/shared/DataStores/DBCStructure.h",
        )
        try:
            self.structure_parser.parse_file(self.structure_file)
        except FileNotFoundError:
            pass  # Structure file optional - continue without it

    def _load_field_mappings(self) -> Dict[str, Dict[str, Dict[str, str]]]:
        """
        Load field name mappings from field_mappings.json.

        Returns:
            Dictionary mapping DBC names to field info
        """
        mapping_file = Path(__file__).parent / "field_mappings.json"

        if not mapping_file.exists():
            print(
                f"Warning: field_mappings.json not found at {mapping_file}",
                file=sys.stderr,
            )
            return {}

        try:
            with open(mapping_file, "r") as f:
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
                "description": "Query raw World of Warcraft DBC files directly (vanilla/original game data without server overrides). For most use cases, prefer query_game_data which includes database overlays. Returns base Blizzard data as stored in .dbc format.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "dbc_name": {
                            "type": "string",
                            "description": "Name of the DBC file (without .dbc extension). Common examples: 'Spell', 'Item', 'SkillLineAbility' for talents, 'AreaTable' for zones, 'CreatureDisplayInfo' for models",
                        },
                        "id": {
                            "type": "number",
                            "description": "Get record by ID field value (field 0). Mutually exclusive with row_index and filter.",
                        },
                        "row_index": {
                            "type": "number",
                            "description": "Get record by row index (0-based, not the same as ID). Mutually exclusive with id and filter.",
                        },
                        "filter": {
                            "type": "object",
                            "description": "Filter records by field values. Keys are field indices (as strings), values to match. Use describe_fields first to find correct indices. Example: {'2': 2567} finds records where field 2 equals 2567.",
                            "additionalProperties": True,
                        },
                        "columns": {
                            "type": "array",
                            "items": {"type": "number"},
                            "description": "Select specific field indices to return (use describe_fields to find indices). If omitted, all fields returned.",
                        },
                        "limit": {
                            "type": "number",
                            "description": "Maximum number of records to return (default: 100, max: 1000)",
                        },
                        "info": {
                            "type": "boolean",
                            "description": "If true, return DBC file structure information instead of records",
                        },
                    },
                    "required": ["dbc_name"],
                },
            },
            {
                "name": "list_dbcs",
                "description": "List all available WoW DBC files that can be queried. Use the 'search' parameter to find specific types (e.g., 'quest', 'item', 'spell'). For LLM workflow: Start here to discover what data sources exist, then use describe_fields to understand structure, then query_game_data to get actual records.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "search": {
                            "type": "string",
                            "description": "Optional case-insensitive search term to filter DBC names. Examples: 'quest' finds Quest, 'item' finds Item, 'spell' finds Spell, 'area' finds AreaTable",
                        }
                    },
                },
            },
            {
                "name": "describe_fields",
                "description": "CRITICAL FIRST STEP for LLMs: Get field names, types, and descriptions for a DBC file BEFORE querying. Returns field mappings extracted from AzerothCore source code showing what each field index represents. Use this to find correct field indices for your filters and column selections. Example workflow: 1) describe_fields('Quest') to learn quest structure, 2) use returned indices in query_game_data filter/columns parameters.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "dbc_name": {
                            "type": "string",
                            "description": "Name of the DBC file (without .dbc extension). MUST match exactly - case sensitive. Common sources: 'Spell', 'Quest', 'Item', 'SkillLineAbility' (talents), 'Achievement', 'AreaTable', 'GameObject', 'CreatureDisplayInfo', 'Talent'",
                        }
                    },
                    "required": ["dbc_name"],
                },
            },
            {
                "name": "query_game_data",
                "description": "Unified World of Warcraft game data query combining DBC files and SQL database tables. Queries DBC first, then checks database for overlays/overrides matching AzerothCore server behavior. Works across acore_world, acore_characters, and acore_auth databases. USE THIS TO GET ACTUAL IN-GAME DATA including quest definitions, item properties, creature templates, gameobject templates, spell information, talent data, achievement details, area information, and faction relations. Use describe_fields first to understand field indices for your query.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "dbc_name": {
                            "type": "string",
                            "description": "Name of the DBC/data source (without .dbc extension). COMMON SOURCES: 'Quest' for quest templates, 'Item' for item data, 'CreatureDisplayInfo' for NPC models, 'GameObject' for interactive objects, 'Spell' for spell effects, 'Achievement' for achievement data, 'AreaTable' for zone/area info, 'SkillLineAbility' for talents/ability trees",
                        },
                        "id": {
                            "type": "number",
                            "description": "Get record by ID field value. Mutually exclusive with row_index and filter.",
                        },
                        "row_index": {
                            "type": "number",
                            "description": "Get record by row index (0-based). Mutually exclusive with id and filter.",
                        },
                        "filter": {
                            "type": "object",
                            "description": "Filter records by field values. Keys are field indices as strings (from describe_fields output), values to match. Supports both numeric values {'2': 1234} and string values {'5': 'QuestName'}. Example for quests: filter field 2 (MinLevel) with {'2': 1} or field 12 (RewardNextQuest) with {'12': 3904}",
                            "additionalProperties": True,
                        },
                        "columns": {
                            "type": "array",
                            "items": {"type": "number"},
                            "description": "Select specific field indices to return. Use describe_fields to find the indices you need. If omitted, all fields are returned.",
                        },
                        "limit": {
                            "type": "number",
                            "description": "Maximum records to return (default: 100, max: 500)",
                        },
                    },
                    "required": ["dbc_name"],
                },
            },
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
                return {"error": f"Unknown tool: {name}", "isError": True}
        except Exception as e:
            return {"error": str(e), "isError": True}

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
                return {
                    "result": None,
                    "message": f"No record found with ID {args['id']}",
                }

            # Apply column selection if specified
            columns = args.get("columns")
            if columns:
                record = {idx: record.get(idx) for idx in columns}

            return {"result": record}

        # Get record by row index
        if "row_index" in args:
            record = reader.get_record(args["row_index"])
            if record is None:
                return {
                    "result": None,
                    "message": f"No record found at row index {args['row_index']}",
                }

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

        return {"result": results, "count": len(results), "truncated": truncated}

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
            file_exists = any(
                name.lower() == f.lower()
                or name.lower() + "entry" == f.lower()
                or name.lower().replace("entry", "") == f.lower()
                for f in dbc_files
            )

            format_preview = (
                (fmt[:60] + "...") if fmt and len(fmt) > 60 else (fmt or "")
            )
            result.append(
                {
                    "name": name,
                    "format": format_preview,
                    "field_count": field_count,
                    "record_size": record_size,
                    "file_exists": file_exists,
                }
            )

        return {"result": result, "count": len(result)}

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

        # Get field mappings for this DBC (JSON-based mapping, if available)
        json_field_info = self.field_mappings.get(dbc_name, {})

        # Get structure-based field names from DBCStructure.h (preferred source)
        struct_name = self.format_parser.DBC_NAME_MAP.get(dbc_name, dbc_name + "Entry")  # type: ignore
        struct_field_mapping = self.structure_parser.get_field_mapping(
            struct_name or ""
        )

        # Also try without Entry suffix if first attempt failed
        if not struct_field_mapping:
            struct_field_mapping = self.structure_parser.get_field_mapping(dbc_name)

        # Build comprehensive field list
        fields = []
        for idx in range(len(format_string)):
            # Get format character for type info
            format_char = format_string[idx] if idx < len(format_string) else "x"

            # Map format char to human-readable type
            type_map = {
                "i": "uint32",
                "n": "uint32",
                "d": "uint32",
                "l": "uint32",
                "f": "float",
                "s": "string",
                "b": "uint8",
                "x": "unused",
                "X": "unused",
            }
            field_type = type_map.get(format_char, "unknown")

            # Get field name - priority: JSON mapping > structure parser > default
            idx_str = str(idx)
            if idx_str in json_field_info:
                field_name = json_field_info[idx_str]["name"]
                struct_type = json_field_info[idx_str].get("type", field_type)
                description = json_field_info[idx_str].get("description", "")
            elif idx_str in struct_field_mapping:
                field_name = struct_field_mapping[idx_str]["name"]
                struct_type = struct_field_mapping[idx_str].get("type", field_type)
                description = struct_field_mapping[idx_str].get("description", "")
            else:
                field_name = f"Field{idx}"
                struct_type = field_type
                description = ""

            # Determine mapping source
            has_json_mapping = idx_str in json_field_info
            has_struct_mapping = idx_str in struct_field_mapping

            field_entry = {
                "index": idx,
                "name": field_name,
                "type": struct_type,
                "format_char": format_char,
                "has_json_mapping": has_json_mapping,
                "has_struct_mapping": has_struct_mapping,
            }

            if description:
                field_entry["description"] = description

            fields.append(field_entry)

        # Count total mapped fields from either source
        total_mapped = sum(
            1
            for idx_str in [str(i) for i in range(len(format_string))]
            if idx_str in json_field_info or idx_str in struct_field_mapping
        )

        return {
            "result": {
                "dbc": dbc_name,
                "field_count": len(fields),
                "mapped_from_json": len(json_field_info),
                "mapped_from_struct": len(struct_field_mapping),
                "total_mapped": total_mapped,
                "fields": fields,
            }
        }

    def _get_db_column_mapping(self, table_name: str, database: str) -> List[str]:
        """
        Get column names for a database table in order.

        Args:
            table_name: Name of the database table
            database: Name of the database

        Returns:
            List of column names in field index order
        """
        cmd = [
            "mysql",
            "-h",
            self.db_host,
            "-P",
            self.db_port,
            "-u",
            self.db_user,
            f"-p{self.db_password}",
            "-D",
            database,
            "-e",
            f"SHOW COLUMNS FROM `{table_name}`",
            "--batch",
            "--skip-column-names",
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
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

    def _query_database(
        self, table_name: str, database: str, args: Dict[str, Any]
    ) -> Tuple[Optional[List[Dict]], Optional[str]]:
        """
        Query a database table using mysql command-line tool.

        Args:
            table_name: Name of the database table
            database: Name of the database
            args: Query arguments (id, filter, columns, limit)

        Returns:
            Tuple of (results_list, error_message)
        """
        try:
            sql_parts = [f"SELECT * FROM {table_name}"]

            # Get the primary key column name for this table (default to "ID")
            pk_column = self.TABLE_PRIMARY_KEYS.get(table_name, "ID")

            where_clauses = []
            if "id" in args:
                where_clauses.append(f"`{pk_column}` = {int(args['id'])}")

            if "filter" in args:
                column_mapping = self._get_db_column_mapping(table_name, database)
                for field_idx, value in args["filter"].items():
                    idx = int(field_idx)
                    if idx == 0:
                        where_clauses.append(f"`{pk_column}` = {int(value)}")
                    elif idx < len(column_mapping):
                        column_name = column_mapping[idx]
                        if isinstance(value, str):
                            escaped_value = value.replace("'", "''")
                            where_clauses.append(f"`{column_name}` = '{escaped_value}'")
                        else:
                            where_clauses.append(f"`{column_name}` = {value}")

            if where_clauses:
                sql_parts.append("WHERE " + " AND ".join(where_clauses))

            limit = args.get("limit", 100)
            sql_parts.append(f"LIMIT {int(limit)}")

            sql = " ".join(sql_parts)

            cmd = [
                "mysql",
                "-h",
                self.db_host,
                "-P",
                self.db_port,
                "-u",
                self.db_user,
                f"-p{self.db_password}",
                "-D",
                database,
                "-e",
                sql,
                "--batch",
                "--skip-column-names",
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

            if result.returncode != 0:
                return None, f"Database query failed: {result.stderr}"

            rows = []
            for line in result.stdout.strip().split("\n"):
                if line:
                    values = line.split("\t")
                    row_dict = {str(i): val for i, val in enumerate(values)}
                    rows.append(row_dict)

            return rows, None

        except subprocess.TimeoutExpired:
            return None, "Database query timed out"
        except Exception as e:
            return None, f"Database query error: {str(e)}"

    def _merge_dbc_with_sql_overlay(
        self, dbc_data: Dict[str, Any], sql_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Merge SQL overlay data into DBC base data per AzerothCore behavior.

        Per DBCDatabaseLoader.cpp: SQL overlay tables match DBC field-by-field.
        For each SQL record at index ID, the values overlay (replace) the DBC values at that position.
        Empty strings in SQL preserve DBC string values.

        Args:
            dbc_data: Base DBC record (dict of field_index -> value)
            sql_data: SQL overlay record (dict of field_index -> value)

        Returns:
            Merged record with SQL values overlaying DBC base
        """
        merged = dict(dbc_data)  # Start with DBC base

        for field_idx, sql_value in sql_data.items():
            # Skip empty strings - they preserve DBC values per AC behavior
            if sql_value == "" and field_idx in merged:
                continue

            # SQL overlay replaces DBC value
            merged[field_idx] = sql_value

        return merged

    def _merge_results(
        self,
        dbc_data: Optional[Any],
        db_data: Optional[List[Dict]],
        is_item: bool = False,
        is_overlay: bool = False,
    ) -> Tuple[Optional[Any], str]:
        """
        Merge DBC and database results per AzerothCore behavior.

        Two modes:
        1. Overlay mode (is_overlay=True): SQL *_dbc tables overlay specific IDs in DBC data
           - DBC provides base, SQL overlays matching records by ID field
           - Empty strings preserve DBC values for string fields

        2. Full template mode (items/quest_template/etc): Prefer full SQL data when it has more fields
           - For items: item_dbc often empty, prefer item_template with all 96+ fields
           - For quests: Only exists in quest_template (pure SQL)

        Args:
            dbc_data: DBC query result (single record or list)
            db_data: Database query results (list of dicts)
            is_item: If True, prefer DB data when it has more fields
            is_overlay: If True, merge overlay by field rather than prefer one source

        Returns:
            Tuple of (merged_data, source_type)
            source_type: "dbc", "database", or "hybrid"
        """
        if db_data and not dbc_data:
            return (db_data[0] if len(db_data) == 1 else db_data), "database"

        if dbc_data and not db_data:
            return dbc_data, "dbc"

        if dbc_data and db_data:
            # Overlay mode: merge SQL into DBC field-by-field
            if is_overlay and isinstance(dbc_data, dict) and len(db_data) == 1:
                merged = self._merge_dbc_with_sql_overlay(dbc_data, db_data[0])
                return merged, "hybrid"

            # Full template mode (items): prefer DB when it has more fields
            if is_item:
                dbc_fields = len(dbc_data) if isinstance(dbc_data, dict) else 0
                db_fields = len(db_data[0]) if db_data else 0
                if db_fields > dbc_fields:
                    return (db_data[0] if len(db_data) == 1 else db_data), "database"

            # Default: prefer DBC data (AC loads DBC first, then overlays)
            return dbc_data, "hybrid"

        return None, "none"

    def _query_game_data(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Unified query that combines DBC files and database tables.

        Mimics AzerothCore's loading behavior:
        1. Try to load from DBC file (if DBC exists for this type)
        2. Try to load from all mapped database tables
        3. Return unified result with metadata about sources

        Note: Some types like Quest, CreatureTemplate, GameObjectTemplate are pure SQL
        and do not have DBC equivalents in AzerothCore.

        Args:
            args: Query arguments (dbc_name, id, filter, columns, limit)

        Returns:
            Result dict with data and metadata about sources
        """
        dbc_name = args.get("dbc_name")
        if not dbc_name:
            return {"error": "dbc_name is required", "isError": True}

        dbc_result = None
        dbc_error = None
        all_db_results: Dict[str, Any] = {}
        is_pure_sql = False

        # Step 1: Try DBC query (skip for pure SQL tables like Quest, CreatureTemplate)
        if dbc_name not in {"Quest", "Creature", "GameObject"}:
            try:
                dbc_response = self._query_dbc(args)
                if "error" in dbc_response:
                    # Some errors are expected (no format found), not always an issue
                    if "No format found" not in dbc_response["error"]:
                        dbc_error = dbc_response["error"]
                else:
                    dbc_result = dbc_response.get("result")
            except Exception as e:
                dbc_error = str(e)

        # Step 2: Try database queries (check all mapped tables for this DBC)
        db_tables_for_dbc = self.DBC_TO_DB_TABLE.get(dbc_name, [])

        for table_info in db_tables_for_dbc:
            # Handle both old format (tuple of 2) and new format (tuple of 3 with is_pure_sql flag)
            if len(table_info) >= 2:
                table_name, database = table_info[0], table_info[1]
                is_pure_sql = len(table_info) >= 3 and table_info[2]
            else:
                continue

            db_result, db_error = self._query_database(table_name, database, args)
            all_db_results[table_name] = {
                "database": database,
                "result": db_result,
                "error": db_error,
            }

        # Step 3: Merge results (prefer DBC if available, then use first valid DB result)
        combined_db_data: Optional[List[Dict]] = None
        overlay_table_name: Optional[str] = None
        for table_name, table_info in all_db_results.items():
            if table_info["result"]:
                combined_db_data = table_info["result"]
                # Track if this is an overlay table (ends with _dbc but not template)
                if table_name.endswith("_dbc") and "template" not in table_name:
                    overlay_table_name = table_name
                break

        # Determine merge mode
        is_item = dbc_name == "Item"
        # Use overlay merging for types where SQL *_dbc tables overlay DBC base data
        is_overlay = (
            dbc_name in self.OVERLAY_DBC_TYPES and overlay_table_name is not None
        )
        merged_data, source = self._merge_results(
            dbc_result, combined_db_data, is_item, is_overlay
        )

        if merged_data is None:
            error_msg = "No data found from any source"
            if dbc_error and "No format found" not in str(dbc_error):
                error_msg += f". DBC error: {dbc_error}"
            db_errors = [v["error"] for v in all_db_results.values() if v.get("error")]
            if db_errors:
                error_msg += f". DB errors: {', '.join(db_errors)}"
            return {"error": error_msg, "isError": True}

        sources_found = []
        if dbc_result:
            sources_found.append("dbc")
        if combined_db_data:
            db_tables_with_data = [k for k, v in all_db_results.items() if v["result"]]
            sources_found.extend(db_tables_with_data)

        response = {
            "result": merged_data,
            "metadata": {
                "source": source,
                "sources_found": sources_found,
                "dbc_exists": dbc_result is not None,
                "db_tables_checked": list(all_db_results.keys()),
                "is_pure_sql": is_pure_sql
                or dbc_name in {"Quest", "Creature", "GameObject"},
            },
        }

        # Add wiki hints if available
        for table_with_data in sources_found:
            hints = self.wiki_hints.generate_hints(table_with_data, merged_data)
            if hints:
                response["hints"] = hints
                break

        # Also try with DBC name if pure DBC source (source="dbc")
        if "hints" not in response and dbc_name:
            hints = self.wiki_hints.generate_hints(dbc_name, merged_data)
            if hints:
                response["hints"] = hints

        return response

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
                            "capabilities": {"tools": {}},
                            "serverInfo": {"name": "dbc-query", "version": "1.0.0"},
                        },
                    }
                elif request.get("method") == "tools/list":
                    response = {
                        "jsonrpc": "2.0",
                        "id": request.get("id"),
                        "result": {"tools": self.list_tools()},
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
                                {"type": "text", "text": json.dumps(result, indent=2)}
                            ]
                        },
                    }
                else:
                    response = {
                        "jsonrpc": "2.0",
                        "id": request.get("id"),
                        "error": {
                            "code": -32601,
                            "message": f"Method not found: {request.get('method')}",
                        },
                    }

                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()

            except json.JSONDecodeError as e:
                error_response = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"Parse error: {str(e)}"},
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
