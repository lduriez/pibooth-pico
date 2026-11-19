# -*- coding: utf-8 -*-
"""pibooth plugin: physical buttons and LEDs through a Raspberry Pi Pico (USB serial).

Outside a Raspberry Pi, pibooth creates its gpiozero buttons/LEDs on simulated
pins (MockFactory). This plugin:
  * "presses" those simulated pins when the Pico reports a button press, which
    reuses all of pibooth's native logic (debounce_delay, both buttons for the
    menu, menu navigation, left/right choice...);
  * reads the state of the simulated LEDs (including blinking handled by
    gpiozero) and mirrors it to the real LEDs wired to the Pico.

Enable it in pibooth.cfg:
    [GENERAL]
    plugins = /path/to/pibooth_pico.py
    [PICO]
    port = /dev/pibooth-pico
"""

import threading
import time

import pibooth
import serial
from pibooth.utils import LOGGER

__version__ = "1.0.0"

SECTION = "PICO"
LED_POLL_S = 0.02
RETRY_S = 2.0


class PicoBridge(threading.Thread):

    def __init__(self, port, app):
        super().__init__(name="pibooth-pico", daemon=True)
        self.port = port
        self.app = app
        self._stop_evt = threading.Event()
        self._ser = None
        self._leds_sent = None
        self._pins = {
            "C": app.buttons.capture.pin,
            "P": app.buttons.printer.pin,
        }
        for pin in self._pins.values():
            if not hasattr(pin, "drive_low"):
                raise RuntimeError(
                    "pibooth_pico: buttons are not on simulated pins "
                    "(is pibooth running on a real Raspberry Pi?)")

    # --- Buttons -----------------------------------------------------------
    def _set_button(self, key, is_pressed):
        pin = self._pins[key]
        # pull_up=True in pibooth: low level = pressed
        if is_pressed:
            pin.drive_low()
        else:
            pin.drive_high()

    def _release_all(self):
        for key in self._pins:
            self._set_button(key, False)

    def _handle_line(self, line):
        if len(line) == 2 and line[0] in self._pins and line[1] in "01":
            LOGGER.debug("Pico: button %s %s", line[0], "pressed" if line[1] == "1" else "released")
            self._set_button(line[0], line[1] == "1")

    # --- LEDs --------------------------------------------------------------
    def _sync_leds(self, force=False):
        state = "L{}{}".format(int(bool(self.app.leds.capture.value)),
                               int(bool(self.app.leds.printer.value)))
        if force or state != self._leds_sent:
            self._ser.write((state + "\n").encode())
            self._leds_sent = state

    # --- Main loop ---------------------------------------------------------
    def run(self):
        while not self._stop_evt.is_set():
            try:
                self._ser = serial.Serial(self.port, 115200, timeout=LED_POLL_S)
                LOGGER.info("Pico connected on %s", self.port)
                self._ser.reset_input_buffer()
                self._ser.write(b"?\n")
                self._sync_leds(force=True)
                buf = b""
                while not self._stop_evt.is_set():
                    buf += self._ser.read(64)
                    while b"\n" in buf:
                        raw, buf = buf.split(b"\n", 1)
                        self._handle_line(raw.decode(errors="ignore").strip().upper())
                    self._sync_leds()
            except (serial.SerialException, OSError) as exc:
                LOGGER.warning("Pico unavailable on %s (%s), retrying in %ss",
                               self.port, exc, RETRY_S)
            finally:
                self._release_all()  # never leave a button stuck "pressed"
                if self._ser is not None:
                    try:
                        self._ser.write(b"L00\n")
                        self._ser.close()
                    except Exception:
                        pass
                    self._ser = None
                self._leds_sent = None
            self._stop_evt.wait(RETRY_S)

    def stop(self):
        self._stop_evt.set()
        self.join(timeout=2)


@pibooth.hookimpl
def pibooth_configure(cfg):
    cfg.add_option(SECTION, "port", "/dev/pibooth-pico",
                   "Serial port of the Raspberry Pi Pico (buttons/LEDs)")


@pibooth.hookimpl
def pibooth_startup(cfg, app):
    app.pico_bridge = PicoBridge(cfg.get(SECTION, "port"), app)
    app.pico_bridge.start()


@pibooth.hookimpl
def pibooth_cleanup(app):
    bridge = getattr(app, "pico_bridge", None)
    if bridge:
        bridge.stop()
