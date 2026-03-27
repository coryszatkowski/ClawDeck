#!/usr/bin/env python3
"""
Overlay helper: draws an amber rounded-corner border around a terminal window.

Uses a single transparent NSWindow with a CALayer border (cornerRadius +
borderWidth) — no custom NSView needed. Reads position from
/tmp/deck-overlay.json every 100ms.

Spawned by main.py — not meant to be run standalone (though it can be for testing).
"""

import json
import signal
import sys
from pathlib import Path

import objc
from AppKit import (
    NSApplication,
    NSWindow,
    NSColor,
    NSTimer,
    NSWindowStyleMaskBorderless,
    NSBackingStoreBuffered,
    NSFloatingWindowLevel,
)
from Foundation import NSObject, NSAutoreleasePool
from Quartz import CGMainDisplayID, CGDisplayBounds, CGColorCreateGenericRGB


import os as _os
OVERLAY_FILE = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), ".deck-overlay.json")
BORDER_WIDTH = 2          # pixels
CORNER_RADIUS = 10        # matches macOS window corners
CHECK_INTERVAL = 0.1      # seconds between position checks
AMBER = (255, 176, 0)
ALPHA = 0.85


# ── Window management (plain Python, no ObjC selector conflicts) ─────

def create_overlay_window():
    """Create a single transparent window with a CALayer rounded border."""
    frame = ((0, 0), (1, 1))
    win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        frame,
        NSWindowStyleMaskBorderless,
        NSBackingStoreBuffered,
        False,
    )
    win.setLevel_(NSFloatingWindowLevel + 1)
    win.setOpaque_(False)
    win.setBackgroundColor_(NSColor.clearColor())
    win.setIgnoresMouseEvents_(True)
    win.setHasShadow_(False)
    win.setCollectionBehavior_(1 << 0)  # canJoinAllSpaces

    # Use CALayer for the rounded border
    view = win.contentView()
    view.setWantsLayer_(True)
    layer = view.layer()
    layer.setCornerRadius_(CORNER_RADIUS)
    layer.setBorderWidth_(BORDER_WIDTH)

    r, g, b = AMBER
    border_color = CGColorCreateGenericRGB(r / 255, g / 255, b / 255, ALPHA)
    layer.setBorderColor_(border_color)
    layer.setBackgroundColor_(CGColorCreateGenericRGB(0, 0, 0, 0))  # transparent fill

    return win


def show_overlay(win, primary_h, qx, qy, qw, qh):
    """Position the overlay window over the given Quartz-coordinates rect."""
    # Convert Quartz (top-left origin) → AppKit (bottom-left origin)
    ns_y = primary_h - qy - qh
    win.setFrame_display_(((qx, ns_y), (qw, qh)), True)
    win.orderFront_(None)


def hide_overlay(win):
    """Hide the overlay window."""
    win.orderOut_(None)


# ── NSObject subclass (only the timer callback) ─────────────────────

class OverlayTick(NSObject):
    """Minimal NSObject — only exposes the timer callback to avoid
    PyObjC selector conflicts with helper methods."""

    def init(self):
        self = objc.super(OverlayTick, self).init()
        if self is None:
            return None

        self.win = create_overlay_window()
        self.visible = False
        self.last_rect = None
        self.last_color = None

        return self

    def _update_border_color(self, rgb):
        """Update the overlay border color if it changed."""
        if rgb == self.last_color:
            return
        r, g, b = rgb
        border_color = CGColorCreateGenericRGB(r / 255, g / 255, b / 255, ALPHA)
        layer = self.win.contentView().layer()
        layer.setBorderColor_(border_color)
        self.last_color = rgb

    def tick_(self, timer):
        """Called every CHECK_INTERVAL by NSTimer."""
        try:
            text = Path(OVERLAY_FILE).read_text()
            data = json.loads(text)

            if data.get("visible", False):
                # Update color if provided
                color_list = data.get("color")
                if color_list and len(color_list) == 3:
                    self._update_border_color(tuple(color_list))

                rect = (data["x"], data["y"], data["w"], data["h"])
                if rect != self.last_rect or not self.visible:
                    primary_h = CGDisplayBounds(CGMainDisplayID()).size.height
                    show_overlay(self.win, primary_h, *rect)
                    self.last_rect = rect
                    self.visible = True
            else:
                if self.visible:
                    hide_overlay(self.win)
                    self.visible = False
                    self.last_rect = None

        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            if self.visible:
                hide_overlay(self.win)
                self.visible = False
                self.last_rect = None


# ═══════════════════════════════════════════════════════════════════════

def main():
    pool = NSAutoreleasePool.alloc().init()

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(2)  # Accessory — no dock icon, no menu bar

    controller = OverlayTick.alloc().init()

    NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
        CHECK_INTERVAL, controller, "tick:", None, True
    )

    def shutdown(sig, frame):
        app.terminate_(None)
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    try:
        app.run()
    finally:
        try:
            Path(OVERLAY_FILE).unlink(missing_ok=True)
        except Exception:
            pass
        pool.release()


if __name__ == "__main__":
    main()
