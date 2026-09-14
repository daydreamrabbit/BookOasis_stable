---
title: "MCP Server Guide"
project: "BookOasis"
category: "guide"
date: 2026-09-14
tags: [mcp, ai, claude, guide]
---

# 🤖 BookOasis MCP Server Guide

As a library grows into the tens or hundreds of thousands of books, manually tracking data-quality issues (missing covers/genre/tags, series scattered as duplicates across categories) becomes practically impossible. BookOasis ships a **read-only MCP (Model Context Protocol) server**, so any MCP-capable AI coding tool (Claude Code, Claude Desktop, Gemini CLI, OpenAI Codex CLI, Cursor, etc. — MCP is an open standard, not tied to any one vendor) can query your library directly and surface problems to you.

- Transport is **local stdio only** — never exposed over the network. The AI tool runs the `tools/mcp_server.py` process directly on the same machine where BookOasis is installed. No extra authentication setup needed.
- v1 is **read-only**. It covers search, stats, and data-quality diagnostics; actual fixes are still made by an admin through the existing web UI.
- Install the `mcp` package first with `pip install -r requirements.txt`. Registration steps below are per-client — skip the ones you don't use.

## Registration

### Common — the MCP server definition (JSON)

Nearly every MCP client ultimately registers a server with a JSON block shaped like this; only the config file's name/location differs between clients.

```json
{
  "mcpServers": {
    "bookoasis": {
      "command": "python3",
      "args": ["/path/to/media_server/tools/mcp_server.py"]
    }
  }
}
```

Replace `/path/to/media_server` with your actual BookOasis install path (absolute path).

### Claude Code

```bash
claude mcp add bookoasis -- python3 /path/to/media_server/tools/mcp_server.py
```

Confirm with `claude mcp list` — it should show `✔ Connected`.

### Claude Desktop

Open `claude_desktop_config.json` (macOS: `~/Library/Application Support/Claude/`, Windows: `%APPDATA%\Claude\`), add the "common JSON" block above under `mcpServers`, and restart the app.

### Gemini CLI / OpenAI Codex CLI / Cursor / other MCP clients

Most of these also use the same `mcpServers` JSON shape, but the exact config file name/location and any CLI registration command (if one exists) varies by tool and can change over time. Check that tool's current official docs for "register an MCP server" and paste in the common JSON block above — as long as `command`/`args` are correct, it works identically regardless of which client you use.

To inspect the tool list/schema quickly without any client, using the official inspector bundled with the `mcp` package:

```bash
mcp dev tools/mcp_server.py
```

## Available tools (v1, read-only)

| Tool | Description |
| :--- | :--- |
| `search_books` | Search series by title/series name (genre/tag filters supported) |
| `get_library_stats` | Total and per-category series/book counts |
| `find_missing_cover` | Books with no cover image |
| `find_missing_genre_and_tags` | Books with both genre and tags empty |
| `find_missing_offsets` | zip/cbz books missing their page-offset cache and needing a rescan (remote-mounted files such as rclone/GDrive are automatically excluded) |
| `find_duplicate_series` | Cases where the exact same series name is scattered across 2+ categories |
| `run_readonly_query` | Run raw read-only (SELECT/WITH/EXPLAIN/PRAGMA) SQL against the library DB |
| `read_logs` | Tail the last N lines of a server log under `logs/` (with an optional search filter) |

`find_duplicate_series` only catches exact-name duplicates. For near-duplicates with typos or variant spellings, let Claude explore with `search_books` and judge for itself — that kind of fuzzy-matching judgment call is exactly why you'd hand this off to an AI via MCP in the first place.

### `run_readonly_query` — ask about the schema first if you don't know it

Use this tool for any ad-hoc condition the built-in diagnostic tools don't cover. If you're unsure of the table structure, start with a schema query like `PRAGMA table_info(books)`. Safety is enforced in two layers:

1. **App level**: rejected immediately if the SQL doesn't start with `SELECT`/`WITH`/`EXPLAIN`/`PRAGMA`, contains multiple `;`-separated statements, or contains a write keyword like `INSERT`/`UPDATE`/`DELETE`/`DROP`.
2. **DB level (the real safety net)**: in sqlite mode, every call opens a fresh, genuinely OS-level read-only connection (`file:...?mode=ro`) — even if layer 1 were bypassed, the file physically can't be written to. In MariaDB mode there's no separate read-only account, so the tool wraps the borrowed pooled connection in `SET SESSION TRANSACTION READ ONLY` for the duration of the call and restores it afterward (MariaDB's defense is one notch weaker than sqlite's — there's no plan to add a dedicated read-only DB account, since this is a single-trusted-operator local stdio server to begin with).

## `db_type` values

Most tools accept a `db_type` parameter: `general` (general library, default) / `adult` (adult library) / `audiobook`. `video` has a different book-table structure so it isn't a target for the fixed diagnostic tools (`find_missing_*`, `find_duplicate_series`), but `run_readonly_query` allows `video` too.

## Roadmap

- Write tools (bulk genre/tag fixes, triggering rescans) — under consideration once the diagnostic tools have proven trustworthy in practice. For anything destructive, "propose a change → admin approves it in the existing web UI" is the preferred shape over direct execution.
- Orphaned-file detection (a DB row exists but the file is gone from disk) — checking existence for every book is slow on remote mounts (rclone/GDrive), so this needs a background job reusing the existing scanner queue plus a separate results-only tool, rather than a synchronous MCP call.
