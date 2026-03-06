#!/usr/bin/env python3
"""
Wiki-based hint generator for DBC/SQL query results.

This module loads AzerothCore wiki documentation and provides contextual
hints based on query results to help users understand the data they're seeing.
"""

import os
import re
from pathlib import Path
from typing import Dict, Any, Optional, List


class WikiHints:
    """Generates contextual hints based on AzerothCore wiki documentation."""

    # Known wiki pages and their topics
    WIKI_PAGES = {
        "gameobject_template": "docs/gameobject_template.md",
        "item_template": "docs/item_template.md",
        "quest_template": "docs/quest_template.md",
        "creature_template": "docs/creature_template.md",
        "lock": "docs/lock.md",
        "loot_template": "docs/loot_template.md",
    }

    # Type-specific hints for common data patterns
    TYPE_HINTS = {
        "lock_dbc": {
            "structure": "Lock.dbc contains lock definitions used by gameobject_template and item_template. Each lock has up to 8 lock slots.",
            "field_groups": {
                "0": "ID - Lock definition ID",
                "1-8": "Type[8] - LockKeyType per slot (from SharedDefines.h): LOCK_KEY_NONE(0), LOCK_KEY_ITEM(1), LOCK_KEY_SKILL(2), LOCK_KEY_SPELL(3)",
                "9-16": "Index[8] - If Type=1: key item ID; If Type=2: LockType enum value",
                "17-24": "Skill[8] - Required skill level (e.g., 25 for mining at skill 0)",
                "25-32": "Action[8] - **commented out in DBCStructure.h, unused**",
            },
            "locktype_map": {
                1: "Lockpicking - Requires Pick Lock skill",
                2: "Herbalism - Herb gathering (skill level required)",
                3: "Mining - Ore deposit mining (skill level required)",
                4: "Disarm Trap",
                5: "Open - Generic unlock action",
                6: "Treasure - Special treasure lock",
                7: "Calcified Elven Gems",
                8: "Close",
                9: "Arm Trap",
                10: "Quick Open",
                11: "Quick Close",
                12: "Open Tinkering",
                13: "Open Kneeling - Requires kneeling to open",
                14: "Open Attacking - Requires attacking state",
                15: "Gahz'ridian - Special Gahz'ridian lock",
                16: "Blasting",
                17: "Slow Open",
                18: "Slow Close",
                19: "Fishing",
                20: "Inscription",
                21: "Open from Vehicle",
            },
        },
        "gameobject_template": {
            "type_field_index": 1,
            "type_map": {
                0: "DOOR - data0: startOpen, data1: LockId, data2: autoClose (ms)",
                1: "BUTTON - data0: startOpen, data1: LockId, data3: linkedTrap",
                2: "QUESTGIVER - data0: LockId, data1: questList, data3: gossipID",
                3: "CHEST - data0: LockId, data1: chestLoot (gameobject_loot_template), data2: restockTime, data3: consumable",
                4: "BINDER - Unused type",
                5: "GENERIC - data0: floatingTooltip, data1: highlight, data5: questID",
                6: "TRAP - data0: LockId, data1: level, data3: spell, data4: type (0=no despawn, 1=despawn after cast)",
                7: "CHAIR - data0: chairslots, data1: height",
                8: "SPELL_FOCUS - data0: spellFocusType, data1: diameter, data2: linkedTrap",
                9: "TEXT - data0: pageID, data1: language, data2: pageMaterial",
                10: "GOOBER - data0: LockId, data1: questID, data5: consumable, data19: gossipID (cast spell when used)",
                11: "TRANSPORT - data0-23: transport timing and floor events",
                12: "AREADAMAGE - data0: open, data1: radius, data2-4: damage values/school",
                13: "CAMERA - data0: LockId, data1: CinematicCamera dbc entry",
                14: "MAP_OBJECT - No data used",
                15: "MO_TRANSPORT - data0: taxiPathID, data1: moveSpeed",
                22: "SPELLCASTER - data0: spell, data1: charges, data2: partyOnly",
            },
        },
        "quest_template": {
            "key_fields": {
                "0": "ID - Unique quest identifier",
                "74": "LogTitle - Quest journal title",
                "75": "LogDescription - Quest objective description in journal",
                "76": "QuestDescription - Detailed quest text (use $B for line breaks)",
                "87": "RequiredItemId1 - Item needed for quest completion",
                "93": "RequiredItemCount1 - Quantity of item needed",
            },
        },
        "item_template": {
            "class_field_index": 1,
            "class_map": {
                0: "None (Generic)",
                1: "Consumable",
                2: "Container",
                3: "Weapon",
                4: "Armor",
                5: "Reagent",
                7: "Gem",
                8: "Libram",
                9: "Ring",
                10: "Trinket",
                11: "Cloth",
                12: "Quest Item (always stackable, never sold)",
            },
        },
    }

    def __init__(self, wiki_path: Optional[str] = None):
        """
        Initialize the hint generator.

        Args:
            wiki_path: Path to the AzerothCore wiki directory (optional)
        """
        self.wiki_path = Path(wiki_path) if wiki_path else self._find_wiki()
        self._loaded_pages: Dict[str, str] = {}

    def _find_wiki(self) -> Path:
        """Find the wiki directory relative to this module."""
        possible_paths = [
            Path(__file__).parent.parent / "acorewiki",
            Path("/home/luke/GIT/acorewiki"),
            Path("~/GIT/acorewiki").expanduser(),
        ]

        for path in possible_paths:
            if path.exists():
                return path

        return Path(".")  # Default to current dir if not found

    def _load_wiki_page(self, page_name: str) -> Optional[str]:
        """Load and cache a wiki markdown page."""
        if page_name in self._loaded_pages:
            return self._loaded_pages[page_name]

        wiki_file = self.WIKI_PAGES.get(page_name)
        if not wiki_file:
            return None

        file_path = self.wiki_path / wiki_file
        if file_path.exists():
            with open(file_path, "r", encoding="utf-8") as f:
                self._loaded_pages[page_name] = f.read()
                return self._loaded_pages[page_name]

        return None

    def _extract_gameobject_type_hint(self, result: Dict[str, Any]) -> Optional[str]:
        """Generate hint for GameObject based on type field."""
        go_info = self.TYPE_HINTS.get("gameobject_template", {})
        type_index = str(go_info.get("type_field_index", 1))

        if type_index not in result:
            return None

        try:
            go_type = int(result[type_index])
            return go_info.get("type_map", {}).get(
                go_type, f"Unknown GO Type: {go_type}"
            )
        except (ValueError, TypeError):
            return None

    def _extract_item_class_hint(self, result: Dict[str, Any]) -> Optional[str]:
        """Generate hint for Item based on class field."""
        item_info = self.TYPE_HINTS.get("item_template", {})
        class_index = str(item_info.get("class_field_index", 1))

        if class_index not in result:
            return None

        try:
            item_class = int(result[class_index])
            return f"Item Class: {item_info.get('class_map', {}).get(item_class, f'Unknown ({item_class})')}"
        except (ValueError, TypeError):
            return None

    def _extract_quest_key_fields(self, result: Dict[str, Any]) -> List[str]:
        """Extract key field hints for Quest data."""
        quest_info = self.TYPE_HINTS.get("quest_template", {})
        hints = []

        for idx_str, description in quest_info.get("key_fields", {}).items():
            if idx_str in result and result[idx_str]:
                hints.append(f"Field {idx_str}: {description} = '{result[idx_str]}'")

        return hints

    def _extract_lock_hints(self, result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Generate hints for Lock DBC data with slot-by-slot interpretation."""
        lock_info = self.TYPE_HINTS.get("lock_dbc", {})
        field_groups = lock_info.get("field_groups", {})
        locktype_map = lock_info.get("locktype_map", {})

        hints: Dict[str, Any] = {
            "table": "lock_dbc" if "Lock" in str(result) else "lock",
            "context": [lock_info.get("structure", "")],
            "slot_details": [],
            "notes": [],
        }

        # Parse each of the 8 lock slots
        for slot_num in range(1, 9):
            # Try both string and integer keys since DBC can use either
            int_key = slot_num  # Use int key first (DBC reader uses ints)
            str_key = str(slot_num)

            props_int_key = slot_num + 8
            props_str_key = str(props_int_key)

            skill_int_key = slot_num + 16
            skill_str_key = str(skill_int_key)

            lock_type = result.get(str_key)
            if lock_type is None and int_key in result:
                lock_type = result[int_key]

            props_value = result.get(props_str_key)
            if props_value is None and props_int_key in result:
                props_value = result[props_int_key]

            required_skill = result.get(skill_str_key)
            if required_skill is None and skill_int_key in result:
                required_skill = result[skill_int_key]

            try:
                lock_type_str = str(lock_type) if lock_type is not None else ""
                props_str = str(props_value) if props_value is not None else ""
                skill_str = str(required_skill) if required_skill is not None else ""

                lock_type_int = int(lock_type_str) if lock_type_str.strip() else 0
                props_int = int(props_str) if props_str.strip() else 0
                skill_int = int(skill_str) if skill_str.strip() else 0
                action_int = 0  # Not used in this simple implementation

                if lock_type_int == 0:
                    continue  # Empty slot

                slot_detail: Dict[str, Any] = {
                    "slot": slot_num,
                    "type": lock_type_int,
                    "properties": props_int,
                    "required_skill": skill_int,
                    "action": action_int,
                }

                if lock_type_int == 1:
                    # Type=1: Key item ID
                    slot_detail["description"] = (
                        f"Requires key item ID {props_int} to unlock"
                    )
                elif lock_type_int == 2:
                    # Type=2: LockType.dbc reference
                    locktype_name = locktype_map.get(
                        props_int, f"Unknown LockType ({props_int})"
                    )
                    skill_note = f" (skill level {skill_int})" if skill_int > 0 else ""
                    slot_detail["description"] = f"Requires {locktype_name}{skill_note}"

                hints["slot_details"].append(slot_detail)

            except (ValueError, TypeError):
                continue

        # Add field group structure info
        for group_range, description in field_groups.items():
            hints["context"].append(f"Fields {group_range}: {description}")

        if not hints["slot_details"]:
            hints["notes"].append(
                "No lock slots configured. This is an empty lock definition."
            )

        return hints

    def generate_hints(
        self, table_name: str, result: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Generate contextual hints for query results.

        Args:
            table_name: The database table or DBC type name
            result: The query result data (dict of field_index -> value)

        Returns:
            Dictionary with hints or None if no relevant hints found
        """
        hints = {
            "table": table_name,
            "context": [],
            "related_tables": [],
            "notes": [],
        }

        # GameObject-specific hints
        if table_name == "gameobject_template" or (
            "GameObject" in str(result.get("3", ""))
        ):
            type_hint = self._extract_gameobject_type_hint(result)
            if type_hint:
                hints["context"].append(type_hint)

            # Check for chest loot reference
            data1 = result.get("9")  # data1 field (index 9 in SQL, but check DBC too)
            if data1:
                try:
                    loot_id = int(data1)
                    hints["related_tables"].append(
                        f"gameobject_loot_template.entry={loot_id} (chestLoot)"
                    )
                    hints["notes"].append(
                        "This is a CHEST type object. data1 references the loot template ID."
                    )
                except (ValueError, TypeError):
                    pass

        # Item-specific hints
        if table_name == "item_template" or table_name == "item_dbc":
            class_hint = self._extract_item_class_hint(result)
            if class_hint:
                hints["context"].append(class_hint)

            # Check for name field to add quest info
            name_field = None
            for idx, val in result.items():
                if "Milly" in str(val):
                    name_field = idx
                    break

        # Quest-specific hints
        if table_name == "quest_template":
            quest_info = self.TYPE_HINTS.get("quest_template", {})
            for idx_str, description in quest_info.get("key_fields", {}).items():
                if idx_str in result and result[idx_str]:
                    hints["context"].append(
                        f"Field {idx_str}: {description} = '{result[idx_str]}'"
                    )

            # Extract quest completion requirements (field 87 is RequiredItemId1)
            required_item_id = result.get("87")
            if required_item_id:
                try:
                    item_id = int(str(required_item_id).split()[0])
                    hints["related_tables"].append(
                        f"item_template.entry={item_id} (RequiredItem)"
                    )
                except (ValueError, TypeError):
                    pass

        # Lock-specific hints
        if "lock" in table_name.lower() or table_name == "Lock":
            lock_hints = self._extract_lock_hints(result)
            if lock_hints:
                return lock_hints

        # Filter out empty hint sections
        if not any([hints["context"], hints["related_tables"], hints["notes"]]):
            return None

        return hints


def add_hints_to_result(
    query_result: Dict[str, Any], table_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Convenience function to add wiki-based hints to a query result.

    Args:
        query_result: The full query result including 'result' and optionally 'metadata'
        table_name: Explicit table name override (optional)

    Returns:
        Query result with added hints section if applicable
    """
    result_data = query_result.get("result", {})
    metadata = query_result.get("metadata", {})

    # Determine table name from metadata if not provided
    if not table_name:
        sources_found = metadata.get("sources_found", [])
        if sources_found:
            table_name = sources_found[0]

    if not table_name or not result_data:
        return query_result

    hint_gen = WikiHints()
    hints = hint_gen.generate_hints(table_name, result_data)

    if hints:
        query_result["hints"] = hints

    return query_result


if __name__ == "__main__":
    # Test the hint generator
    test_result = {
        "0": "161557",
        "1": "3",
        "2": "3012",
        "3": "Milly's Harvest",
        "9": "10119",
    }

    hint_gen = WikiHints()
    hints = hint_gen.generate_hints("gameobject_template", test_result)
    print(f"Generated hints: {hints}")
