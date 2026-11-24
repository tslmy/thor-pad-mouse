#!/usr/bin/env python3
"""End-to-end check on the handheld itself. Run with sudo.

It writes fake stick/button events into the built-in controller, which
InputPlumber has grabbed, and reads what comes out of InputPlumber's virtual
mouse. The virtual mouse is grabbed for the duration, so the running desktop
receives none of the test movement or clicks. Do not touch the controls while
it runs.

--live          do not grab the virtual mouse: the desktop really moves and clicks.
                Only for automated checks with a test window covering the screen.
--expect-stock  assert that nothing reaches the mouse (mouse mode off).
"""
import fcntl
import glob
import os
import select
import struct
import sys
import time

EV_SYN, EV_KEY, EV_REL, EV_ABS = 0, 1, 2, 3
ABS_X, ABS_Y, ABS_Z, ABS_RX, ABS_RY, ABS_RZ = range(6)
REL_X, REL_Y, REL_WHEEL = 0, 1, 8
BTN_LEFT, BTN_RIGHT, BTN_TL, BTN_TR = 0x110, 0x111, 0x136, 0x137
EVIOCGRAB = 0x40044590
EVENT = struct.Struct('llHHi')
ABSINFO = struct.Struct('6i')


def sysfs(event, name):
    with open(f'/sys/class/input/{event}/device/{name}') as handle:
        return handle.read().strip()


def bit(event, kind, code):
    words = sysfs(event, f'capabilities/{kind}').split()
    value = 0
    for word in words:
        value = value << (struct.calcsize('l') * 8) | int(word, 16)
    return bool(value >> code & 1)


def find_gamepad():
    """The built-in pad is the hidden source device that has a right stick."""
    for path in sorted(glob.glob('/dev/inputplumber/by-hidden/event*')):
        event = os.path.basename(path)
        if bit(event, 'abs', ABS_RX) and bit(event, 'key', BTN_TR):
            return f'/dev/input/{event}', sysfs(event, 'name')
    sys.exit('No InputPlumber-managed gamepad with a right stick and R1 found.')


def find_mouse():
    for path in glob.glob('/sys/class/input/event*'):
        event = os.path.basename(path)
        if sysfs(event, 'name') == 'InputPlumber Mouse':
            return f'/dev/input/{event}'
    sys.exit('InputPlumber has no virtual mouse target.')


class Rig:
    def __init__(self, pad, mouse, grab=True):
        self.pad = os.open(pad, os.O_RDWR)
        self.mouse = os.open(mouse, os.O_RDONLY | os.O_NONBLOCK)
        self.grabbed = grab
        if grab:
            fcntl.ioctl(self.mouse, EVIOCGRAB, 1)

    def limit(self, code):
        raw = bytearray(ABSINFO.size)
        fcntl.ioctl(self.pad, 0x80184540 + code, raw)  # EVIOCGABS
        return ABSINFO.unpack(raw)[2]

    def send(self, kind, code, value):
        os.write(self.pad, EVENT.pack(0, 0, kind, code, value) + EVENT.pack(0, 0, EV_SYN, 0, 0))

    def read(self, seconds):
        events, end = [], time.monotonic() + seconds
        while (left := end - time.monotonic()) > 0:
            if not select.select([self.mouse], [], [], left)[0]:
                break
            data = os.read(self.mouse, EVENT.size * 64)
            for offset in range(0, len(data), EVENT.size):
                _, _, kind, code, value = EVENT.unpack_from(data, offset)
                if kind != EV_SYN:
                    events.append((kind, code, value))
        return events

    def push(self, code, value, seconds=0.5):
        """Hold one axis, return it to centre, and report what the mouse did."""
        self.read(0.1)
        events, end = [], time.monotonic() + seconds
        while time.monotonic() < end:
            # The real controller keeps reporting its resting position, so
            # keep re-asserting the fake one while the stick is "held".
            self.send(EV_ABS, code, value)
            events += self.read(0.0005)
        self.send(EV_ABS, code, 0)
        events += self.read(0.2)
        quiet = self.read(0.3)  # nothing may keep moving after release
        return events, quiet

    def tap(self, kind, code, down):
        self.read(0.1)
        self.send(kind, code, down)
        events = self.read(0.2)
        self.send(kind, code, 0)
        return events + self.read(0.2)


def total(events, axis):
    return sum(value for kind, code, value in events if kind == EV_REL and code == axis)


def buttons(events):
    return [(code, value) for kind, code, value in events if kind == EV_KEY]


def main():
    expect_mouse = '--expect-stock' not in sys.argv
    pad, name = find_gamepad()
    rig = Rig(pad, find_mouse(), grab='--live' not in sys.argv)
    print(f'controller: {name} ({pad}); expecting {"mouse" if expect_mouse else "stock"} mappings')
    failures = []

    def check(label, ok, detail):
        print(f'{"PASS" if ok else "FAIL"}  {label}: {detail}')
        if not ok:
            failures.append(label)

    try:
        for label, code, axis, sign in (
            ('right stick right', ABS_RX, REL_X, 1), ('right stick left', ABS_RX, REL_X, -1),
            ('right stick down', ABS_RY, REL_Y, 1), ('right stick up', ABS_RY, REL_Y, -1),
        ):
            events, quiet = rig.push(code, sign * rig.limit(code))
            moved, other = total(events, axis), total(events, REL_Y if axis == REL_X else REL_X)
            if expect_mouse:
                check(label, moved * sign > 100 and abs(other) < abs(moved) / 4 and not quiet,
                      f'moved {moved} (cross-axis {other}), {len(quiet)} events after release')
            else:
                check(label, not events, f'{len(events)} mouse events')
        events, _ = rig.push(ABS_X, rig.limit(ABS_X), 0.3)
        check('left stick leaves the mouse alone', not events, f'{len(events)} mouse events')
        got = buttons(rig.tap(EV_KEY, BTN_TR, 1))
        want = [(BTN_LEFT, 1), (BTN_LEFT, 0)] if expect_mouse else []
        check('R1 left click', got == want, got)
        got = buttons(rig.tap(EV_ABS, ABS_RZ, rig.limit(ABS_RZ)))
        want = [(BTN_RIGHT, 1), (BTN_RIGHT, 0)] if expect_mouse else []
        check('R2 right click', got == want, got)
        if expect_mouse:
            rig.read(0.1)
            rig.send(EV_KEY, BTN_TR, 1)
            events = rig.read(0.2)
            events += rig.push(ABS_RX, rig.limit(ABS_RX), 0.3)[0]
            rig.send(EV_KEY, BTN_TR, 0)
            events += rig.read(0.3)
            check('holding R1 while moving drags',
                  buttons(events) == [(BTN_LEFT, 1), (BTN_LEFT, 0)]
                  and events[0] == (EV_KEY, BTN_LEFT, 1) and events[-1] == (EV_KEY, BTN_LEFT, 0)
                  and total(events, REL_X) > 50,
                  f'{buttons(events)} around a move of {total(events, REL_X)}')
        got = buttons(rig.tap(EV_KEY, BTN_TL, 1)) + buttons(rig.tap(EV_ABS, ABS_Z, rig.limit(ABS_Z)))
        check('L1 and L2 do not click', not got, got)
    finally:
        for code in (ABS_X, ABS_Y, ABS_Z, ABS_RX, ABS_RY, ABS_RZ):
            rig.send(EV_ABS, code, 0)
        for code in (BTN_TL, BTN_TR):
            rig.send(EV_KEY, code, 0)
        rig.read(0.2)
        if rig.grabbed:
            fcntl.ioctl(rig.mouse, EVIOCGRAB, 0)
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()
