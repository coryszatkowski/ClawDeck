# Logging & Exception Handling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace silent exception swallowing with proper logging so errors surface, and convert operational print() calls to Python's logging module with file output.

**Architecture:** Add a module-level `logging` setup in main.py with console (INFO) and rotating file (DEBUG) handlers. Fix exception handlers in three tiers: poll loop gets error counting + WARNING logs, expected exceptions get DEBUG logs, bare `except: pass` blocks get WARNING logs. REPL print() calls stay as-is.

**Tech Stack:** Python stdlib `logging`, `logging.handlers.RotatingFileHandler`

---

### Task 1: Add logging setup at module level

**Files:**
- Modify: `main.py:37-43` (imports section)
- Modify: `main.py` (add setup function after imports, before class definition)

- [ ] **Step 1: Add logging imports and setup function**

After the existing imports (line 43), add:

```python
import logging
from logging.handlers import RotatingFileHandler

def _setup_logging():
    """Configure clawdeck logger with console and file handlers."""
    log_dir = Path.home() / ".clawdeck"
    log_dir.mkdir(exist_ok=True)

    logger = logging.getLogger("clawdeck")
    logger.setLevel(logging.DEBUG)

    # Console: INFO and above
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(console)

    # File: DEBUG and above, rotating 1MB x 3 backups
    file_handler = RotatingFileHandler(
        log_dir / "clawdeck.log", maxBytes=1_000_000, backupCount=3
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    ))
    logger.addHandler(file_handler)

    return logger

logger = _setup_logging()
```

- [ ] **Step 2: Verify logging works**

Run: `.venv/bin/python -c "import main; main.logger.info('test'); main.logger.debug('debug test')"`

Expected: `[INFO] test` printed to console. `~/.clawdeck/clawdeck.log` contains both lines with timestamps.

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "Add logging setup with console and rotating file handlers"
```

---

### Task 2: Fix poll loop exception handling (Tier 1)

**Files:**
- Modify: `main.py:1475-1518` (`_poll_active_loop` method)

- [ ] **Step 1: Add error counter and replace bare except**

Replace the current `_poll_active_loop` method (lines 1475-1518):

```python
    def _poll_active_loop(self):
        """Background thread: sync active_slot and Claude status with the grid."""
        consecutive_errors = 0
        while self.running:
            try:
                if self.mode == MODE_GRID:
                    needs_redraw = False

                    # Periodically refresh TTY map so new/changed terminals get picked up
                    now_tty = time.time()
                    if now_tty - self._last_tty_refresh >= TTY_MAP_REFRESH_SEC:
                        self._build_tty_map()
                        self._last_tty_refresh = now_tty

                    # Snap-to-grid: detect dragged windows and snap them
                    if self.config["snap_enabled"] and self._check_snap_to_grid():
                        needs_redraw = True

                    # Check frontmost window
                    slot = self._get_frontmost_slot()
                    if slot is not None and slot != self.active_slot:
                        self.active_slot = slot
                        self._update_overlay()
                        needs_redraw = True

                    # Read Claude Code status from hook files
                    old_status = dict(self.slot_status)
                    self._read_status_files()
                    if self.slot_status != old_status:
                        needs_redraw = True

                    # Toggle blink phase for permission (red) slots
                    now = time.time()
                    if now - self._last_blink_toggle >= BLINK_INTERVAL:
                        self.blink_on = not self.blink_on
                        self._last_blink_toggle = now
                        # Only redraw for blink if any slot is in permission state
                        if "permission" in self.slot_status.values():
                            needs_redraw = True

                    if needs_redraw:
                        self._update_all_buttons()

                consecutive_errors = 0
            except Exception:
                consecutive_errors += 1
                if consecutive_errors >= 10:
                    logger.error("Poll loop: %d consecutive errors", consecutive_errors, exc_info=True)
                else:
                    logger.warning("Poll loop error (consecutive: %d)", consecutive_errors, exc_info=True)
            time.sleep(self.config["poll_interval"])
