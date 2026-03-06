#!/usr/bin/env python3
"""
Parser for AzerothCore DBCStructure.h to extract field names and descriptions.

This module reads the DBCStructure.h header file and extracts struct definitions
with field names, types, indices, and comments for various DBC file types.
"""

import re
from typing import Dict, List, Optional, Any
from pathlib import Path


class DBCStructureParser:
    """Parser for DBCStructure.h struct definitions."""

    def __init__(self):
        """Initialize the parser."""
        self.structs: Dict[str, Dict[str, Any]] = {}

    def parse_file(self, structure_path: str) -> Dict[str, Dict[str, Any]]:
        """Parse the DBCStructure.h file and extract all struct definitions."""
        path = Path(structure_path)
        if not path.exists():
            raise FileNotFoundError(f"DBCStructure.h not found at: {path}")

        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        # Pattern to match struct definitions (non-greedy to handle nested braces)
        struct_pattern = r"struct\s+(\w+)\s*\{([^}]*)\}\s*;"

        for match in re.finditer(struct_pattern, content, re.DOTALL):
            struct_name = match.group(1)
            struct_body = match.group(2)

            fields = self._parse_fields(struct_body)
            self.structs[struct_name] = {
                "name": struct_name,
                "fields": fields,
                "field_count": len(fields),
            }

        return self.structs

    def _parse_fields(self, struct_body: str) -> List[Dict[str, Any]]:
        """Parse field definitions from struct body."""
        fields = []

        for line in struct_body.split("\n"):
            # Skip commented lines and keywords
            stripped = line.strip()
            if (
                not stripped
                or stripped.startswith("//")
                or "union" in stripped
                or "struct " in stripped
            ):
                continue

            # Split code from comment at first //
            if "//" in line:
                code_part, comment_part = line.split("//", 1)
            else:
                code_part, comment_part = line, ""

            code_stripped = code_part.strip()

            # Pattern 1: type fieldname; (e.g., uint32 ID;)
            match = re.match(r"(\w+)\s+(\w+)\s*;?\s*$", code_stripped)
            if match:
                field_type, field_name = match.groups()
            # Pattern 2: type fieldname[]; (e.g., uint32 Type[8];)
            elif re.match(r"(\w+)\s+\w+\[\d+\]", code_stripped):
                parts = re.split(r"\s+", code_stripped.strip(";"))
                field_type = parts[0]
                field_name = parts[1].strip("[];") if len(parts) > 1 else "Field"
            # Pattern 3: type fieldname[MAX_CONSTANT]; (e.g., uint32 Type[MAX_LOCK_CASE];)
            elif "[MAX_" in code_stripped or "[" in code_stripped:
                parts = re.split(r"\s+", code_stripped.strip(";"))
                field_type = parts[0]
                field_name = parts[1].replace(";", "") if len(parts) > 1 else "Field"
            else:
                continue

            # Extract index from comment (e.g., "0        m_ID" or "1-8      m_Type")
            index_match = re.match(r"\s*(\d+)(?:\s*-\s*(\d+))?\s*(.*)", comment_part)

            field_info: Dict[str, Any] = {
                "name": field_name,
                "type": field_type,
            }

            if index_match:
                start_idx = int(index_match.group(1))
                end_idx = (
                    int(index_match.group(2)) if index_match.group(2) else start_idx
                )
                description = index_match.group(3).strip()

                if start_idx == end_idx:
                    field_info["index"] = start_idx
                else:
                    field_info["index_range"] = (start_idx, end_idx)

                if description:
                    field_info["description"] = description

            fields.append(field_info)

        return fields

    def get_fields(self, struct_name: str) -> Optional[List[Dict[str, Any]]]:
        """Get field definitions for a specific struct."""
        return self.structs.get(struct_name, {}).get("fields")

    def get_field_mapping(self, struct_name: str) -> Dict[str, Dict[str, Any]]:
        """Get field mapping by index for a specific struct."""
        fields = self.get_fields(struct_name)
        if not fields:
            return {}

        mapping: Dict[str, Dict[str, Any]] = {}
        for field in fields:
            name = field["name"]
            type_str = field.get("type", "unknown")
            desc = field.get("description", "")

            idx = field.get("index")
            idx_range = field.get("index_range")

            if idx is not None:
                # Single index
                mapping[str(idx)] = {
                    "name": name,
                    "type": type_str,
                    "description": desc,
                }
            elif idx_range:
                # Range of indices (e.g., array fields)
                start, end = idx_range
                for i in range(start, end + 1):
                    offset = i - start
                    field_name = f"{name}[{offset}]" if (end - start) > 0 else name
                    mapping[str(i)] = {
                        "name": field_name,
                        "type": type_str,
                        "description": desc,
                        "is_array_element": True,
                    }

        return mapping

    def get_struct_info(self, struct_name: str) -> Optional[Dict[str, Any]]:
        """Get complete struct information including metadata."""
        return self.structs.get(struct_name)


def main():
    """Test the DBC structure parser."""
    import json

    default_path = (
        "/home/luke/GIT/azerothcore-wotlk/src/server/shared/DataStores/DBCStructure.h"
    )

    parser = DBCStructureParser()
    structs = parser.parse_file(default_path)

    print(f"Parsed {len(structs)} struct definitions")
    print()

    # Show LockEntry as example
    lock_struct = parser.get_struct_info("LockEntry")
    if lock_struct:
        print("LockEntry structure:")
        print(json.dumps(lock_struct, indent=2))
        print()


if __name__ == "__main__":
    main()
