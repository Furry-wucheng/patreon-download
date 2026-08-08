# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A Python CLI tool for downloading Patreon content (posts, user collections, shop items). Uses the Patreon API with cookie-based authentication. Requires Python 3.13+.

## Commands

### Setup
```bash
uv sync                    # Install dependencies
cp config.json.example config.json  # Create config (must add cookie)
```

### Run
```bash
uv run patreon-dl post <url>   # Download single post
uv run patreon-dl user <url>   # Download all posts from creator
uv run patreon-dl shop <url>   # Download shop items
uv run python -m patreon_download --help  # Alternative entry via __main__.py
```

### Test
```bash
uv run pytest tests/ -v                         # All tests
uv run pytest tests/test_utils.py -v            # Single module
uv run pytest tests/ --cov=patreon_download     # With coverage
```

## Architecture

```
src/patreon_download/
├── __main__.py     # python -m entry point
├── cli.py          # argparse, command dispatch (post/user/shop)
├── config.py       # Config dataclass, JSON loading, validation
├── api.py          # PatreonClient: HTTP requests, pagination, JSON:API parsing
├── models.py       # Dataclasses: Post, Product, MediaItem
├── downloader.py   # File download, progress bars, threading, hash dedup
└── utils.py        # URL parsing, filename sanitization, template formatting
```

**Data flow**: CLI parses args → `Config.load()` → `PatreonClient` fetches API data → returns `Post`/`Product` models → `downloader.py` saves files to disk.

**Config search order**: `--config` flag > `./config.json` > `~/.patreon-dl/config.json`

**Key patterns**:
- Patreon JSON:API responses are parsed in `api.py` using `_safe_get()` for nested dict traversal
- `downloader.py` uses `HashRegistry` (SHA256 in `.hashes.json`) for content-based deduplication, thread-safe with locks
- Rich library provides progress bars and console output
- `requests.Session` maintains cookies across API calls with automatic retry and rate limiting
- `api.py` extracts campaign IDs from HTML via regex on `window.patreon` or `__NEXT_DATA__` scripts (three fallback methods)