```

- [ ] **Step 2: Verify the poll loop still runs**

Run: `.venv/bin/python main.py`

Expected: Controller starts normally, buttons update. Check `~/.clawdeck/clawdeck.log` — no poll loop errors should appear during normal operation.

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "Fix poll loop: log exceptions instead of silently swallowing them"
```

---

### Task 3: Fix Tier 2 — Expected/specific exception handlers

**Files:**
- Modify: `main.py` — 6 locations with specific exception types

- [ ] **Step 1: Add debug logging to config load (line 322)**

Replace:
```python
        except (FileNotFoundError, json.JSONDecodeError):
            pass
```

With:
```python
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.debug("Config load skipped: %s", e)
```

- [ ] **Step 2: Add debug logging to color parsing (line 344)**

Replace:
```python
            except (ValueError, IndexError):
                pass
```

With:
```python
            except (ValueError, IndexError) as e:
                logger.debug("Invalid color hex for '%s': %s", key, e)
```

- [ ] **Step 3: Add debug logging to font loading (line 554)**

Replace:
```python
                except (IOError, OSError):
                    continue
```

With:
```python
                except (IOError, OSError):
                    logger.debug("Font not found: %s", path)
                    continue
```

- [ ] **Step 4: Add debug logging to window parse (line 667)**

Replace:
```python
                    except ValueError:
                        continue
```

With:
```python
                    except ValueError as e:
                        logger.debug("Skipping malformed window line: %s", e)
                        continue
```

- [ ] **Step 5: Add debug logging to status file read (line 720)**

Replace:
```python
            except (json.JSONDecodeError, IOError):
                continue
```

With:
```python
            except (json.JSONDecodeError, IOError) as e:
                logger.debug("Skipping status file: %s", e)
                continue
```

- [ ] **Step 6: Add debug logging to TTY detection (line 823)**

Replace:
```python
        except (OSError, AttributeError):
            pass
```

With:
```python
        except (OSError, AttributeError) as e:
            logger.debug("TTY detection via stdin failed: %s", e)
```

- [ ] **Step 7: Add debug logging to TTY fallback (line 830)**

Replace:
```python
        except Exception:
            pass
```

With:
```python
        except Exception as e:
            logger.debug("TTY detection via tty command failed: %s", e)
```

- [ ] **Step 8: Add debug logging to settings server port binding (line 1855)**

Replace:
```python
            except OSError:
                continue
```

With:
```python
            except OSError:
                logger.debug("Port %d in use, trying next", port)
                continue
```

- [ ] **Step 9: Add debug logging to overlay log file permission (line 748)**

Replace:
```python
            except PermissionError:
                # Stale root-owned log from previous sudo run — discard output
```

With:
```python
            except PermissionError:
                logger.debug("Overlay log file permission denied, discarding output")
                # Stale root-owned log from previous sudo run — discard output
```

- [ ] **Step 10: Commit**

```bash
git add main.py
git commit -m "Add debug logging to expected exception handlers (Tier 2)"
```

---

### Task 4: Fix Tier 3 — Bare `except Exception: pass` blocks

**Files:**
- Modify: `main.py` — 8 locations with bare `except Exception: pass`

- [ ] **Step 1: Overlay file cleanup in _start_overlay (line 732)**

Replace:
```python
        except Exception:
            pass
```

With:
```python
        except Exception:
            logger.warning("Failed to clean stale overlay file", exc_info=True)
```

- [ ] **Step 2: Overlay start failure (line 756)**

Replace:
```python
        except Exception as e:
            print(f"[overlay] Failed to start overlay: {e}")
```

With:
```python
        except Exception:
            logger.error("Failed to start overlay", exc_info=True)
```

- [ ] **Step 3: Overlay stop — terminate (line 766)**

