# dbc-query

MCP (Model Context Protocol) server for querying World of Warcraft DBC (Database Client) files directly.

## Overview

This tool allows AI assistants to query WoW DBC files without requiring SQL import. It reads WDBC format files directly and provides a query interface through the MCP protocol.

## Features

- Direct WDBC file parsing (WoW 3.3.5 / WotLK)
- Automatic format string extraction from AzerothCore source
- SQL-like query interface
- No database import required
- Lightweight and portable

## Requirements

- Python 3.7+
- AzerothCore DBC files
- AzerothCore source (for format definitions)

## Installation

TBD

## Usage

TBD

## Architecture

- `server.py` - MCP server implementation
- `dbc_reader.py` - WDBC file parser
- `format_parser.py` - DBCfmt.h parser for format strings

## License

TBD
