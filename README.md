# dbc-query

MCP (Model Context Protocol) server for querying World of Warcraft DBC (Database Client) files directly.

## Overview

This tool allows AI assistants to query WoW DBC files without requiring SQL import. It reads WDBC format files directly and provides a query interface through the MCP protocol.

**Why use this instead of SQL?**
- ✅ No manual DBC→SQL conversion needed
- ✅ Automatically works with DBC file updates
- ✅ Accesses all 246 DBC files, not just imported ones
- ✅ Lightweight - no database overhead
- ✅ Portable across AzerothCore installations

## Features

- **Direct WDBC file parsing** (WoW 3.3.5 / WotLK format)
- **Automatic format detection** from AzerothCore DBCfmt.h
- **Field name mappings** extracted from DBCStructure.h (85 DBCs, 982 fields)
- **Multiple query modes**: by ID, row index, or field filters
- **Column selection** for optimized results
- **DBC caching** for performance
- **246 DBC files supported** out of the box

## Requirements

- Python 3.7+
- AzerothCore DBC files (typically in `env/dist/bin/dbc/`)
- AzerothCore source code (for DBCfmt.h format definitions)
- Claude Code (for MCP integration)

## Installation

1. **Clone this repository:**
   ```bash
   git clone https://github.com/YOUR_USERNAME/dbc-query.git ~/dbc-query
   cd ~/dbc-query
   ```

2. **Verify Python version:**
   ```bash
   python3 --version  # Should be 3.7 or higher
   ```

3. **Generate field mappings (optional - already included):**
   ```bash
   # Field mappings are pre-generated, but you can regenerate them:
   python3 struct_parser.py
   # This creates field_mappings.json from DBCStructure.h
   ```

4. **Test the standalone tools:**
   ```bash
   # Test format parser
   python3 format_parser.py

   # Test DBC reader
   python3 dbc_reader.py SkillLineAbility 0

   # Test MCP server
   echo '{"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}' | python3 server.py
   ```

5. **Configure Claude Code MCP server:**

   Add to your `~/.claude.json` in the `mcpServers` section:
   ```json
   {
     "mcpServers": {
       "dbc_query": {
         "type": "stdio",
         "command": "python3",
         "args": ["/root/dbc-query/server.py"],
         "env": {
           "DBC_PATH": "/root/azerothcore-wotlk/env/dist/bin/dbc",
           "DBC_FORMAT_FILE": "/root/azerothcore-wotlk/src/server/shared/DataStores/DBCfmt.h"
         }
       }
     }
   }
   ```

   **Important:** Update the paths to match your installation:
   - `DBC_PATH`: Location of your .dbc files
   - `DBC_FORMAT_FILE`: Path to DBCfmt.h in your AzerothCore source

6. **Restart Claude Code** to load the MCP server

## Usage

### Standalone Command-Line Usage

**Query by DBC name and row index:**
```bash
python3 dbc_reader.py Spell 0
python3 dbc_reader.py SkillLineAbility 1550
```

**List available formats:**
```bash
python3 format_parser.py
```

**Test integration:**
```bash
./test_integration.sh
```

### MCP Tool Usage (from Claude Code)

After configuration, Claude will have access to these tools:

#### 1. Query DBC Files (`query_dbc`)

**Get record by ID:**
```python
# Find spell 2567
mcp__dbc_query__query_dbc(dbc_name="Spell", id=2567)
```

**Get record by row index:**
```python
mcp__dbc_query__query_dbc(dbc_name="SkillLineAbility", row_index=0)
```

**Filter by field values:**
```python
# Find all SkillLineAbility entries for spell 2567
# Field 2 = spell ID
mcp__dbc_query__query_dbc(
    dbc_name="SkillLineAbility",
    filter={"2": 2567}
)
```

**Select specific columns:**
```python
# Only return fields 0, 1, 2, 3, 4
mcp__dbc_query__query_dbc(
    dbc_name="SkillLineAbility",
    filter={"2": 2567},
    columns=[0, 1, 2, 3, 4]
)
```