Replace:
```python
            except Exception:
                try:
                    self.overlay_proc.kill()
                except Exception:
                    pass
```

With:
```python
            except Exception:
                logger.warning("Overlay terminate failed, attempting kill", exc_info=True)
                try:
                    self.overlay_proc.kill()
                except Exception:
                    logger.warning("Overlay kill also failed", exc_info=True)
```

- [ ] **Step 4: Overlay stop — file cleanup (line 775)**

Replace:
```python
        except Exception:
            pass
```

(The one at line 775 in `_stop_overlay`)

With:
```python
        except Exception:
            logger.warning("Failed to remove overlay file", exc_info=True)
```

- [ ] **Step 5: Overlay update — atomic write (line 796)**

Replace:
```python
        except Exception:
            pass
```

With:
```python
        except Exception:
            logger.warning("Failed to write overlay file", exc_info=True)
```

- [ ] **Step 6: Get terminal windows — outer exception (line 670)**

Replace:
```python
        except Exception:
            return []
```

With:
```python
        except Exception:
            logger.warning("Failed to get terminal windows", exc_info=True)
            return []
```

- [ ] **Step 7: Settings server — brightness set (line 1821)**

Replace:
```python
                        except Exception:
                            pass
```

With:
```python
                        except Exception:
                            logger.warning("Failed to set brightness via settings API", exc_info=True)
```

- [ ] **Step 8: Settings server — config save (line 1813)**

Replace:
```python
                    except Exception as e:
                        self._json_response({"ok": False, "error": str(e)}, 500)
```

With:
```python
                    except Exception as e:
                        logger.error("Settings API: config save failed", exc_info=True)
                        self._json_response({"ok": False, "error": str(e)}, 500)
```

- [ ] **Step 9: MIC command failure (line 1192)**

Replace:
```python
            except Exception as e:
                print(f"[mic] Command failed: {e}")
```

With:
```python
            except Exception:
                logger.warning("MIC command failed", exc_info=True)
```

- [ ] **Step 10: Commit**

```bash
git add main.py
git commit -m "Add warning/error logging to bare except blocks (Tier 3)"
```

---

### Task 5: Convert operational print() calls to logger

**Files:**
- Modify: `main.py` — ~15 operational print() calls with `[prefix]` format

- [ ] **Step 1: Convert [config] print (line 335)**

Replace:
```python
            print(f"[config] Failed to save: {e}")
```

With:
```python
            logger.error("Config save failed: %s", e)
```

- [ ] **Step 2: Convert [screen] print (line 539)**

Replace:
```python
        print(f"[screen] Display at ({x}, {y}), {w}x{h}, menu_bar={menu_bar_h}px, dock={dock_h}px")
```

With:
```python
        logger.info("Display at (%d, %d), %dx%d, menu_bar=%dpx, dock=%dpx", x, y, w, h, menu_bar_h, dock_h)
```

- [ ] **Step 3: Convert [tile] prints (lines 859, 872, 880)**

Replace:
```python
            print("[tile] No terminal windows found.")
```
With:
```python
            logger.warning("No terminal windows found")
```

Replace:
```python
            print(f"[tile] Controller terminal → slot 14")
```
With:
```python
            logger.info("Controller terminal -> slot 14")
```

Replace:
```python
        print(f"[tile] Found {len(term_wins)} terminal window(s), tiling {count} into layout '{self.config.get('layout', 'default')}'")
```
With:
```python
        logger.info("Found %d terminal window(s), tiling %d into layout '%s'", len(term_wins), count, self.config.get('layout', 'default'))
```

- [ ] **Step 4: Convert [snap] print (line 1006)**

Replace:
```python
                                print(f"[snap] Snapping window to {best_terminal}")
```

With:
```python
                                logger.info("Snapping window to %s", best_terminal)
```

- [ ] **Step 5: Convert startup operational prints**

