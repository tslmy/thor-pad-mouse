#!/usr/bin/env python3
"""Check that the controller drives a win4wine shell, without touching the screen.

    sudo python3 tools/test-win4wine.py reactos|xp|win7 [screenshot-dir]

Needs github.com/tslmy/thor-win4wine installed, its shells not currently in use,
and pad-mouse active. The shell's own labwc runs headless but with real
libinput, so InputPlumber's virtual mouse reaches it as it would on the panel.
Fake stick and button input then has to move the cursor and open and close
Wine's menus. Your logged-in session stays where it is.

The host desktop sees the same mouse, so a full-screen window covers it for the
duration; do not touch the controls while this runs.
"""
import importlib.util
import json
import math
import os
from pathlib import Path
import pwd
import shutil
import signal
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
SHELLS = ('reactos', 'xp', 'win7')


def load_device_test():
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location('device_test', HERE / 'device-test.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- root: private seat, then drop to the user ------------------------------

def private_run(user_run):
    """Give this process tree its own /run, so a second seatd can exist."""
    def mount(*args):
        subprocess.run(['mount', *args], check=True)

    os.unshare(os.CLONE_NEWNS)
    mount('--make-rprivate', '/')
    real = tempfile.mkdtemp(prefix='pad-mouse-run-')
    mount('--rbind', '/run', real)
    mount('-t', 'tmpfs', '-o', 'mode=755', 'tmpfs', '/run')
    for name in ('udev', 'user', 'dbus', 'systemd'):
        os.mkdir(f'/run/{name}')
        mount('--rbind', f'{real}/{name}', f'/run/{name}')
    try:
        user_run()
    finally:
        subprocess.run(['umount', '-R', '-l', real], check=False)
        os.rmdir(real)  # only ever removes the empty mount point


def as_root(shell, shots):
    if os.geteuid() != 0 or not os.environ.get('SUDO_USER'):
        sys.exit('Run with sudo from your normal account.')
    user = pwd.getpwnam(os.environ['SUDO_USER'])
    pad_device, _ = load_device_test().find_gamepad()
    mouse_device = load_device_test().find_mouse()
    # Opened as root, used by the unprivileged test below.
    pad = os.open(pad_device, os.O_RDWR)
    mouse = os.open(mouse_device, os.O_RDONLY | os.O_NONBLOCK)
    home = Path(user.pw_dir)
    base = home / '.local/share/win4wine'
    env = {
        'HOME': str(home), 'USER': user.pw_name, 'LOGNAME': user.pw_name,
        'XDG_RUNTIME_DIR': f'/run/user/{user.pw_uid}',
        'PATH': f'{home}/.local/bin:/usr/local/bin:/usr/bin:{base}/rootfs/usr/bin',
        'PYTHONPATH': str(base / 'python'), 'FEX_ROOTFS': str(base / 'rootfs'),
        'LD_LIBRARY_PATH': str(base / 'labwc/lib'),
        'LANG': 'en_US.UTF-8', 'LC_ALL': 'en_US.UTF-8',
    }
    identity = {'user': user.pw_uid, 'group': user.pw_gid,
                'extra_groups': os.getgrouplist(user.pw_name, user.pw_gid)}

    def run():
        seatd = subprocess.Popen(['seatd', '-u', user.pw_name, '-l', 'error'],
                                 env=dict(os.environ, SEATD_VTBOUND='0'))
        try:
            for _ in range(50):
                if Path('/run/seatd.sock').is_socket():
                    break
                time.sleep(.1)
            result = subprocess.run(
                [sys.executable, '-B', __file__, '--as-user', str(pad), str(mouse), shell, shots],
                env=env, pass_fds=(pad, mouse), cwd=home, **identity)
        finally:
            seatd.terminate()
            seatd.wait(timeout=10)
        if result.returncode:
            sys.exit(result.returncode)

    private_run(run)


# --- user: the shell itself -------------------------------------------------

def wait(predicate, label, seconds=150):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            value = predicate()
            if value:
                return value
        except (OSError, ValueError):
            pass
        time.sleep(.1)
    raise RuntimeError(f'timed out waiting for {label}')


def host_shield():
    """Full-screen window on the host desktop to absorb the test clicks."""
    manager = subprocess.run(['systemctl', '--user', 'show-environment'],
                             capture_output=True, text=True).stdout
    host = dict(line.split('=', 1) for line in manager.splitlines() if '=' in line)
    if not host.get('WAYLAND_DISPLAY') or not Path(
            os.environ['XDG_RUNTIME_DIR'], host['WAYLAND_DISPLAY']).is_socket():
        print('note: no host Wayland desktop found to shield')
        return None
    code = ('import gi; gi.require_version("Gtk","3.0"); from gi.repository import Gtk\n'
            'w=Gtk.Window(); w.add(Gtk.Label(label="pad-mouse test running: please do not touch"))\n'
            'w.add_events(256|512); w.connect("button-press-event", lambda *a: True)\n'
            'w.fullscreen(); w.show_all(); w.present(); Gtk.main()\n')
    env = dict(os.environ, WAYLAND_DISPLAY=host['WAYLAND_DISPLAY'], GDK_BACKEND='wayland')
    env.pop('LD_LIBRARY_PATH', None)
    env.pop('PYTHONPATH', None)
    process = subprocess.Popen([sys.executable, '-c', code], env=env)
    time.sleep(3)
    return process


def as_user(pad_fd, mouse_fd, shell, shots):
    from Xlib import X, display, error

    pad = load_device_test()
    home = Path.home()
    root_dir = home / 'win4wine'
    base = home / '.local/share/win4wine'
    config = json.loads((home / f'.config/win4wine/{shell}-standalone.json').read_text())
    wineserver = str(Path(config['wine']).with_name('wineserver'))
    prefix_env = dict(os.environ, WINEPREFIX=config['prefix'])
    try:
        subprocess.run([wineserver, '-w'], env=prefix_env, check=True, timeout=2,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        sys.exit(f'The {shell} prefix is in use. Log off that shell first.')
    sys.path.insert(0, str(root_dir / 'session'))
    from wineenv import SHELLS as WINE_SHELLS, environment

    rig = pad.Rig.__new__(pad.Rig)
    rig.pad, rig.mouse, rig.grabbed = pad_fd, mouse_fd, False
    failures = []

    def check(label, ok, detail=''):
        print(f'{"PASS" if ok else "FAIL"}  {shell}: {label} {detail}', flush=True)
        if not ok:
            failures.append(label)

    log_path = home / f'.local/state/pad-mouse-test-{shell}.log'
    shield = host_shield()
    work = Path(tempfile.mkdtemp(prefix='pad-mouse-shell-', dir=os.environ['XDG_RUNTIME_DIR']))
    process = connection = None
    try:
        runtime, ipc, state = (work / name for name in ('runtime', 'ipc', 'state'))
        for directory in (runtime, ipc, state):
            directory.mkdir(mode=0o700)
        test_config = dict(config, state=str(state), primary='HEADLESS-1', welcome_screen=False)
        session = work / 'session.json'
        session.write_text(json.dumps(test_config))
        displays = work / 'displays'
        startup = work / 'startup.sh'
        startup.write_text(
            f'#!/bin/sh\npython3 "{base}/tools/configure-win4wine-outputs.py" --test-output HEADLESS-1 || exit $?\n'
            f'printf "%s %s\\n" "$DISPLAY" "$WAYLAND_DISPLAY" > "{displays}"\n'
            f'exec python3 "{root_dir}/session/supervisor.py" --config "{session}"\n')
        startup.chmod(0o755)
        env = dict(os.environ, XDG_RUNTIME_DIR=str(runtime), WIN4WINE_IPC=str(ipc),
                   LIBSEAT_BACKEND='seatd', WLR_BACKENDS='headless,libinput',
                   WLR_HEADLESS_OUTPUTS='1', WLR_RENDERER='pixman', WLR_NO_HARDWARE_CURSORS='1',
                   XCURSOR_THEME=f'win4wine-{shell}', XCURSOR_SIZE='32',
                   # Silence the startup chime.
                   PULSE_SERVER='unix:/nonexistent', ALSA_CONFIG_PATH='/dev/null')
        with log_path.open('w') as log:
            process = subprocess.Popen(
                ['dbus-run-session', '--', str(base / 'labwc/bin/labwc'), '-V',
                 '-C', str(base / 'labwc-config'), '-S', str(startup)],
                env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        x_name, wayland_name = wait(lambda: displays.read_text().split(), 'Xwayland')
        wait(lambda: json.loads((state / 'status.json').read_text()).get('state') == 'xp-shell', 'shell')
        connection = display.Display(x_name)
        screen = connection.screen()
        width, height = screen.width_in_pixels, screen.height_in_pixels

        def viewable():
            found = {}
            for window in screen.root.query_tree().children:
                try:
                    if window.get_attributes().map_state == X.IsViewable:
                        box = window.get_geometry()
                        kind = window.get_full_property(
                            connection.intern_atom('_WIN4WINE_CLASS'), X.AnyPropertyType)
                        name = bytes(kind.value).rstrip(b'\0').decode(errors='replace') if kind else ''
                        if box.width > 60 and box.height > 60:
                            found[window.id] = name
                except error.XError:
                    pass
            return found

        def pointer():
            reply = screen.root.query_pointer()
            return reply.root_x, reply.root_y

        wait(lambda: 'Progman' in viewable().values(), 'desktop')
        time.sleep(12)  # let start-up windows and balloons settle

        def steer(x, y, tolerance=9, seconds=30):
            """Closed loop on the right stick until the cursor is there."""
            limit = rig.limit(pad.ABS_RX)

            def deflect(distance):
                if abs(distance) <= tolerance:
                    return 0
                amount = .24 if abs(distance) < 40 else .4 if abs(distance) < 120 else .8
                return int(math.copysign(amount * limit, distance))

            deadline = time.monotonic() + seconds
            try:
                while time.monotonic() < deadline:
                    now_x, now_y = pointer()
                    stick = deflect(x - now_x), deflect(y - now_y)
                    if stick == (0, 0):
                        return True
                    until = time.monotonic() + .03
                    while time.monotonic() < until:
                        rig.send(pad.EV_ABS, pad.ABS_RX, stick[0])
                        rig.send(pad.EV_ABS, pad.ABS_RY, stick[1])
                        rig.read(.0005)
                return False
            finally:
                rig.send(pad.EV_ABS, pad.ABS_RX, 0)
                rig.send(pad.EV_ABS, pad.ABS_RY, 0)
                rig.read(.3)

        def click(kind, code, down):
            rig.send(kind, code, down)
            rig.read(.08)
            rig.send(kind, code, 0)
            rig.read(.2)

        def left():
            click(pad.EV_KEY, pad.BTN_TR, 1)

        def right():
            click(pad.EV_ABS, pad.ABS_RZ, rig.limit(pad.ABS_RZ))

        def appeared(before, seconds=8):
            try:
                return wait(lambda: set(viewable()) - set(before), 'a window', seconds)
            except RuntimeError:
                return set()

        def gone(windows, seconds=8):
            try:
                return wait(lambda: not windows & set(viewable()), 'close', seconds)
            except RuntimeError:
                return False

        def shot(name):
            if shots:
                subprocess.run([str(base / 'tools/grim'), '-c', f'{shots}/{shell}-{name}.png'],
                               env=dict(env, WAYLAND_DISPLAY=wayland_name), check=False, timeout=30)

        empty = int(width * .55), int(height * .3)
        away = int(width * .35), int(height * .2)
        check('right stick moves the cursor', steer(*empty), f'at {pointer()} of {width}x{height}')

        # Start menu first: after a context menu has been dismissed, XP's own
        # Start button ignores the next click, however the click is made.
        check('right stick reaches the Start button', steer(24, height - 12, tolerance=10), f'at {pointer()}')
        before = viewable()
        left()
        start = appeared(before)
        time.sleep(2)
        check('R1 on Start opens the Start menu', bool(start), sorted(viewable().get(i, '') for i in start))
        shot('r1-start-menu')
        steer(*empty)
        left()
        check('R1 on the desktop closes the Start menu', bool(start) and gone(start))
        time.sleep(1)

        before = viewable()
        right()
        menu = appeared(before)
        time.sleep(1)
        check('R2 opens the desktop context menu', bool(menu), sorted(viewable().get(i, '') for i in menu))
        shot('r2-context-menu')
        steer(*away)
        left()
        check('R1 elsewhere closes it', bool(menu) and gone(menu))

        wine_env = environment(dict(env, DISPLAY=x_name, WINEDEBUG='-all'), test_config, WINE_SHELLS[shell])
        wine_env['WIN4WINE_SESSION_REQUEST'] = 'Z:' + str(state / 'session-request').replace('/', '\\')
        with log_path.open('a') as log:
            subprocess.run([config['wine'], str(root_dir / '.local/bridge/exit-windows-test.exe'), 'logoff'],
                           env=wine_env, check=False, timeout=60, stdout=log, stderr=log)
        wait(lambda: json.loads((state / 'status.json').read_text()).get('state') == 'stopped', 'logoff', 90)
    finally:
        if connection:
            try:
                connection.close()
            except error.ConnectionClosedError:
                pass
        if process:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            process.wait(timeout=30)
            # Only this prefix, verified idle before we started it.
            subprocess.run([wineserver, '-k'], env=prefix_env, check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if shield:
            shield.terminate()
        shutil.rmtree(work, ignore_errors=True)
    sys.exit(1 if failures else 0)


def main():
    if len(sys.argv) == 6 and sys.argv[1] == '--as-user':
        as_user(int(sys.argv[2]), int(sys.argv[3]), sys.argv[4], sys.argv[5])
    elif len(sys.argv) in (2, 3) and sys.argv[1] in SHELLS:
        shots = str(Path(sys.argv[2]).resolve()) if len(sys.argv) == 3 else ''
        as_root(sys.argv[1], shots)
    else:
        sys.exit(__doc__)


if __name__ == '__main__':
    main()