**Get DBC file info:**
```python
mcp__dbc_query__query_dbc(dbc_name="Spell", info=true)
```

#### 2. List Available DBCs (`list_dbcs`)

**List all DBCs:**
```python
mcp__dbc_query__list_dbcs()
```

**Search for specific DBCs:**
```python
mcp__dbc_query__list_dbcs(search="Spell")
mcp__dbc_query__list_dbcs(search="Talent")
```

#### 3. Describe DBC Fields (`describe_fields`)

**Get field names and types for a DBC:**
```python
# Get all field information for Spell.dbc
mcp__dbc_query__describe_fields(dbc_name="Spell")

# Returns:
# {
#   "dbc": "Spell",
#   "field_count": 234,
#   "mapped_fields": 184,    # Fields with known names
#   "unmapped_fields": 50,   # Fields named "FieldN"
#   "fields": [
#     {"index": 0, "name": "Id", "type": "uint32", "format_char": "n", "has_mapping": true},
#     {"index": 136, "name": "SpellName[0]", "type": "string_array", "format_char": "s", "has_mapping": true},
#     {"index": 153, "name": "Rank[0]", "type": "string_array", "format_char": "s", "has_mapping": true},
#     ...
#   ]
# }
```

**Example usage - Find spell name field:**
```python
# Describe fields to find the name field
fields = mcp__dbc_query__describe_fields(dbc_name="Spell")

# Look for "Name" in field names
name_fields = [f for f in fields["result"]["fields"] if "Name" in f["name"]]
# Returns: SpellName[0] at index 136

# Now query just the fields you need
spell = mcp__dbc_query__query_dbc(
    dbc_name="Spell",
    id=133,
    columns=[0, 136, 153]  # ID, Name, Rank
)
```

**Benefits:**
- 🔍 **Discover field meanings** without consulting external documentation
- 📊 **See field types** (uint32, float, string, etc.)
- ✅ **Know which fields are mapped** vs unnamed
- 🎯 **Optimize queries** by selecting only needed columns

**Field name coverage:**
- **Spell.dbc**: 184/234 fields (78.6%)
- **SkillLineAbility.dbc**: 10/14 fields (71.4%)
- **Item.dbc**: Varies by DBC
- **Total**: 85 DBCs with field mappings

**Unmapped fields:**
Fields without mappings are shown as `FieldN` (e.g., `Field42`). These are typically unused fields or fields without comments in the AzerothCore source code.

## Architecture

### Core Modules

- **`server.py`** - MCP server implementation
  - JSON-RPC 2.0 protocol handler
  - Tool registration and execution
  - DBC caching for performance

- **`dbc_reader.py`** - WDBC binary file parser
  - Header parsing (signature, record count, etc.)
  - Binary data section parsing
  - String table resolution
  - Query interface (filter, columns, ID/row lookup)

- **`format_parser.py`** - DBCfmt.h format string parser
  - Extracts format strings from C++ header
  - DBC name mapping (e.g., Spell → SpellEntry)
  - Field count and record size calculation

- **`struct_parser.py`** - DBCStructure.h field name extractor
  - Parses C++ struct definitions to extract field names and types
  - Handles array fields spanning multiple indices (e.g., `SpellName[0-15]`)
  - Generates `field_mappings.json` with 85 DBCs, 982 fields
  - Run manually: `python3 struct_parser.py` to regenerate mappings

### Field Name Extraction

Field names are extracted from `DBCStructure.h` by parsing C++ struct comments:

```cpp
// From DBCStructure.h:
struct SpellEntry {
    uint32 Id;                                    // 0
    uint32 Category;                              // 1
    std::array<char const*, 16> SpellName;        // 136-151
    std::array<char const*, 16> Rank;             // 153-168
    ...
};
```

