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
            "subclass_field_index": 2,
            # Updated class_map based on actual acore_world item_template data analysis
            "class_map": {
                0: "Generic/Misc - Food, water, non-stackable consumables",
                1: "Container - Bags, satchels, special containers",
                2: "Weapon - Axes, swords, maces, bows, guns, staves, daggers",
                3: "Gem Source - Raw gems like Malachite (for socketing)",
                4: "Armor/Jewelry/Headwear - Cloth through plate + rings + trinkets",
                5: "Quest Item (rare) - Very specific quest items (~4 total)",
                6: "Ammo/Projectile - Arrows, bullets for ranged weapons",
                7: "TradeSkill Material - Crafting components (organs, parts)",
                8: "Reagent/Misc - Rare single-use reagents",
                9: "Recipe/Blueprint - TradeSkill blueprints, tomes, spell books",
                10: "Currency - Arena marks, honor points, reputation tokens",
                11: "Range Container - Quivers, ammunition containers",
                12: "Quest Item - General quest items (flexible properties)",
                13: "Leatherwork Material - Leather pieces and templates",
                15: "Mail/Scale - Dragonkin mail armor and leather variants",
                16: "Plate/NPC Equip - Plate armor + NPC special equipment",
            },
            # Subclass mappings for class=1 (Consumable)
            "subclass_consumable_map": {
                0: "Generic Consumable",
                1: "Potion",
                2: "Elixir",
                3: "Flask",
                4: "Scroll",
                5: "Food",
                6: "Item Enhancement",
                7: "Bandage",
                8: "Other Consumable",
            },
            # Subclass mappings for class=2 (Container)
            "subclass_container_map": {
                0: "Bag/Pocket",
                1: "Soul Bag",
                2: "Herb Bag",
                3: "Enchanting Bag",
                4: "Engineering Bag",
                5: "Gem Bag",
                6: "Mining Bag",
                7: "Leatherworking Bag",
                8: "Inscription Bag",
            },
            # Subclass mappings for class=3 (Weapon)
            "subclass_weapon_map": {
                0: "1-Hand Axe",
                1: "2-Hand Axe",
                2: "Bow",
                3: "Gun",
                4: "1-Hand Mace",
                5: "2-Hand Mace",
                6: "Polearm",
                7: "1-Hand Sword",
                8: "2-Hand Sword",
                10: "Staff",
                11: "Exotic Weapon",
                12: "Exotic Off-Hand",
                13: "Fist Weapon",
                14: "Misc Weapon",
                15: "Dagger",
                16: "Thrown",
                17: "Spear",
                18: "Crossbow",
                19: "Wand",
                20: "Fishing Pole",
            },
            # Subclass mappings for class=4 (Armor)
            "subclass_armor_map": {
                0: "Misc Armor",
                1: "Cloth",
                2: "Leather",
                3: "Mail",
                4: "Plate",
                5: "Buckler",
                6: "Shield",
                7: "Libram",
                8: "Idol",
                9: "Totem",
                10: "Sigil",
            },
            # Subclass mappings for class=7 (Gem)
            "subclass_gem_map": {
                0: "Red Gem (Strength/Agility)",
                1: "Blue Gem (Intellect/Spirit)",
                2: "Yellow Gem (Agility/Crit)",
                3: "Purple Gem (Stamina/Spi)",
                4: "Green Gem (Sta/Str or Sta/Agi)",
                5: "Orange Gem (Sta/Str or Sta/Agi with Crit/Hit)",
                6: "Meta Gem",
                7: "Simple Stat Gem",
                8: "Prismatic Gem",
            },
        },
        "creature_template": {
            "type_field_index": 33,  # type field in creature_template (creatureType from SharedDefines.h)
            "typeflags_field_index": 24,  # creatureTypeFlags field
            "type_map": {
                1: "Beast - Can be skinned, tamed by hunters",
                2: "Dragonkin - Dragon-like creatures",
                3: "Demon - Chaotic magical beings",
                4: "Elemental - Primal force creature",
                5: "Giant - Large humanoid/mammal-type",
                6: "Undead - Reanimated corpse or similar",
                7: "Humanoid - Human, goblin, tauren, etc.",
                8: "Critter - Non-hostile small creatures (rabbits, birds)",
                9: "Mechanical - Constructs, golems, robots",
                10: "Not Specified - No creature type set",
                11: "Totem - Hunter/druid totems",
                12: "Non-Combat Pet - Companion pet",
                13: "Gas Cloud - Area effect cloud",
            },
            # CreatureTypeFlags from SharedDefines.h (bitmask)
            "typeflags_map": {
                0x00000001: "TAMEABLE - Can be tamed by hunters (must also be beast + have family)",
                0x00000002: "VISIBLE_TO_GHOSTS - Visible to dead players for gossip",
                0x00000004: 'BOSS_MOB - Shows "??" level, immune to knockback, raid boss marker',
                0x00000008: "DO_NOT_PLAY_WOUND_ANIM - No wound animation on parry",
                0x00000010: "NO_FACTION_TOOLTIP - Hides faction tooltip in unit frame",
                0x00000020: "MORE_AUDIBLE - Enhanced sound effects",
                0x00000040: "SPELL_ATTACKABLE - Can be targeted by spells",
                0x00000080: "INTERACT_WHILE_DEAD - Player can interact if creature is dead",
                0x00000100: "SKIN_WITH_HERBALISM - Herbalism gatherable",
                0x00000200: "SKIN_WITH_MINING - Mining node",
                0x00000400: "NO_DEATH_MESSAGE - Death won't appear in combat log",
                0x00000800: "ALLOW_MOUNTED_COMBAT - Can fight while mounted",
                0x00001000: "CAN_ASSIST - Can help players in combat",
                0x00002000: "NO_PET_BAR - No pet action bar shown",
                0x00004000: "MASK_UID - Non-unique in combat log",
                0x00008000: "SKIN_WITH_ENGINEERING - Salvageable by engineers",
                0x00010000: "TAMEABLE_EXOTIC - Exotic hunter pet (requires Exotic Beasts talent)",
                0x00020000: "USE_MODEL_COLLISION_SIZE - Uses model bounds for collision",
                0x00040000: "ALLOW_INTERACTION_WHILE_IN_COMBAT - Can interact during combat",
                0x00080000: "COLLIDE_WITH_MISSILES - Projectiles collide with this creature",
                0x00100000: "NO_NAME_PLATE - No nametag shown above creature",
                0x00200000: "DO_NOT_PLAY_MOUNTED_ANIMATIONS - No mount animations",
                0x00400000: "LINK_ALL - Always link in combat log (party/raid)",
                0x00800000: "INTERACT_ONLY_WITH_CREATOR - Only summoner can interact",
                0x01000000: "DO_NOT_PLAY_UNIT_EVENT_SOUNDS - No death scream sounds",
                0x02000000: "HAS_NO_SHADOW_BLOB - No shadow under unit model",
                0x04000000: "TREAT_AS_RAID_UNIT - Targetable by party/raid-targeting spells",
                0x08000000: "FORCE_GOSSIP - Always display gossip menu (single option)",
                0x10000000: "DO_NOT_SHEATHE - Weapons stay unsheathed",
                0x20000000: "DO_NOT_TARGET_ON_INTERACTION - Right-click doesn't target",
                0x40000000: "DO_NOT_RENDER_OBJECT_NAME - Hide name in world frame",
                0x80000000: "QUEST_BOSS - Marked as quest objective boss (unverified)",
            },
            "key_fields": {
                "0": "entry - Creature ID (matches creature_loot_template.entry)",
                "6": "name - Creature name",
                "33": "type - Creature type from SharedDefines.h enum",
                "24": "creatureTypeFlags - Special behavior flags (bitmask)",
                "95": "lootId - References creature_loot_template.entry",
            },
        },
    }

    # Spell system enums from SharedDefines.h
    SPELL_EFFECTS = {
        0: "SPELL_EFFECT_NONE",
        1: "INSTAKILL",
        2: "SCHOOL_DAMAGE (Holy/Nature/Fire/Frost/Shadow/Physical)",
        3: "DUMMY - Used for auras and spell targeting",
        4: "PORTAL_TELEPORT - Teleport to portal (requires SPELL_EFFECT_PORTAL)",
        5: "TELEPORT_UNITS - Teleport target location",
        6: "APPLY_AURA - Apply temporary or permanent aura effect",
        7: "ENVIRONMENTAL_DAMAGE - Fall, drown, suffocate damage",
        8: "POWER_DRAIN - Drain mana/energy/rune",
        9: "HEALTH_LEECH - Lifesteal from damage",
        10: "HEAL - Restore health",
        11: "BIND - Set homebound location (grey out hearthstone)",
        12: "PORTAL - Create portal item/teleportation destination",
        13 - 15: "RITUAL_* - Portal ritual spells",
        16: "QUEST_COMPLETE - Marks quest as complete",
        17: "WEAPON_DAMAGE_NOSCHOOL - Physical damage without school",
        18: "RESURRECT - Revive dead units (resurrection)",
        19: "ADD_EXTRA_ATTACKS - Extra attack on next swing",
        20 - 23: "DODGE/EVADE/PARRY/BLOCK - Combat avoidance/dodge animations",
        24: "CREATE_ITEM - Create item in target's inventory",
        25: "WEAPON - Weapon damage (with school)",
        26: "DEFENSE - Defense skill up",
        27: "PERSISTENT_AREA_AURA - Aura affecting area persistently",
        28: "SUMMON - Summon creature at location",
        29: "LEAP - Jump to target (like Charge)",
        30: "ENERGIZE - Restore power (mana/energy/rage)",
        31: "WEAPON_PERCENT_DAMAGE - % of weapon damage",
        32: "TRIGGER_MISSILE - Auto-fire missile spell",
        33: "OPEN_LOCK - Open locked containers",
        34: "SUMMON_CHANGE_ITEM - Transform item on summon",
        35: "APPLY_AREA_AURA_PARTY - Area aura for party members",
        36: "LEARN_SPELL - Teach target a spell",
        37: "SPELL_DEFENSE - Spell damage/absorb reduction",
        38: "DISPEL - Remove enchantments from target",
        39: "LANGUAGE - Grant language understanding",
        40: "DUAL_WIELD - Allow two-weapon fighting",
        41 - 42: "JUMP/JUMP_DEST - Jump mechanics (separate effects)",
        43: "TELEPORT_UNITS_FACE_CASTER - Teleport and face caster",
        44: "SKILL_STEP - Increase skill point gains",
        45: "ADD_HONOR - Grant honor points (pvp only)",
        46: "SPAWN - Spawn object/gameobject",
        47: "TRADE_SKILL - Trigger tradeskill proc",
        48: "STEALTH - Enter stealth mode",
        49: "DETECT - Detect invisible/stealthed units",
        50: "TRANS_DOOR - Transform into door/flyable form",
        51: "FORCE_CRITICAL_HIT - Force critical hit on next attack",
        52: "GUARANTEE_HIT - Next attack guaranteed to hit",
        53: "ENCHANT_ITEM - Permanently enchant held item",
        54: "ENCHANT_ITEM_TEMPORARY - Temporarily enchant held item",
        55: "TAMECREATURE - Tame beast as hunter pet",
        56: "SUMMON_PET - Summon hunter pet to fight",
        57: "LEARN_PET_SPELL - Teach spell to hunter pet",
        58: "WEAPON_DAMAGE - Weapon damage (school-based)",
        59: "CREATE_RANDOM_ITEM - Create random item from loot table",
        60: "PROFICIENCY - Grant weapon proficiencies",
        61: "SEND_EVENT - Trigger internal game event",
        62: "POWER_BURN - Burn mana/energy over time",
        63: "THREAT - Gain/lose threat on target",
        64: "TRIGGER_SPELL - Cast another spell automatically",
        65: "APPLY_AREA_AURA_RAID - Area aura for raid members",
        66: "CREATE_MANA_GEM - Create mana gem item",
        67: "HEAL_MAX_HEALTH - Heal based on max health %",
        68: "INTERRUPT_CAST - Interrupt target's current cast",
        69: "DISTRACT - Distract mechanical creatures",
        70: "PULL - Pull target closer (mage Pull)",
        71: "PICKPOCKET - Pickpocket humanoid creatures",
        72: "ADD_FARSIGHT - Allow view through other unit's eyes",
        73: "UNTRAIN_TALENTS - Reset talent points",
        74: "APPLY_GLYPH - Apply glyph to spellbook",
        75: "HEAL_MECHANICAL - Heal mechanical units",
        76: "SUMMON_OBJECT_WILD - Summon wild creature/object",
        77: "SCRIPT_EFFECT - Trigger scripted spell behavior",
        78: "ATTACK - Force target to attack caster",
        79: "SANCTUARY - Sanctuary effect (dmg taken -> health)",
        80: "ADD_COMBO_POINTS - Add combo points to rogue",
        81: "CREATE_HOUSE - Create player housing",
        82: "BIND_SIGHT - Bind sight (for flying mounts in certain areas)",
        83: "DUEL - Force duel between two players",
        84: "STUCK - Teleport stuck players out of geometry",
        85: "SUMMON_PLAYER - Summon another player (GM only)",
        86: "ACTIVATE_OBJECT - Activate nearby gameobject",
        87 - 92: "GAMEOBJECT_*, ENCHANT_HELD_ITEM - GO damage/repair/enchant effects",
        93 - 100: "FORCE_DESELECT, SELF_RESURRECT through DISENCHANT - Utility effects",
    }

    SPELL_SCHOOLS = {
        0: "HOLY (Holy spells)",
        1: "NATURE (Nature magic)",
        2: "FIRE (Fire magic)",
        3: "FROST (Ice magic)",
        4: "SHADOW (Shadow/Death magic)",
        5: "PHYSICAL (Melee/ranged attacks)",
    }

    SPELL_ATTR_MASKS = {
        "ATTR1": {
            0x00000001: "CASTER_PLAYABLE - Only castable by players",
            0x00000002: "UNIT_TARGET - Target is unit/player",
            0x00000004: "NO_KNEELING - Can be cast while running",
            0x00000010: "NOT_WHILE_SHAPESHIFTED - Cannot cast while shapeshifted",
        },
        "ATTR2": {
            0x00000010: "NO_PVP_CREDIT - No honor points when killing with this spell",
            0x00000080: "TRIGGERABLE - Can proc from other sources",
        },
    }

    # Achievement-related enums from DBCEnums.h
    ACHIEVEMENT_CRITERIA_TYPES = {
        0: "KILL_CREATURE - Kill x creatures of entry Y",
        1: "WIN_BG - Win battleground matches",
        5: "REACH_LEVEL - Reach level X",
        7: "REACH_SKILL_LEVEL - Reach skill level X in profession",
        8: "COMPLETE_ACHIEVEMENT - Complete achievement ID X",
        9: "COMPLETE_QUEST_COUNT - Complete x quests total",
        10: "COMPLETE_DAILY_QUEST_DAILY - Complete daily quests in a row",
        13: "DAMAGE_DONE - Deal X damage to enemies",
        16: "DEATH_AT_MAP - Die at specific map location",
        17: "DEATH - Die x times",
        18: "DEATH_IN_DUNGEON - Die in dungeon instance",
        19: "COMPLETE_RAID - Kill all bosses in raid instance",
        27: "COMPLETE_QUEST - Complete specific quest ID",
        29: "CAST_SPELL - Cast spell X, Y times",
        30: "BG_OBJECTIVE_CAPTURE - Capture objective in battleground",
        31: "HONORABLE_KILL_AT_AREA - Honor kill at zone",
        32: "WIN_ARENA - Win arena match",
        33: "PLAY_ARENA - Play arena match",
        34: "LEARN_SPELL - Learn spell ID X",
        35: "HONORABLE_KILL - Earn honorable kill",
        36: "OWN_ITEM - Own item in inventory/bank",
        41: "USE_ITEM - Use item ID X",
        42: "LOOT_ITEM - Loot item ID X",
        43: "EXPLORE_AREA - Visit location (MapID, x, z coordinates)",
        46: "GAIN_REPUTATION - Gain reputation with faction",
        47: "GAIN_EXALTED_REPUTATION - Reach Exalted with faction",
        52: "HK_CLASS - Honor kill of class X",
        53: "HK_RACE - Honor kill of race X",
        55: "HEALING_DONE - Heal X amount total",
        67: "LOOT_MONEY - Loot X gold",
        72: "FISH_IN_GAMEOBJECT - Fish at gameobject",
        74: "ON_LOGIN - Daily login achievement",
        75: "LEARN_SKILLLINE_SPELLS - Learn x spells in skill line",
        76: "WIN_DUEL - Win duel against player",
        77: "LOSE_DUEL - Lose duel to player",
        78: "KILL_CREATURE_TYPE - Kill x creatures of type (beast/demon/etc)",
        80: "GOLD_EARNED_BY_AUCTIONS - Earn X gold from auctions",
        90: "LOOT_EPIC_ITEM - Loot epic item (itemlevel >= 200)",
        105: "TOTAL_HEALING_RECEIVED - Receive X healing total",
    }

    # Reputation ranks from SharedDefines.h
    REPUTATION_RANKS = {
        0: "Hated (-2100 to -1500 rep)",
        1: "Hostile (-1499 to -900 rep)",
        2: "Unfriendly (-899 to -300 rep)",
        3: "Neutral (-299 to 0 rep, starting state)",
        4: "Friendly (1 to 3000 rep)",
        5: "Honored (3001 to 6000 rep)",
        6: "Revered (6001 to 9000 rep)",
        7: "Exalted (9001+ rep, maximum)",
    }

    # Difficulty settings from DBCEnums.h
    DIFFICULTY_SETTINGS = {
        0: "NORMAL - Regular difficulty (dungeon/world/raid 10-man)",
        1: "HEROIC - Heroic dungeon or 25-man raid normal",
        2: "EPIC - Epic+ difficulty (legacy) / 10-man Heroic",
        3: "25-HEROIC - 25-man Heroic difficulty",
    }

    # SQL column name to DBC field index mapping for item_template
    # Note: SQL table columns don't always match DBC field positions
    ITEM_TEMPLATE_COL_TO_IDX = {
        # Core fields (match DBC indices)
        "entry": "0",
        "class": "1",
        "Class": "1",
        "subclass": "2",
        "Subclass": "2",
        "SoundOverrideSubclass": "3",
        "name": "4",
        "Name": "4",
        # DisplayID in SQL table is column 5
        "displayid": "5",
        "DisplayID": "5",
        # Quality (itemQuality) - index 6 in DBC structure
        "Quality": "6",
        # InventoryType - index 7 in DBC structure
        "InventoryType": "7",
        # AllowableClass bitmask - column 13 in SQL table, virtual index 8
        "AllowableClass": "8",
        # Bonding (itemBonding) - column 100 in SQL, virtual index 9
        "Bonding": "9",
        "bonding": "9",
        # SheathType - column 108 in SQL table, used for weapons
        "sheath": "24",
        "SheathType": "24",
        # Additional useful columns from item_template
        "Flags": "10",
        "FlagsExtra": "11",
        "BuyPrice": "13",
        "SellPrice": "15",
        "AllowableRace": "14",
        "ItemLevel": "16",
        "RequiredLevel": "17",
        "maxcount": "24",
        "stackable": "25",
        "ContainerSlots": "26",
        "description": "101",
        "Material": "107",
        "RandomProperty": "109",
        "RequiredDisenchantSkill": "116",
    }

    # Item qualities from SharedDefines.h
    ITEM_QUALITIES = {
        0: "GRAY - Poor quality, no special effects",
        1: "WHITE - Common quality, standard items",
        2: "GREEN - Uncommon quality, bonus stats",
        3: "BLUE - Rare quality, significant bonuses",
        4: "PURPLE - Epic quality, powerful effects",
        5: "ORANGE - Legendary quality (unique, quest/boss drops)",
        6: "ARATE - Artifact quality (high-level expansion items)",
    }

    # Sheath types from SharedDefines.h (SheathTypes enum)
    SHEATH_TYPES = {
        0: "NONE - No sheathing (weapons stay equipped)",
        1: "MAIN_HAND - Main hand weapons",
        2: "OFF_HAND - Off-hand items (shields, books, off-hand weapons)",
        3: "LARGEWEAPON_LEFT - Two-handed weapon in left hand slot",
        4: "LARGEWEAPON_RIGHT - Two-handed weapon / shield variant",
        5: "HIPWEAPON_LEFT - Hip weapon in left slot (ranged + sidearm)",
        6: "HIPWEAPON_RIGHT - Hip weapon in right slot (ranged + sidearm)",
        7: "SHIELD - Shield specific sheathing",
    }

    # Player races from SharedDefines.h
    PLAYER_RACES = {
        1: "HUMAN (Alliance)",
        2: "ORC (Horde)",
        3: "DWARF (Alliance)",
        4: "NIGHTELF (Alliance)",
        5: "UNDEAD_PLAYER (Horde)",
        6: "TAUREN (Horde)",
        7: "GNOME (Alliance)",
        8: "TROLL (Horde)",
        10: "BLOODELF (Horde)",
        11: "DRAENEI (Alliance)",
    }

    # Player classes from SharedDefines.h
    PLAYER_CLASSES = {
        1: "WARRIOR",
        2: "PALADIN",
        3: "HUNTER",
        4: "ROGUE",
        5: "PRIEST",
        6: "DEATH_KNIGHT",
        7: "SHAMAN",
        8: "MAGE",
        9: "WARLOCK",
        11: "DRUID",
    }

    # Stats enum from SharedDefines.h (item stats, character attributes)
    STAT_TYPES = {
        0: "HEALTH - Hit points",
        1: "MANA - Magic resource",
        2: "STRENGTH - Melee damage, armor",
        3: "AGILITY - Dodge, attack power (ranged/off-hand)",
        4: "STAMINA - Health points",
        5: "INTELLECT - Mana, spell crit",
        6: "SPIRIT - Mana regeneration",
    }

    # Power types from SharedDefines.h
    POWER_TYPES = {
        0: "HEALTH",
        1: "MANA",
        2: "ENERGY (Rogue resource)",
        3: "HAPPINESS (Pet bar)",
        4: "RUNE_POWER (Death Knight)",
        5: "FOCUS (Hunter)",
        6: "RUNES (Death Knight rune pool)",
        7: "RAGING_BLOOD",
    }

    # Stealth types from SharedDefines.h
    STEALTH_TYPES = {
        0: "STANDARD_STEALTH - Rogue hunter stealth",
        1: "SABOTEUR_STEALTH - PvP stealth detection",
        2: "SNEAKY_STEALTH - Sneak mode (dwarven form)",
        3: "DRUID_CAT_STEALTH - Cat form stealth",
    }

    # Invisibility types from SharedDefines.h
    INVISIBILITY_TYPES = {
        0: "INVISIBLE_TO_EVERYONE - Cannot be seen at all",
        1: "INVISIBLE_WHEN_STANDING_STILL - Detection on movement",
        2: "INVISIBLE_WHEN_NOT_IN_COMBAT - Combat reveals invisibility",
        3: "INVISIBLE_TO_ENEMIES_ONLY - Allies can see you",
        4: "SPECIAL_CASE - Custom invisibility logic",
    }

    # Dispel types from SharedDefines.h
    DISPEL_TYPES = {
        0: "NO_DISPEL - Cannot be dispelled",
        1: "MAGIC - Magic spells (Mage, Priest)",
        2: "CURSE - Curses (Warlock Remove Curse)",
        3: "DISEASE - Diseases (Priest Cleanse)",
        4: "STEALTH - Stealth removal",
        5: "SLEEP - Wake effects (Shackle Undead, etc)",
        6: "POISON - Poisons (Druid Detox)",
        7: "ALL_ENEMY - All negative friendly auras",
    }

    # Mechanics enum subset (resistances/immunities) from SharedDefines.h
    MECHANICS = {
        0x00000001: "STEALTH - Stealth resistance",
        0x00000002: "SNEAK - Sneak form immunity",
        0x00000004: "INVISIBILITY - Invisibility resistance",
        0x00000020: "DISARM - Disarm effect immunity",
        0x00000040: "STUN - Stun resistance/immunity",
        0x00000080: "SLEEP - Sleep/put to sleep immunity",
        0x00000100: "SNARE - Speed reduction/slow immunity",
        0x00000200: "ROOT - Root effect immunity",
        0x00000400: "CHARM - Charm control immunity",
        0x00000800: "DISORIENT - Disorient immunity",
        0x00001000: "FEAR - Fear effect immunity",
        0x00002000: "SILENCE - Silence casting immunity",
        0x00004000: "ROOT_ALT - Alternative root effect",
        0x00008000: "BANISH - Banish effect immunity",
        0x00010000: "SHIELD - Shield/protective aura",
        0x00020000: "SKULL - Taunt mechanic",
        0x00040000: "DISEASE - Disease resistance/immunity",
        0x00080000: "GHOUL - Ghoulish control immunity",
        0x00100000: "STUN_ALT - Alternative stun effect",
        0x00200000: "SPELL_DISRUPT - Spell interrupt immunity",
        0x00400000: "CONFUSED - Confusion/mind control immunity",
        0x00800000: "FREEZE - Freeze/cold effect immunity",
        0x01000000: "PACIFY - Pacify/silence immunity",
        0x02000000: "KNOCKOUT - Knockout/knockback immunity",
        0x40000000: "SKINNABLE - Can be skinned by player",
        0x80000000: "PET_TAMING - Pet taming mechanic",
    }

    # Expansions enum
    EXPANSIONS = {
        0: "CLASSIC - World of Warcraft Classic (v1.12)",
        1: "THE_BURNING_CRUSADE - TBC expansion (v2.4)",
        2: "WRATH_OF_THE_LICH_KING - WotLK expansion (v3.3.5a)",
    }

    # Item bond types (binding mechanics)
    ITEM_BOND_TYPES = {
        0: "NO_BIND - Can be traded/sold freely",
        1: "BIND_WHEN_PICKED_UP - Instantly binds when looted/bought",
        2: "BIND_WHEN_EQUIPPED - Binds when equipped (can be traded before)",
        3: "BIND_WHEN_USED - Binds when used",
        4: "BIND_QUEST_ITEM - Quest items cannot be traded",
    }

    # Language enum subset for item texts
    LANGUAGES = {
        0: "COMMON (Alliance/Horde)",
        1: "THALASSIAN (Naga, Netherspeak)",
        2: "DWARVEN",
        3: "DEAD_TONGUE - Undercommon/Undead",
        4: "DEMONTIC",
        5: "DRACOAN",
        6: "KALIMPTIC (Troll)",
        7: "GNOBLISH",
        8: "ORCISH",
        9: "DARNASSI (Night Elf)",
        10: "TAURAHE (Tauren)",
        11: "QUIRKISH (Murloc)",
        12: "TONGUE_OF_THE_ELEMENTS - Elemental language",
        13: "GUTTERSPEAK (Orcish/Draconic hybrid)",
    }

    # Spell custom errors for cast failure reasons
    SPELL_CAST_RESULTS = {
        0: "SUCCESS - Cast succeeded",
        1: "UNKNOWN_SPELL - Spell doesn't exist or not learned",
        3: "LEVEL_TOO_HIGH - Caster level too high to use this spell",
        4: "BAD_TARGETS - Invalid target",
        5: "NO_TARGETS - No valid targets found",
        7: "OUT_OF_RANGE - Target is out of range",
        8: "NO_AMMO - Missing required ammunition",
        9: "TOO_FAR_AWAY - Caster too far from target",
        11: "CANT_MOVE_THERE - Cannot move to that location",
        14: "CASTER_BUSY - Caster is already casting/attacking",
        15: "NO_POWER - Insufficient mana/energy/rage/focus",
        16: "COOLDOWN - Spell is on cooldown",
        20: "REMOVED_FROM_COMBAT - Interrupted by entering combat",
        24: "CHANNELING - Currently channeling another spell",
    }

    # Team enums for faction alignment
    TEAM_ENUMS = {
        0: "ALLIANCE",
        1: "HORDE",
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

    def _extract_item_quality_and_details(self, result: Dict[str, Any]) -> List[str]:
        """Extract item quality and other relevant details."""
        # Normalize data first to handle SQL columns
        result = self._normalize_result_for_item(result)

        hints = []

        # Field 6 is itemQuality in DBC structure (0-6)
        if "6" in result:
            try:
                quality = int(result["6"])
                quality_name = self.ITEM_QUALITIES.get(
                    quality, f"Unknown Quality ({quality})"
                )
                hints.append(f"Quality: {quality_name}")
            except (ValueError, TypeError):
                pass

        # Field 1 is class, field 2 is subclass - already handled by _extract_item_subclass_hint
        # Field 9 is Bonding
        if "9" in result:
            try:
                bonding = int(result["9"])
                bond_name = self.ITEM_BOND_TYPES.get(
                    bonding, f"Unknown Bond ({bonding})"
                )
                hints.append(f"Binding: {bond_name}")
            except (ValueError, TypeError):
                pass

        # Field 7 is AllowableClass (class mask)
        if "7" in result:
            try:
                class_mask = int(result["7"])
                if class_mask != 0:
                    allowed_classes = []
                    for class_id, class_name in self.PLAYER_CLASSES.items():
                        if class_mask & (1 << (class_id - 1)):
                            allowed_classes.append(class_name.split()[0])
                    if allowed_classes:
                        hints.append(f"Allowed Classes: {', '.join(allowed_classes)}")
            except (ValueError, TypeError):
                pass

        # Field 24 is SheathType for weapons (from 'sheath' SQL column)
        if "24" in result:
            try:
                sheath = int(result["24"])
                if sheath > 0:  # Only show if weapon has sheath type
                    sheath_name = self.SHEATH_TYPES.get(
                        sheath, f"Unknown Sheath ({sheath})"
                    )
                    hints.append(f"Sheath Type: {sheath_name}")
            except (ValueError, TypeError):
                pass

        return hints

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

    def _normalize_result_for_item(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize item_template data to handle both DBC indices and SQL column names."""
        normalized = dict(result)  # Copy original

        # If already has numeric keys (DBC style), return as-is
        if any(k.isdigit() for k in result.keys()):
            return normalized

        # Otherwise, convert SQL column names to DBC indices
        for col_name, idx in self.ITEM_TEMPLATE_COL_TO_IDX.items():
            if col_name in result and idx not in normalized:
                normalized[idx] = result[col_name]

        return normalized

    def _extract_item_class_hint(self, result: Dict[str, Any]) -> Optional[str]:
        """Generate hint for Item based on class field."""
        # Normalize data first to handle SQL columns
        result = self._normalize_result_for_item(result)

        item_info = self.TYPE_HINTS.get("item_template", {})
        class_index = str(item_info.get("class_field_index", 1))

        if class_index not in result:
            return None

        try:
            item_class = int(result[class_index])
            return f"Item Class: {item_info.get('class_map', {}).get(item_class, f'Unknown ({item_class})')}"
        except (ValueError, TypeError):
            return None

    def _extract_item_subclass_hint(self, result: Dict[str, Any]) -> Optional[str]:
        """Generate hint for Item based on class and subclass fields."""
        # Normalize data first to handle SQL columns
        result = self._normalize_result_for_item(result)

        item_info = self.TYPE_HINTS.get("item_template", {})
        class_index = str(item_info.get("class_field_index", 1))
        subclass_index = str(item_info.get("subclass_field_index", 2))

        if class_index not in result:
            return None

        try:
            item_class = int(result[class_index])

            # Check if there's a subclass map for this class (only 1, 2, 3, 4, 7 have detailed subclasses)
            if item_class not in [1, 2, 3, 4, 7]:
                return None

            # Map class to proper subclass dict name
            subclass_dict_map = {
                1: "subclass_consumable_map",
                2: "subclass_container_map",
                3: "subclass_weapon_map",
                4: "subclass_armor_map",
                7: "subclass_gem_map",
            }
            subclass_map_name = subclass_dict_map.get(
                item_class, f"subclass_{item_class}_map"
            )
            subclass_map = item_info.get(subclass_map_name, {})

            if subclass_index not in result:
                class_name = item_info.get("class_map", {}).get(
                    item_class, f"Unknown Class ({item_class})"
                )
                return f"{class_name}"

            item_subclass = int(result[subclass_index])
            class_name = item_info.get("class_map", {}).get(
                item_class, f"Unknown Class ({item_class})"
            )
            subclass_name = subclass_map.get(
                item_subclass, f"Unknown Subclass ({item_subclass})"
            )

            return f"{class_name}: {subclass_name}"

        except (ValueError, TypeError):
            return None

    def _extract_creature_typeflags(self, result: Dict[str, Any]) -> List[str]:
        """Parse creatureTypeFlags bitmask and return active flags."""
        creature_info = self.TYPE_HINTS.get("creature_template", {})
        typeflags_index = str(creature_info.get("typeflags_field_index", 24))

        if typeflags_index not in result:
            return []

        try:
            flags_value = int(result[typeflags_index])
            if flags_value == 0:
                return []

            typeflags_map = creature_info.get("typeflags_map", {})
            active_flags = []

            # Check each flag bit
            for flag_bit, flag_name in sorted(typeflags_map.items()):
                if flags_value & flag_bit:
                    active_flags.append(flag_name.split(" - ")[0])

            return active_flags if active_flags else []

        except (ValueError, TypeError):
            return []

    def _extract_spell_effect_hint(
        self, result: Dict[str, Any], effect_index: int = 0
    ) -> Optional[str]:
        """Generate hint for Spell effect based on EffectId field."""
        # Effects are stored at indices that depend on the DBC structure
        # For spell_dbc overlay: fields vary, but we can try common patterns
        effect_names = self.SPELL_EFFECTS

        # Try to find effect type in result (could be different fields based on source)
        for idx_str in [
            str(effect_index),
            str(effect_index * 3 + 102),
            f"Effect{effect_index}",
        ]:
            if idx_str in result and result[idx_str]:
                try:
                    effect_type = int(result[idx_str])
                    return effect_names.get(
                        effect_type, f"Unknown Effect ({effect_type})"
                    )
                except (ValueError, TypeError):
                    pass

        return None

    def _extract_quest_key_fields(self, result: Dict[str, Any]) -> List[str]:
        """Extract key field hints for Quest data."""
        quest_info = self.TYPE_HINTS.get("quest_template", {})
        hints = []

        for idx_str, description in quest_info.get("key_fields", {}).items():
            if idx_str in result and result[idx_str]:
                hints.append(f"Field {idx_str}: {description} = '{result[idx_str]}'")

        return hints

    def _extract_creature_type_hint(
        self, result: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Generate hints for Creature data based on creatureType field."""
        creature_info = self.TYPE_HINTS.get("creature_template", {})
        type_index = str(creature_info.get("type_field_index", 23))

        if type_index not in result:
            return None

        try:
            creature_type = int(result[type_index])
            type_name = creature_info.get("type_map", {}).get(
                creature_type, f"Unknown Type ({creature_type})"
            )

            hints = {
                "table": "creature_template",
                "context": [f"Creature Type: {type_name}"],
                "related_tables": [],
                "notes": [],
            }

            # Check for loot template reference
            loot_id = result.get("95")  # lootId field
            if loot_id and str(loot_id).strip() != "0" and str(loot_id).isdigit():
                hints["related_tables"].append(
                    f"creature_loot_template.entry={loot_id} (loot)"
                )

            # Check for name field (index 6 in creature_template)
            if "6" in result and result["6"] and str(result["6"]) not in ("", "NULL"):
                hints["notes"].append(f"Name: {result['6']}")

            # Parse creatureTypeFlags bitmask
            typeflags = self._extract_creature_typeflags(result)
            if typeflags:
                flags_str = ", ".join(typeflags[:5])
                if len(typeflags) > 5:
                    flags_str += "..."
                hints["notes"].append(f"Type Flags: {flags_str}")

            return hints
        except (ValueError, TypeError):
            return None

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
            result: The query result data (dict of field_index -> value, or list)

        Returns:
            Dictionary with hints or None if no relevant hints found
        """
        # Handle both single record (dict) and multiple records (list)
        if isinstance(result, list):
            if len(result) == 0:
                return None
            result = result[0]  # Use first record for hints

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

            # Extract item quality and details
            item_details = self._extract_item_quality_and_details(result)
            for detail in item_details:
                hints["notes"].append(detail)

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

        # Creature-specific hints
        if table_name == "creature_template" or table_name in {
            "Creature",
            "creature_dbc",
        }:
            creature_hints = self._extract_creature_type_hint(result)
            if creature_hints:
                return creature_hints

        # Lock-specific hints
        if "lock" in table_name.lower() or table_name == "Lock":
            lock_hints = self._extract_lock_hints(result)
            if lock_hints:
                return lock_hints

        # Item subclass hints (for class+subclass combination)
        if table_name == "item_template" or table_name == "item_dbc":
            subclass_hint = self._extract_item_subclass_hint(result)
            if subclass_hint and subclass_hint != self._extract_item_class_hint(result):
                # Only add if it provides more detail than just class
                hints["context"].append(subclass_hint)

        # Spell system hints
        if table_name == "spell_dbc" or table_name in {"Spell", "spell_template"}:
            spell_hints = self._generate_spell_hints(result)
            if spell_hints:
                hints.update(spell_hints)

        # Filter out empty hint sections
        if not any([hints["context"], hints["related_tables"], hints["notes"]]):
            return None

        return hints

    def _generate_spell_hints(self, result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Generate comprehensive hints for spell data."""
        spell_hints = {
            "table": "Spell"
            if isinstance(result, dict) and 3 in result
            else "spell_dbc",
            "context": [],
            "related_tables": [],
            "notes": [],
            "effects": [],
        }

        # Try to extract effect information (fields vary between DBC and SQL overlay)
        for effect_num in range(3):  # Spells can have up to 3 effects
            effect_hint = self._extract_spell_effect_hint(result, effect_num)
            if effect_hint:
                spell_hints["effects"].append(f"Effect{effect_num}: {effect_hint}")

        # Check for school damage type
        for school_idx in range(6):
            str_key = str(school_idx)
            if str_key in result:
                try:
                    school_val = result[str_key]
                    if school_val and int(str(school_val)) > 0:
                        school_name = self.SPELL_SCHOOLS.get(
                            int(school_val), f"Unknown ({school_val})"
                        )
                        spell_hints["notes"].append(f"School Damage: {school_name}")
                        break
                except (ValueError, TypeError):
                    pass

        # Add effect descriptions if found
        if spell_hints["effects"]:
            spell_hints["context"].append("Spell effects:")
            for effect in spell_hints["effects"]:
                spell_hints["context"].append(f"  - {effect}")

        # Check if any hints were generated
        if not any(
            [spell_hints["context"], spell_hints["effects"], spell_hints["notes"]]
        ):
            return None

        return spell_hints


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
