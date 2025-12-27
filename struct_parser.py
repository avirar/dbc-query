#!/usr/bin/env python3
"""
Parser for AzerothCore DBCStructure.h to extract field names and types.

This module parses the C++ struct definitions in DBCStructure.h and creates
a mapping of field indices to field names and types for each DBC.
"""

import re
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional


class StructParser:
    """Parser for DBCStructure.h C++ struct definitions."""

    def __init__(self, structure_file: str):
        """
        Initialize the struct parser.

        Args:
            structure_file: Path to DBCStructure.h file
        """
        self.structure_file = Path(structure_file)
        self.mappings: Dict[str, Dict[int, Dict[str, str]]] = {}

    def parse(self) -> Dict[str, Dict[int, Dict[str, str]]]:
        """
        Parse DBCStructure.h and extract field name mappings.

        Returns:
            Dictionary mapping DBC name to field mappings.
            Example:
            {
                "SkillLineAbility": {
                    0: {"name": "ID", "type": "uint32"},
                    1: {"name": "SkillLine", "type": "uint32"},
                    2: {"name": "Spell", "type": "uint32"}
                }
            }

        Raises:
            FileNotFoundError: If DBCStructure.h doesn't exist
        """
        if not self.structure_file.exists():
            raise FileNotFoundError(f"DBCStructure.h not found at: {self.structure_file}")

        with open(self.structure_file, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        # Find all struct definitions
        # Pattern matches: struct SkillLineAbilityEntry { ... };
        struct_pattern = r'struct\s+(\w+(?:Entry)?)\s*\{([^}]+)\}'
        structs = re.findall(struct_pattern, content, re.DOTALL)

        for struct_name, struct_body in structs:
            fields = self._parse_struct_fields(struct_body)

            if fields:
                # Remove "Entry" suffix for DBC name consistency
                dbc_name = struct_name.replace("Entry", "")
                self.mappings[dbc_name] = fields

        return self.mappings

    def _parse_struct_fields(self, struct_body: str) -> Dict[int, Dict[str, str]]:
        """
        Parse individual struct fields from struct body.

        Args:
            struct_body: The body content of a C++ struct

        Returns:
            Dictionary mapping field index to field info
        """
        fields = {}

        # Pattern matches field definitions with index comments:
        # uint32 SkillLine;                                       // 1
        # float Speed;                                            // 47
        # std::array<char const*, 16> name;                       // 4-19
        # int32 SoundOverrideSubclassID;                          // 3

        # Split into lines for processing
        lines = struct_body.split('\n')

        for line in lines:
            line = line.strip()

            # Skip empty lines and preprocessor directives
            if not line or line.startswith('#'):
                continue

            # Skip commented-out fields (they're not loaded into memory)
            if line.startswith('//'):
                continue

            # Match field definition with index comment
            # Captures: type, field_name, index
            # Updated to handle template types like std::array<char const*, 16>
            field_match = re.match(
                r'((?:const\s+)?(?:uint|int|float|char)(?:32|8|16)?|std::(?:array|string)(?:<[^>]+>)?)\s+'
                r'(\w+)(?:\s*\[.*?\])?(?:\s*\{.*?\})?;?\s*'
                r'//\s*(\d+)(?:-(\d+))?',
                line
            )

            if field_match:
                field_type = field_match.group(1).strip()
                field_name = field_match.group(2).strip()
                field_index_start = int(field_match.group(3))
                field_index_end = field_match.group(4)

                # Clean up type names
                field_type = self._normalize_type(field_type)

                # Handle array fields (e.g., "4-19" for name[16])
                if field_index_end:
                    # This is an array field spanning multiple indices
                    field_index_end = int(field_index_end)
                    for idx in range(field_index_start, field_index_end + 1):
                        # For arrays, append index to field name
                        array_field_name = f"{field_name}[{idx - field_index_start}]"
                        fields[idx] = {
                            "name": array_field_name,
                            "type": field_type
                        }
                else:
                    # Single field
                    fields[field_index_start] = {
                        "name": field_name,
                        "type": field_type
                    }

        return fields

    def _normalize_type(self, type_str: str) -> str:
        """
        Normalize C++ type names to simpler forms.

        Args:
            type_str: C++ type string

        Returns:
            Normalized type name
        """
        # Mapping of C++ types to simpler names
        type_map = {
            'uint32': 'uint32',
            'int32': 'int32',
            'uint8': 'uint8',
            'int8': 'int8',
            'float': 'float',
            'char const*': 'string',
            'char*': 'string',
            'std::array<char const*, 16>': 'string_array',
            'std::array<uint32, 2>': 'uint32_array',
            'std::array<uint32, 3>': 'uint32_array',
            'std::array<int32, 3>': 'int32_array',
            'std::array<float, 3>': 'float_array',
        }

        # Check for exact matches first
        if type_str in type_map:
            return type_map[type_str]

        # Handle std::array with various types
        if type_str.startswith('std::array'):
            if 'char' in type_str:
                return 'string_array'
            elif 'uint32' in type_str:
                return 'uint32_array'
            elif 'int32' in type_str:
                return 'int32_array'
            elif 'float' in type_str:
                return 'float_array'
            return 'array'

        # Default: return as-is
        return type_str

    def get_field_info(self, dbc_name: str, field_index: int) -> Optional[Dict[str, str]]:
        """
        Get field information for a specific DBC and field index.

        Args:
            dbc_name: Name of the DBC
            field_index: Field index

        Returns:
            Field info dict or None if not found
        """
        if not self.mappings:
            self.parse()

        dbc_fields = self.mappings.get(dbc_name, {})
        return dbc_fields.get(field_index)

    def get_all_fields(self, dbc_name: str) -> Dict[int, Dict[str, str]]:
        """
        Get all field mappings for a DBC.

        Args:
            dbc_name: Name of the DBC

        Returns:
            Dictionary of all fields for the DBC
        """
        if not self.mappings:
            self.parse()

        return self.mappings.get(dbc_name, {})

    def list_dbcs(self) -> List[str]:
        """
        List all DBCs with field mappings.

        Returns:
            List of DBC names
        """
        if not self.mappings:
            self.parse()

        return sorted(self.mappings.keys())

    def export_json(self, output_file: str) -> None:
        """
        Export field mappings to JSON file.

        Args:
            output_file: Path to output JSON file
        """
        if not self.mappings:
            self.parse()

        # Convert integer keys to strings for JSON
        json_mappings = {}
        for dbc_name, fields in self.mappings.items():
            json_mappings[dbc_name] = {
                str(idx): field_info
                for idx, field_info in fields.items()
            }

        with open(output_file, 'w') as f:
            json.dump(json_mappings, f, indent=2, sort_keys=True)

        print(f"Exported {len(json_mappings)} DBC field mappings to {output_file}")


def main():
    """Generate field mappings JSON file."""
    # Default paths
    default_structure_file = "/root/azerothcore-wotlk/src/server/shared/DataStores/DBCStructure.h"
    default_output_file = "/root/dbc-query/field_mappings.json"

    structure_file = sys.argv[1] if len(sys.argv) > 1 else default_structure_file
    output_file = sys.argv[2] if len(sys.argv) > 2 else default_output_file

    print(f"Parsing DBCStructure.h from: {structure_file}")
    print()

    parser = StructParser(structure_file)
    mappings = parser.parse()

    print(f"Parsed {len(mappings)} struct definitions")
    print()

    # Show summary
    print("DBC Field Mapping Summary:")
    print("-" * 70)

    for dbc_name in sorted(mappings.keys())[:10]:  # Show first 10
        field_count = len(mappings[dbc_name])
        print(f"  {dbc_name:30s} {field_count:3d} fields")

    if len(mappings) > 10:
        print(f"  ... and {len(mappings) - 10} more DBCs")

    print("-" * 70)
    print()

    # Show example
    if "SkillLineAbility" in mappings:
        print("Example: SkillLineAbility field mappings:")
        for idx in sorted(mappings["SkillLineAbility"].keys())[:5]:
            field = mappings["SkillLineAbility"][idx]
            print(f"  Field {idx:2d}: {field['name']:30s} ({field['type']})")
        print()

    # Export to JSON
    parser.export_json(output_file)
    print()
    print(f"✓ Field mappings successfully generated!")
    print(f"  File: {output_file}")
    print(f"  DBCs mapped: {len(mappings)}")
    total_fields = sum(len(fields) for fields in mappings.values())
    print(f"  Total fields: {total_fields}")


if __name__ == "__main__":
    main()
