#!/bin/bash
# Integration test for dbc_query MCP server

echo "Testing dbc_query MCP server integration..."
echo ""

# Test 1: List tools
echo "Test 1: List available tools"
echo '{"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}' | python3 /root/dbc-query/server.py | jq -r '.result.tools[].name'
echo ""

# Test 2: Query spell 2567
echo "Test 2: Query spell 2567 in SkillLineAbility"
echo '{"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "query_dbc", "arguments": {"dbc_name": "SkillLineAbility", "filter": {"2": 2567}}}}' | python3 /root/dbc-query/server.py | jq -r '.result.content[0].text' | jq -r '.result[0] | "ID=\(.["0"]), SkillLine=\(.["1"]), Spell=\(.["2"]), RaceMask=\(.["3"]), ClassMask=\(.["4"])"'
echo ""

# Test 3: Get Spell.dbc info
echo "Test 3: Get Spell.dbc information"
echo '{"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "query_dbc", "arguments": {"dbc_name": "Spell", "info": true}}}' | python3 /root/dbc-query/server.py | jq -r '.result.content[0].text' | jq -r '.result | "Records: \(.record_count), Fields: \(.field_count)"'
echo ""

# Test 4: List Spell-related DBCs
echo "Test 4: List Spell-related DBCs"
echo '{"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "list_dbcs", "arguments": {"search": "Spell"}}}' | python3 /root/dbc-query/server.py | jq -r '.result.content[0].text' | jq -r '.count as $count | "Found \($count) Spell-related DBCs"'
echo ""

echo "All tests completed successfully!"
