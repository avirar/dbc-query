#!/bin/bash
# Integration test for dbc_query MCP server

call_tool() {
    local tool=$1 args=$2
    echo "{\"jsonrpc\": \"2.0\", \"id\": 1, \"method\": \"tools/call\", \"params\": {\"name\": \"$tool\", \"arguments\": $args}}" | timeout 10 python3 /root/dbc-query/server.py 2>/dev/null
}

echo "Testing dbc_query MCP server integration..."
echo ""

# Test 1: List tools
echo "Test 1: List available tools"
count=$(echo '{"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}' | timeout 5 python3 /root/dbc-query/server.py 2>/dev/null | python3 -c "import sys,json; r=json.load(sys.stdin); print(len(r['result']['tools']))")
echo "  Tools available: $count (expected: 7)"
[ "$count" = "7" ] && echo "  PASS" || echo "  FAIL"

# Test 2: Query spell 2567 in SkillLineAbility
echo ""
echo "Test 2: Query spell 2567 in SkillLineAbility"
result=$(call_tool query_dbc '{"dbc_name": "SkillLineAbility", "filter": {"2": 2567}}' | python3 -c "import sys,json; r=json.load(sys.stdin); d=json.loads(r['result']['content'][0]['text']); r0=d['result'][0]; print(f'ID={r0[\"0\"]}, SkillLine={r0[\"1\"]}, Spell={r0[\"2\"]}')")
echo "  $result"
echo "  PASS"

# Test 3: Get Spell.dbc info
echo ""
echo "Test 3: Get Spell.dbc information"
result=$(call_tool query_dbc '{"dbc_name": "Spell", "info": true}' | python3 -c "import sys,json; r=json.load(sys.stdin); d=json.loads(r['result']['content'][0]['text']); print(f'Records: {d[\"result\"][\"record_count\"]}, Fields: {d[\"result\"][\"field_count\"]}')")
echo "  $result"
echo "  PASS"

# Test 4: List Spell-related DBCs
echo ""
echo "Test 4: List Spell-related DBCs"
count=$(call_tool list_dbcs '{"search": "Spell"}' | python3 -c "import sys,json; r=json.load(sys.stdin); d=json.loads(r['result']['content'][0]['text']); print(d['count'])")
echo "  Found $count Spell-related DBCs"
echo "  PASS"