The `struct_parser.py` tool extracts these definitions and creates a JSON mapping:
```json
{
  "Spell": {
    "0": {"name": "Id", "type": "uint32"},
    "136": {"name": "SpellName[0]", "type": "string_array"},
    "153": {"name": "Rank[0]", "type": "string_array"}
  }
}
```

This mapping is loaded at runtime and used by the `describe_fields` tool.

### WDBC File Format

```
Header (20 bytes):
  - Signature: 'WDBC' (4 bytes)
  - RecordCount: uint32 (4 bytes)
  - FieldCount: uint32 (4 bytes)
  - RecordSize: uint32 (4 bytes)
  - StringBlockSize: uint32 (4 bytes)

Data Section: RecordCount × RecordSize bytes
String Table: StringBlockSize bytes (null-terminated strings)
```

### Format String Characters

- `i`, `n`, `d`, `l` = uint32 (4 bytes)
- `f` = float (4 bytes)
- `s` = string offset into string table (4 bytes)
- `b` = uint8 (1 byte)
- `x` = skip/unused (4 bytes)
- `X` = skip/unused (1 byte)

## Examples

### Example 1: Investigating Spell 2567 Bug

```python
# Get spell info
result = mcp__dbc_query__query_dbc(dbc_name="Spell", id=2567, columns=[0, 136])
# Returns: {0: 2567, 136: "Thrown"}

# Check class restrictions in SkillLineAbility
result = mcp__dbc_query__query_dbc(
    dbc_name="SkillLineAbility",
    filter={"2": 2567},
    columns=[0, 1, 2, 3, 4]
)
# Returns: {0: 1550, 1: 176, 2: 2567, 3: 0, 4: 0}
# ClassMask=0 confirms the bug!
```

### Example 2: Finding All Talents for a Class

```python
# List talent-related DBCs
mcp__dbc_query__list_dbcs(search="Talent")

# Query talents (field 8 = class ID, 0 = all classes)
mcp__dbc_query__query_dbc(
    dbc_name="Talent",
    filter={"8": 1},  # Warrior class
    limit=50
)
```

### Example 3: Exploring Zone Data

```python
# Get zone name and info
mcp__dbc_query__query_dbc(dbc_name="AreaTable", id=1519)
# Returns zone data including name strings
```

## Troubleshooting

**MCP server not appearing in Claude Code:**
- Ensure paths in `~/.claude.json` are correct
- Restart Claude Code after configuration changes
- Check `DBC_PATH` points to directory containing .dbc files
- Verify `DBC_FORMAT_FILE` points to DBCfmt.h

**"No format found for DBC" error:**
- Check DBC name spelling (case-sensitive)
- Try adding "Entry" suffix (e.g., "SpellEntry" instead of "Spell")
- Run `python3 format_parser.py` to see available formats

**"File not found" error:**
- Verify DBC file exists in `DBC_PATH`
- Check file permissions (should be readable)
- Ensure DBC_PATH in environment is correct

**Format string mismatch:**
- DBC file may be from different WoW version
- Check DBCfmt.h is from matching AzerothCore version
- Verify DBC wasn't corrupted during extraction

## Performance

- **First query:** ~100-500ms (loads and caches DBC)
- **Subsequent queries:** ~1-10ms (from cache)
- **Memory usage:** ~10-50MB per cached DBC
- **Supported DBC count:** 246 files

## Tested DBCs

Successfully tested with:
- **Spell.dbc**: 49,839 records, 234 fields
- **SkillLineAbility.dbc**: 10,219 records, 14 fields
- **AreaTable.dbc**: 2,307 records, 36 fields
- **Item.dbc**: 46,096 records, 8 fields
- **Talent.dbc**: 892 records, 23 fields
- **Achievement.dbc**: 1,817 records, 62 fields

## Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Make your changes with tests
4. Submit a pull request

## License

This project is licensed under the GNU AGPL v3 License - see the LICENSE file for details.

## Acknowledgments

- AzerothCore team for DBC format documentation
- Model Context Protocol specification
- WDBXEditor for DBC format insights
