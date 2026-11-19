# main.py — MicroPython firmware for Raspberry Pi Pico H
# USB serial bridge between physical buttons/LEDs and pibooth (pibooth_pico.py plugin).
#
# Protocol (ASCII lines terminated by \n):
#   Pico -> PC : "C1" / "C0"  capture button pressed / released
#                "P1" / "P0"  print button pressed / released
#                "PONG"       reply to PING
#   PC -> Pico : "Lxy"        x = capture LED (0/1), y = print LED (0/1)
#                "?"          send back the current state of both buttons
#                "PING"

import sys
import select
import time
from machine import Pin

# --- Wiring (Pico GPxx numbers, not physical pin numbers) ---
BTN_CAPTURE = 14   # physical pin 19 — button between GP14 and GND
BTN_PRINT = 15     # physical pin 20 — button between GP15 and GND
LED_CAPTURE = 16   # physical pin 21 — through a 220-330 Ω resistor to the LED
LED_PRINT = 17     # physical pin 22
DEBOUNCE_MS = 20

buttons = {
    "C": Pin(BTN_CAPTURE, Pin.IN, Pin.PULL_UP),
    "P": Pin(BTN_PRINT, Pin.IN, Pin.PULL_UP),
}
leds = {
    "C": Pin(LED_CAPTURE, Pin.OUT, value=0),
    "P": Pin(LED_PRINT, Pin.OUT, value=0),
}
Pin(25, Pin.OUT, value=1)  # Pico H onboard LED: firmware is running

# Debounced "pressed" state (True = pressed; pull-up, so level 0 = pressed)
pressed = {k: False for k in buttons}
last_raw = {k: 1 for k in buttons}
raw_since = {k: time.ticks_ms() for k in buttons}


def send(msg):
    sys.stdout.write(msg + "\n")


def handle(line):
    line = line.strip().upper()
    if not line:
        return
    if line[0] == "L" and len(line) == 3:
        leds["C"].value(line[1] == "1")
        leds["P"].value(line[2] == "1")
    elif line == "?":
        for k in buttons:
            send(k + ("1" if pressed[k] else "0"))
    elif line == "PING":
        send("PONG")


poll = select.poll()
poll.register(sys.stdin, select.POLLIN)
buf = ""

while True:
    now = time.ticks_ms()

    # Buttons with debouncing
    for k, pin in buttons.items():
        raw = pin.value()
        if raw != last_raw[k]:
            last_raw[k] = raw
            raw_since[k] = now
        elif time.ticks_diff(now, raw_since[k]) >= DEBOUNCE_MS:
            is_pressed = raw == 0
            if is_pressed != pressed[k]:
                pressed[k] = is_pressed
                send(k + ("1" if is_pressed else "0"))

    # Commands from the PC (non-blocking)
    while poll.poll(0):
        ch = sys.stdin.read(1)
        if ch in ("\n", "\r"):
            handle(buf)
            buf = ""
        else:
            buf = (buf + ch)[-32:]

    time.sleep_ms(2)