Replace line 1675:
```python
        print(f"Found {len(devices)} HID interface(s), attempting to open...")
```
With:
```python
        logger.info("Found %d HID interface(s), attempting to open...", len(devices))
```

Replace line 1680:
```python
                print(f"  Opened interface {i}: {dev.deck_type()}")
```
With:
```python
                logger.info("Opened interface %d: %s", i, dev.deck_type())
```

Replace line 1693:
```python
        print(f"Connected: {self.deck.deck_type()} ({key_count} keys)")
```
With:
```python
        logger.info("Connected: %s (%d keys)", self.deck.deck_type(), key_count)
```

Replace line 1700:
```python
        print("Tiling terminal windows...")
```
With:
```python
        logger.info("Tiling terminal windows...")
```

Replace line 1726:
```python
        print("Starting screen overlay...")
```
With:
```python
        logger.info("Starting screen overlay...")
```

- [ ] **Step 6: Convert error prints that also need user-facing output**

Replace lines 1669-1670:
```python
            print("No Stream Deck found. Make sure it's plugged in.")
            print("Also verify: brew install hidapi && pip install streamdeck")
```
With:
```python
            logger.error("No Stream Deck found")
            print("No Stream Deck found. Make sure it's plugged in.")
            print("Also verify: brew install hidapi && pip install streamdeck")
```

Replace line 1683:
```python
                print(f"  Interface {i} failed: {e}")
```
With:
```python
                logger.warning("Interface %d failed: %s", i, e)
```

Replace lines 1685-1686:
```python
            print("ERROR: Could not open any Stream Deck interface.")
            print("If this is a permissions issue, try: sudo python main.py")
```
With:
```python
            logger.error("Could not open any Stream Deck interface")
            print("ERROR: Could not open any Stream Deck interface.")
            print("If this is a permissions issue, try: sudo python main.py")
```

Replace lines 1696-1697:
```python
            print(f"Warning: this script expects {TOTAL_KEYS} keys but your deck has {key_count}.")
            print("The key layout may not work correctly.")
```
With:
```python
            logger.warning("Expected %d keys but deck has %d — layout may not work correctly", TOTAL_KEYS, key_count)
            print(f"Warning: this script expects {TOTAL_KEYS} keys but your deck has {key_count}.")
            print("The key layout may not work correctly.")
```

- [ ] **Step 7: Convert mic learn print (line 1234)**

Replace:
```python
            print("  Failed to create event tap — check Accessibility permissions")
```
With:
```python
            logger.error("Failed to create event tap — check Accessibility permissions")
            print("  Failed to create event tap — check Accessibility permissions")
```

- [ ] **Step 8: Verify the full application**

Run: `.venv/bin/python main.py`

Expected:
- Console shows INFO-level messages during startup (Connected, Tiling, etc.)
- `~/.clawdeck/clawdeck.log` contains timestamped DEBUG-level messages
- REPL help text, command responses, and banner still print normally
- No duplicate output (operational logs should appear once via logger, not logger + print)

- [ ] **Step 9: Commit**

```bash
git add main.py
git commit -m "Convert operational print() calls to logger (keep REPL prints as-is)"
```

---

### Task 6: Final verification

- [ ] **Step 1: Review the log file**

Run: `cat ~/.clawdeck/clawdeck.log`

Verify: timestamps present, severity levels correct, no bare print-style output leaked in.

- [ ] **Step 2: Verify no remaining bare `except: pass`**

Run: `grep -n "except.*:$" main.py` and check that none are followed by just `pass` on the next line (except the REPL's `KeyboardInterrupt/EOFError` handler which is correct).

- [ ] **Step 3: Count remaining print() calls**

Run: `grep -c "print(" main.py`

Expected: ~55-60 remaining (all REPL/help/banner/accessibility — no operational logs).

- [ ] **Step 4: Final commit if any cleanup needed**

```bash
git add main.py
git commit -m "Wave 1 complete: logging and exception handling"
```
