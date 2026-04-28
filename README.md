# dbc-query

MCP (Model Context Protocol) server for querying all AzerothCore datastores — DBC binary files, SQL tables, and their overlays — in the exact same manner as the server loads them.

## Overview

This tool gives AI assistants access to all ~308 AzerothCore datastores through MCP, covering:

- **112 DBC-backed stores** — Binary `.dbc` files with optional SQL overlay tables (`*_dbc`)
- **60 SQL ObjectMgr stores** — Tables loaded by `sObjectMgr` (creature_template, quest_template, etc.)
- **51 SQL Manager stores** — Tables loaded by manager singletons like `sSpellMgr`, `sSmartScriptMgr`, etc.
- **85 SQL Auxiliary stores** — Supplementary tables (loot templates, quest items, etc.)

**Key capability:** Cross-referencing C++ struct names, SQL table names, DBC file names, and store variables so an LLM can navigate the codebase efficiently.

## Tools

### 1. `query_dbc` — Query DBC binary files

```python
mcp__dbc_query__query_dbc(dbc_name="Spell", id=2567)
mcp__dbc_query__query_dbc(dbc_name="SkillLineAbility", filter={"2": 2567}, columns=[0, 1, 2])
mcp__dbc_query__query_dbc(dbc_name="Spell", info=True)
```

### 2. `query_game_data` — Unified query across all datastore types

Merges DBC binary data with SQL overlays, or queries SQL-only stores:

```python
# DBC + SQL overlay merge (spell_dbc table overlays Spell.dbc)
mcp__dbc_query__query_game_data(dbc_name="Spell", id=2567)

# SQL ObjectMgr store
mcp__dbc_query__query_game_data(dbc_name="creature_template", id=1)

# SQL Manager store
mcp__dbc_query__query_game_data(dbc_name="smart_scripts", filter={"entryorguid": 1000})

# Field selection - limit to specific fields
mcp__dbc_query__query_game_data(
    dbc_name="Spell", 
    id=118,
    fields=[38, 39]  # BaseLevel, SpellLevel
)

# Field selection with names (v2.0+)
mcp__dbc_query__query_game_data(
    dbc_name="Spell",
    id=118,
    fields=["BaseLevel", "SpellLevel"]
)

# Compact mode strips nulls (default) - v2.0+
mcp__dbc_query__query_game_data(
    dbc_name="SkillLine", 
    id=6,
    compact=True  # default: strips nulls, omits raw section
)

# String filters with LIKE - v2.0+
mcp__dbc_query__query_game_data(
    dbc_name="Item",
    filter={"Name": {"$like": "%Sword%"}},  # SQL LIKE
    limit=5
)

mcp__dbc_query__query_game_data(
    dbc_name="Item",
    filter={"Name": {"$ilike": "%sword%"}},  # case-insensitive
    limit=5
)
```

### 3. `describe_fields` — Get field metadata with SQL/struct cross-references

Returns field names, types, SQL column names, struct field names, and access hints:

```python
mcp__dbc_query__describe_fields(dbc_name="Spell")
# Returns: field_count=234, struct=SpellEntry, sql_table=spell_dbc,
#          access=sSpellStore.LookupEntry(id), fields with names + sql_columns
```

### 4. `lookup_datastore` — Cross-reference lookup

Resolve by struct name, SQL table, DBC file, or store variable:

```python
mcp__dbc_query__lookup_datastore(query="SpellEntry")       # by C++ struct
mcp__dbc_query__lookup_datastore(query="creature_template") # by SQL table
mcp__dbc_query__lookup_datastore(query="sSpellStore")       # by store variable
mcp__dbc_query__lookup_datastore(query="Spell.dbc")         # by DBC file
```

### 5. `execute_sql` — Run SQL queries on acore_world

```python
mcp__dbc_query__execute_sql(sql="SELECT entry, name FROM creature_template LIMIT 5")
```

### 6. `list_stores` — Browse datastores by category

```python
mcp__dbc_query__list_stores(category="sql_manager")  # 51 SQL manager stores
mcp__dbc_query__list_stores(category="dbc_backed")    # 112 DBC-backed stores
mcp__dbc_query__list_stores(search="spell")            # Search across all stores
```

### 7. `list_dbcs` — List available DBC files

```python
mcp__dbc_query__list_dbcs(search="Spell")
```

## v2.0 Improvements

### Field Selection

Limit output by requesting specific fields using indices or names:

```python
# Numeric indices
fields=[38, 39, 54]  # BaseLevel, SpellLevel, Reagent[0]

# Field names (C++ struct or SQL column)
fields=["BaseLevel", "SpellLevel"]

# Mixed
fields=[38, "SpellLevel", 54]
```

This dramatically reduces response size. For example, `Spell id=118` with `fields=[38, 39]` returns ~20 lines instead of ~2000.

### Compact Mode (Default)

