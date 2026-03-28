# Wave 1: Logging & Exception Handling

## Problem

- `_poll_active_loop` catches all exceptions with `except Exception: pass` — the controller goes blind when errors occur, causing cascading issues (wrong slot, stale overlay, etc.)
- ~90 `print()` calls with no timestamps, severity, or file output — users can't provide useful bug reports

## Design

### Logging Setup (module-level in main.py)

- Logger: `"clawdeck"`
- Console handler: INFO level, format: `[%(levelname)s] %(message)s`
- File handler: `RotatingFileHandler` at `~/.clawdeck/clawdeck.log`, DEBUG level, format includes timestamp, 1MB max with 3 backups
- Create `~/.clawdeck/` directory on startup if missing

### Exception Handler Tiers

**Tier 1 — Poll loop (`_poll_active_loop`, line 1516):**
- Log at WARNING with `exc_info=True` (full traceback in log file)
- Add consecutive error counter; escalate to ERROR after 10 consecutive failures
- Reset counter on successful iteration
- Continue polling (don't crash)

**Tier 2 — Expected/specific exceptions (FileNotFoundError, JSONDecodeError, PermissionError, etc.):**
- Add `logger.debug()` so they appear in log file
- Keep existing behavior (continue/pass)

**Tier 3 — Bare `except Exception: pass` blocks (overlay cleanup, window listing, etc.):**
- Add `logger.warning()` with exception info
- Keep "continue anyway" behavior

### print() Conversion Rules

- **Operational logs** (`[tile]`, `[config]`, `[overlay]`, `[snap]`, `[mic]` prefixed): Convert to `logger.info()` / `logger.warning()`
- **REPL output** (help text, command responses, startup banner): Keep as `print()` — these are user-facing CLI, not log events
- **Error messages shown to user** (e.g. "No Stream Deck found"): Keep as `print()` AND add `logger.error()`

### Out of Scope

- overlay.py, menubar.py, install_hooks.py (no print() calls / separate concerns)
- Splitting main.py into modules (Wave 4+ work)
- Structured/JSON logging (YAGNI for now)