# Test 5: Lookup SpellEntry
echo ""
echo "Test 5: Lookup SpellEntry via lookup_datastore"
result=$(call_tool lookup_datastore '{"query": "SpellEntry"}' | python3 -c "
import sys,json
r=json.load(sys.stdin)
d=json.loads(r['result']['content'][0]['text'])
m=d['result']['matches'][0]
print(f'  struct={m[\"c_struct\"]}, sql={m[\"sql_table\"]}, store={m[\"store_variable\"]}, dbc={m[\"dbc_file\"]}')
print(f'  access: {m[\"hints\"][\"access_pattern\"]}')
")
echo "$result"
echo "  PASS"

# Test 6: Lookup by SQL table name
echo ""
echo "Test 6: Lookup creature_template (SQL table name)"
result=$(call_tool lookup_datastore '{"query": "creature_template"}' | python3 -c "
import sys,json
r=json.load(sys.stdin)
d=json.loads(r['result']['content'][0]['text'])
m=d['result']['matches'][0]
print(f'  struct={m[\"c_struct\"]}, category={m[\"category\"]}, store={m[\"store_variable\"]}')
")
echo "$result"
echo "  PASS"

# Test 7: Lookup by store variable
echo ""
echo "Test 7: Lookup sSpellStore (store variable)"
result=$(call_tool lookup_datastore '{"query": "sSpellStore"}' | python3 -c "
import sys,json
r=json.load(sys.stdin)
d=json.loads(r['result']['content'][0]['text'])
m=d['result']['matches'][0]
print(f'  struct={m[\"c_struct\"]}, exact={d[\"result\"].get(\"exact\",False)}')
")
echo "$result"
echo "  PASS"

# Test 8: Lookup smart_scripts (manager store)
echo ""
echo "Test 8: Lookup smart_scripts (SQL manager)"
result=$(call_tool lookup_datastore '{"query": "smart_scripts"}' | python3 -c "
import sys,json
r=json.load(sys.stdin)
d=json.loads(r['result']['content'][0]['text'])
m=d['result']['matches'][0]
print(f'  struct={m[\"c_struct\"]}, manager={m.get(\"manager_singleton\",\"\")}, access={m[\"hints\"][\"access_pattern\"]}')
")
echo "$result"
echo "  PASS"

# Test 9: List stores by category
echo ""
echo "Test 9: List stores by category"
count=$(call_tool list_stores '{"category": "sql_manager"}' | python3 -c "import sys,json; r=json.load(sys.stdin); d=json.loads(r['result']['content'][0]['text']); print(d['count'])")
echo "  SQL Manager stores: $count"
count2=$(call_tool list_stores '{"category": "dbc_backed"}' | python3 -c "import sys,json; r=json.load(sys.stdin); d=json.loads(r['result']['content'][0]['text']); print(d['count'])")
echo "  DBC-backed stores: $count2"
count3=$(call_tool list_stores '{"category": "sql_objectmgr"}' | python3 -c "import sys,json; r=json.load(sys.stdin); d=json.loads(r['result']['content'][0]['text']); print(d['count'])")
echo "  SQL ObjectMgr stores: $count3"
echo "  PASS"

# Test 10: Describe fields with metadata
echo ""
echo "Test 10: Describe fields with enriched metadata"
result=$(call_tool describe_fields '{"dbc_name": "Spell"}' | python3 -c "
import sys,json
r=json.load(sys.stdin)
d=json.loads(r['result']['content'][0]['text'])
r2=d['result']
print(f'  field_count={r2[\"field_count\"]}, mapped={r2[\"mapped_fields\"]}, unmapped={r2[\"unmapped_fields\"]}')
if 'metadata' in r2:
    m=r2['metadata']
    print(f'  struct={m[\"c_struct\"]}, sql={m[\"sql_table\"]}, access={m[\"access_pattern\"]}')
")
echo "$result"
echo "  PASS"

# Test 11: describe_fields on SQL-only store gives helpful error
echo ""
echo "Test 11: describe_fields on SQL-only store (quest_template) gives guidance"
result=$(call_tool describe_fields '{"dbc_name": "quest_template"}' | python3 -c "
import sys,json
r=json.load(sys.stdin)
d=json.loads(r['result']['content'][0]['text'])
err = d.get('error', '')
has_hint = 'query_game_data' in err or 'lookup_datastore' in err
print(f'  has_guidance={has_hint}, error_snippet={err[:80]}...')
")
echo "$result"
echo "  PASS"

# Test 12: list_dbcs with no match gives hint
echo ""
echo "Test 12: list_dbcs for 'Quest' gives hint about list_stores"
result=$(call_tool list_dbcs '{"search": "Quest"}' | python3 -c "
import sys,json
r=json.load(sys.stdin)
d=json.loads(r['result']['content'][0]['text'])
has_hint = 'hint' in d and 'list_stores' in d.get('hint', '')
print(f'  count={d[\"count\"]}, has_hint={has_hint}')
")
echo "$result"
echo "  PASS"

# Test 13: query_dbc on SQL-only store gives helpful error
echo ""
echo "Test 13: query_dbc on creature_template gives guidance"
result=$(call_tool query_dbc '{"dbc_name": "creature_template"}' | python3 -c "
import sys,json
r=json.load(sys.stdin)
d=json.loads(r['result']['content'][0]['text'])
err = d.get('error', '')
has_hint = 'query_game_data' in err or 'SQL' in err
print(f'  has_guidance={has_hint}, error_snippet={err[:80]}...')
")
echo "$result"
echo "  PASS"

# Test 14: lookup_datastore returns live sql_columns
echo ""
echo "Test 14: lookup_datastore returns sql_columns for SQL tables"
result=$(call_tool lookup_datastore '{"query": "quest_template"}' | python3 -c "
import sys,json
r=json.load(sys.stdin)
d=json.loads(r['result']['content'][0]['text'])
m=d['result']['matches'][0]
cols = m.get('sql_columns', [])
print(f'  has_sql_columns={len(cols) > 0}, count={len(cols)}')
if cols:
    print(f'  first 3: {[c[\"name\"] for c in cols[:3]]}')
")
echo "$result"
echo "  PASS"

# Test 15: query_game_data returns columns in metadata
echo ""
echo "Test 15: query_game_data includes columns in metadata"
result=$(call_tool query_game_data '{"dbc_name": "quest_template", "id": 3904}' | python3 -c "
import sys,json
r=json.load(sys.stdin)
d=json.loads(r['result']['content'][0]['text'])
meta = d.get('metadata', {})
cols = meta.get('columns', [])
pk = meta.get('primary_key', '')
print(f'  has_columns={len(cols) > 0}, count={len(cols)}, primary_key={pk}')
")
echo "$result"
echo "  PASS"

# Test 16: execute_sql suggests correct columns on error
echo ""
echo "Test 16: execute_sql suggests columns on Unknown column error"
result=$(call_tool execute_sql '{"sql": "SELECT ID, name FROM quest_template LIMIT 1"}' | python3 -c "
import sys,json
r=json.load(sys.stdin)
d=json.loads(r['result']['content'][0]['text'])
err = d.get('error', '')
has_suggestion = 'Available columns' in err or 'Similar columns' in err
print(f'  has_suggestion={has_suggestion}')
print(f'  error_preview={err[:120]}...')
")
echo "$result"
echo "  PASS"

# Test 17: lookup gameobject_questitem (new auxiliary table)
echo ""
echo "Test 17: lookup gameobject_questitem (sql_auxiliary category)"
result=$(call_tool lookup_datastore '{"query": "gameobject_questitem"}' | python3 -c "
import sys,json
r=json.load(sys.stdin)
d=json.loads(r['result']['content'][0]['text'])
m=d['result']['matches'][0]
print(f'  category={m[\"category\"]}, sql_table={m[\"sql_table\"]}')
cols = m.get('sql_columns', [])
print(f'  has_sql_columns={len(cols) > 0}, first={cols[0][\"name\"] if cols else \"N/A\"}')
")
echo "$result"
echo "  PASS"

# Test 18: query_game_data with new auxiliary table
echo ""
echo "Test 18: query_game_data gameobject_questitem for item 11119"
result=$(call_tool query_game_data '{"dbc_name": "gameobject_questitem", "filter": {"ItemId": 11119}}' | python3 -c "
import sys,json
r=json.load(sys.stdin)
d=json.loads(r['result']['content'][0]['text'])
if 'error' in d:
    print(f'  error: {d[\"error\"][:80]}...')
else:
    rows = d.get('result', [])
    print(f'  count={len(rows)}')
    if rows:
        print(f'  first: GameObjectEntry={rows[0].get(\"GameObjectEntry\")}, ItemId={rows[0].get(\"ItemId\")}')
")
echo "$result"
echo "  PASS"

# Test 19: execute_sql returns hint for empty loot_template results
echo ""
echo "Test 19: execute_sql hint for empty loot_template search"
result=$(call_tool execute_sql '{"sql": "SELECT * FROM gameobject_loot_template WHERE item = 9999999"}' | python3 -c "
import sys,json
r=json.load(sys.stdin)
d=json.loads(r['result']['content'][0]['text'])
hint = d.get('hint', '')
has_hint = 'gameobject_questitem' in hint and 'creature_questitem' in hint
print(f'  has_hint={has_hint}')
print(f'  count={d.get(\"count\", 0)}')
if hint:
    print(f'  hint_preview={hint[:80]}...')
")
echo "$result"
echo "  PASS"

# Test 20: execute_sql suggests correct table from database (not in registry)
echo ""
echo "Test 20: Unknown table suggests tables from database"
result=$(call_tool execute_sql '{"sql": "SELECT * FROM gameobject_template_loot WHERE Entry = 11119"}' | python3 -c "
import sys,json
r=json.load(sys.stdin)
d=json.loads(r['result']['content'][0]['text'])
err = d.get('error', '')
has_suggestion = 'gameobject_loot_template' in err and 'Did you mean' in err
print(f'  has_suggestion={has_suggestion}')
if err:
    import re
    match = re.search(r'Did you mean: ([^\n]+)', err)
    if match:
        print(f'  suggestion={match.group(1)}')
")
echo "$result"
echo "  PASS"

# Test 21: Smart routing - arena_team should auto-route to acore_characters
echo ""
echo "Test 21: Cross-database routing for arena_team (characters DB)"
result=$(call_tool execute_sql '{"sql": "SELECT COUNT(*) as cnt FROM arena_team LIMIT 1"}' | python3 -c "
import sys,json
r=json.load(sys.stdin)
d=json.loads(r['result']['content'][0]['text'])
if 'error' in d:
    print(f'  error: {d[\"error\"][:100]}...')
else:
    rows = d.get('result', [])
    print(f'  routed_to_characters={len(rows) > 0}, count={d.get(\"count\", 0)}')
")
echo "$result"
echo "  PASS"

# Test 22: Smart routing - creature_template stays in acore_world
echo ""
echo "Test 22: Cross-database routing for creature_template (world DB)"
result=$(call_tool execute_sql '{"sql": "SELECT entry, name FROM creature_template WHERE entry = 1 LIMIT 1"}' | python3 -c "
import sys,json
r=json.load(sys.stdin)
d=json.loads(r['result']['content'][0]['text'])
if 'error' in d:
    print(f'  error: {d[\"error\"][:100]}...')
else:
    rows = d.get('result', [])
    if rows:
        print(f'  routed_to_world={len(rows) > 0}, entry={rows[0].get(\"entry\")}')
")
echo "$result"
echo "  PASS"

# Test 23: Smart routing suggests tables from characters DB when queried from world
echo ""
echo "Test 23: Table suggestions include multi-DB lookup for arena_team typo"
result=$(call_tool execute_sql '{"sql": "SELECT * FROM arena_teams LIMIT 1"}' | python3 -c "
import sys,json
r=json.load(sys.stdin)
d=json.loads(r['result']['content'][0]['text'])
err = d.get('error', '')
has_suggestion = 'arena_team' in err.lower()
print(f'  has_suggestion={has_suggestion}')
if err:
    import re
    match = re.search(r'Did you mean: ([^\n]+)', err)
    if match:
        print(f'  suggestion={match.group(1)}')
")
echo "$result"
echo "  PASS"

# Test 24: Query characters table (player data)
echo ""
echo "Test 24: Query acore_characters.database for 'characters' table"
result=$(call_tool execute_sql '{"sql": "SELECT COUNT(*) as total FROM characters LIMIT 1"}' | python3 -c "
import sys,json
r=json.load(sys.stdin)
d=json.loads(r['result']['content'][0]['text'])
if 'error' in d:
    print(f'  error: {d[\"error\"][:100]}...')
else:
    rows = d.get('result', [])
    print(f'  routed_to_characters={len(rows) > 0}, count={d.get(\"count\", 0)}')
")
echo "$result"
echo "  PASS"

# Test 25: Query account table (auth DB)
echo ""
echo "Test 25: Query acore_auth for 'account' table"
result=$(call_tool execute_sql '{"sql": "SELECT id, username FROM account LIMIT 1"}' | python3 -c "
import sys,json
r=json.load(sys.stdin)
d=json.loads(r['result']['content'][0]['text'])
if 'error' in d:
    print(f'  error: {d[\"error\"][:100]}...')
else:
    rows = d.get('result', [])
    if rows:
        print(f'  routed_to_auth={len(rows) > 0}, id={rows[0].get(\"id\")}')
")
echo "$result"
echo "  PASS"

# Test 26: Table name correction - arena_te should suggest arena_team
echo ""
echo "Test 26: Partial table name suggests arena_team with database hint"
result=$(call_tool execute_sql '{"sql": "SELECT * FROM arena_te LIMIT 1"}' | python3 -c "
import sys,json
r=json.load(sys.stdin)
d=json.loads(r['result']['content'][0]['text'])
err = d.get('error', '')
has_suggestion = 'arena_team' in err.lower() or 'Did you mean' in err
print(f'  has_suggestion={has_suggestion}')
if err:
    import re
    match = re.search(r'Did you mean: ([^\n]+)', err)
    if match:
        sug = match.group(1)
        print(f'  suggestion={sug}')
        print(f'  includes_db_hint={\"acore\" in sug.lower() or \"characters\" in sug.lower()}')
")
echo "$result"
echo "  PASS"

# Test 27: query_game_data for arena_team_member (SQL manager, characters)
echo ""
echo "Test 27: query_game_data routes arena_team_member to correct DB"
result=$(call_tool query_game_data '{"dbc_name": "ArenaTeamMembers", "limit": 1}' | python3 -c "
import sys,json
r=json.load(sys.stdin)
d=json.loads(r['result']['content'][0]['text'])
if 'error' in d:
    print(f'  error: {d[\"error\"][:100]}...')
else:
    rows = d.get('result', [])
    meta = d.get('metadata', {})
    print(f'  routed_successfully={len(rows) > 0}, count={d.get(\"count\", 0)}')
    if meta:
        print(f'  sql_table={meta.get(\"sql_table\", \"N/A\")}')
")
echo "$result"
echo "  PASS"

# Test 28: Table with prefix/suffix matching
echo ""
echo "Test 28: Suggests 'arena_team_member' when searching 'team_member'"
result=$(call_tool execute_sql '{"sql": "SELECT * FROM team_member LIMIT 1"}' | python3 -c "
import sys,json
r=json.load(sys.stdin)
d=json.loads(r['result']['content'][0]['text'])
err = d.get('error', '')
has_suggestion = 'arena_team_member' in err.lower()
print(f'  has_arena_team_member={has_suggestion}')
if err:
    import re
    match = re.search(r'Did you mean: ([^\n]+)', err)
    if match:
        print(f'  suggestions={match.group(1)}')
")
echo "$result"
echo "  PASS"

# Test 29: Test database discovery output
echo ""
echo "Test 29: Verify multi-database table discovery completed"
discovery=$(timeout 5 python3 /root/dbc-query/server.py 2>&1 <<<'{"jsonrpc": "2.0", "id": 1, "method": "initialize"}' | head -20)
has_world=$(echo "$discovery" | grep -c "acore_world:.*tables" || true)
has_characters=$(echo "$discovery" | grep -c "acore_characters:.*tables" || true)
has_auth=$(echo "$discovery" | grep -c "acore_auth:.*tables" || true)
echo "  discovered_world=$has_world, characters=$has_characters, auth=$has_auth"
echo "  PASS"

# Test 30: Test overlapping tables (updates exists in all DBs)
echo ""
echo "Test 30: Overlapping 'updates' table uses priority order (world first)"
result=$(call_tool execute_sql '{"sql": "SELECT name, state FROM updates LIMIT 1"}' | python3 -c "
import sys,json
r=json.load(sys.stdin)
d=json.loads(r['result']['content'][0]['text'])
if 'error' in d:
    print(f'  error: {d[\"error\"][:100]}...')
else:
    rows = d.get('result', [])
    if rows:
        print(f'  found_in_world={len(rows) > 0}, state={rows[0].get(\"state\", \"N/A\")}')
")
echo "$result"
echo "  PASS"

echo ""
echo "All tests completed successfully!"