By default (`compact=True`), responses are optimized:
- ✅ Null/empty fields stripped (no `FieldNNN: None`)
- ✅ Redundant `raw` section omitted
- ✅ Single ID lookups return flat arrays (`[field1, field2...]`)
- ✅ Multi-record results remain nested (`[[row1], [row2]]`)

For debugging, set `compact=False` to get full readout with all fields and raw duplicates.

### Empty Results

When no data is found:
- Returns `{}` instead of `[]`
- Includes `metadata.empty_reason` explaining why
- Provides `suggestion` if typo detected

### Typo Recovery

Store name typos suggest corrections from:
- Registry C++ struct names (e.g., `SpellEntry`)
- SQL table names (e.g., `spell_proc_event`)
- All discovered database tables

```python
query_game_data("creature_templat")  
# → "Did you mean: creature_template (struct), quest_template (table)?"

query_game_data("spel_proc_event")  
# → "Did you mean: spell_proc_event (table)?"
```

### String Filters & LIKE Queries

Search string fields using SQL patterns:

```python
# Case-sensitive LIKE
filter={"Name": {"$like": "%Polymorph%"}}

# Case-insensitive (ILIKE)
filter={"Name": {"$ilike": "%polymorph%"}}

# Direct equality (for array locale fields)
filter={"Name[3]": "First Aid"}  # English locale
```

**Pattern Escaping:** Special SQL chars (`%`, `_`) are auto-escaped with `\`. Warnings appear in metadata if escaping occurred.

**Note:** LIKE queries require a SQL overlay table. If none exists, a helpful error suggests using `execute_sql` directly.

## Requirements

- Python 3.7+
- AzerothCore DBC files (typically in `env/dist/bin/dbc/`)
- AzerothCore source code (for DBCfmt.h format definitions)
- MySQL/MariaDB (for SQL queries and overlay merges)

## Installation

1. **Clone and configure:**
   ```bash
   git clone https://github.com/avirar/dbc-query.git ~/dbc-query
   ```

2. **Generate the datastore registry (optional — pre-generated):**
   ```bash
   python3 generate_registry.py
   # Creates datastore_registry.json from docs/datastores/*.md
   ```

3. **Test the integration:**
   ```bash
   ./test_integration.sh
   ```

4. **Configure as MCP server:**

   **opencode** — add to `~/.config/opencode/opencode.jsonc` in the `"mcp"` section:
   ```jsonc
   {
     "mcp": {
       "dbc_query": {
         "type": "local",
         "command": ["python3", "/path/to/dbc-query/server.py"],
         "environment": {
           "DBC_PATH": "/path/to/azerothcore-wotlk/env/dist/bin/dbc",
           "DBC_FORMAT_FILE": "/path/to/azerothcore-wotlk/src/server/shared/DataStores/DBCfmt.h"
         },
         "enabled": true
       }
     }
   }
   ```

   **Claude Code** — add to `~/.claude.json` in the `"mcpServers"` section:
   ```json
   {
     "mcpServers": {
       "dbc_query": {
         "type": "stdio",
         "command": "python3",
         "args": ["/path/to/dbc-query/server.py"],
         "env": {
           "DBC_PATH": "/path/to/azerothcore-wotlk/env/dist/bin/dbc",
           "DBC_FORMAT_FILE": "/path/to/azerothcore-wotlk/src/server/shared/DataStores/DBCfmt.h"
         }
       }
     }
   }
   ```

   **Important:** Update the paths to match your installation. DB credentials are optional — if omitted, the server auto-detects them from `worldserver.conf`. To override, set `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` environment variables.

## Architecture

```
server.py                 MCP server with 7 tools
├── dbc_reader.py         WDBC binary file parser
├── format_parser.py      DBCfmt.h format string parser
├── struct_parser.py      DBCStructure.h field name extractor
├── datastore_registry.json  308 datastore entries + field mappings
├── generate_registry.py  Parser that generates registry from markdown docs
└── generate_supplementary.py  Adds supplementary SQL tables from database
```

### Datastore Registry

`datastore_registry.json` is the core metadata file with:

- **308 datastore entries** across 4 categories (dbc_backed, sql_objectmgr, sql_manager, sql_auxiliary)
- **Field mappings** with SQL column names, C++ types, and field names
- **5 lookup indices** (by struct name, SQL table, DBC file, store variable, name)

Generated by `generate_registry.py` from AzerothCore datastore documentation in `docs/datastores/`. Additional tables added via `generate_supplementary.py` by querying the database.

### DBC Overlay Mechanism

AzerothCore loads DBC binary files first, then overlays entries from matching SQL tables (e.g., `spell_dbc` overlays `Spell.dbc`). The `query_game_data` tool merges both sources, with SQL taking precedence.

## Performance

- **DBC first query:** ~100-500ms (loads and caches)
- **DBC subsequent queries:** ~1-10ms (from cache)
- **SQL queries:** ~10-100ms depending on query complexity
- **Registry lookup:** <1ms (in-memory JSON)

## License

GNU AGPL v3
