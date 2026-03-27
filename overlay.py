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
    NSTextField,
    NSFont,
    NSTextAlignmentCenter,
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


LABEL_HEIGHT = 26     # pixels for the folder label bar


def create_label_window():
    """Create a window for the folder label bar at the top of the overlay."""
    frame = ((0, 0), (1, 1))
    win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        frame,
        NSWindowStyleMaskBorderless,
        NSBackingStoreBuffered,
        False,
    )
    win.setLevel_(NSFloatingWindowLevel + 2)  # above the border overlay
    win.setOpaque_(False)
    win.setBackgroundColor_(NSColor.clearColor())
    win.setIgnoresMouseEvents_(True)
    win.setHasShadow_(False)
    win.setCollectionBehavior_(1 << 0)  # canJoinAllSpaces

    # Use CALayer for rounded corners on the background
    view = win.contentView()
    view.setWantsLayer_(True)
    layer = view.layer()
    # Default amber — will be updated dynamically from IPC color
    r, g, b = AMBER
    layer.setBackgroundColor_(CGColorCreateGenericRGB(r / 255.0, g / 255.0, b / 255.0, 1.0))
    layer.setCornerRadius_(CORNER_RADIUS)
    # Only round top corners by masking bottom
    layer.setMaskedCorners_(1 << 2 | 1 << 3)  # kCALayerMinXMaxYCorner | kCALayerMaxXMaxYCorner (AppKit top = visual top)

    # Create text field — no background, vertically centered via frame offset
    label = NSTextField.alloc().initWithFrame_(((0, 0), (1, LABEL_HEIGHT)))
    label.setBezeled_(False)
    label.setDrawsBackground_(False)
    label.setEditable_(False)
    label.setSelectable_(False)
    label.setAlignment_(NSTextAlignmentCenter)
    label.setFont_(NSFont.boldSystemFontOfSize_(16.0))
    label.setTextColor_(NSColor.blackColor())  # default — updated dynamically

    view.addSubview_(label)
    return win, label


def show_label(win, label_field, primary_h, qx, qy, qw):
    """Position the label window at the top of the overlay rect."""
    ns_y = primary_h - qy - LABEL_HEIGHT
    win.setFrame_display_(((qx, ns_y), (qw, LABEL_HEIGHT)), True)
    # Center text vertically — offset the text field down slightly
    text_h = 20  # approximate height of 16pt bold text
    y_offset = (LABEL_HEIGHT - text_h) / 2
    label_field.setFrame_(((0, y_offset), (qw, text_h)))
    win.orderFront_(None)


def hide_label(win):
    """Hide the label window."""
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
        self.label_win, self.label_field = create_label_window()
        self.last_cwd = None
        self.last_label_bg = None
        self.last_label_text = None

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

                # Show/hide folder label
                cwd = data.get("cwd")
                if cwd:
                    # Update label bar background to match active color
                    if color_list and tuple(color_list) != self.last_label_bg:
                        r, g, b = color_list
                        bg_color = CGColorCreateGenericRGB(r / 255, g / 255, b / 255, 1.0)
                        self.label_win.contentView().layer().setBackgroundColor_(bg_color)
                        self.last_label_bg = tuple(color_list)

                    # Update label text color
                    text_color = data.get("label_text_color")
                    if text_color and len(text_color) == 3 and tuple(text_color) != self.last_label_text:
                        r, g, b = text_color
                        self.label_field.setTextColor_(
                            NSColor.colorWithCalibratedRed_green_blue_alpha_(r / 255.0, g / 255.0, b / 255.0, 1.0)
                        )
                        self.last_label_text = tuple(text_color)

                    if cwd != self.last_cwd or rect != self.last_rect:
                        self.label_field.setStringValue_(cwd)
                        primary_h = CGDisplayBounds(CGMainDisplayID()).size.height
                        show_label(self.label_win, self.label_field, primary_h, rect[0], rect[1], rect[2])
                    self.last_cwd = cwd
                else:
                    if self.last_cwd is not None:
                        hide_label(self.label_win)
                        self.last_cwd = None
            else:
                if self.visible:
                    hide_overlay(self.win)
                    hide_label(self.label_win)
                    self.visible = False
                    self.last_rect = None
                    self.last_cwd = None

        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            if self.visible:
                hide_overlay(self.win)
                hide_label(self.label_win)
                self.visible = False
                self.last_rect = None
                self.last_cwd = None


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
