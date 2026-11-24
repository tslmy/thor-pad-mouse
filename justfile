set shell := ["bash", "-euo", "pipefail", "-c"]

# Run these from a computer with SSH access to the handheld. Set THOR_HOST and,
# if needed, THOR_USER and THOR_SSH_KEY. On the handheld itself: ./install.sh

default:
    @just --list

# Unit tests and syntax checks. Needs no handheld.
check:
    python3 -B -m unittest discover -s tests -v
    bash -n install.sh tools/remote.sh
    python3 -B -c 'import ast, sys; [ast.parse(open(f).read(), f) for f in sys.argv[1:]]' src/pad-mouse tools/device-test.py tools/test-win4wine.py

_upload:
    COPYFILE_DISABLE=1 tar --no-xattrs --exclude=__pycache__ -cf - install.sh src tools tests | tools/remote.sh 'rm -rf ~/.local/share/pad-mouse && mkdir -p ~/.local/share/pad-mouse && tar -xf - -C ~/.local/share/pad-mouse'

# Read-only prerequisite check.
doctor: _upload
    tools/remote.sh '~/.local/share/pad-mouse/install.sh check'

# Install or upgrade, then start. No sudo, no packages.
install: _upload
    tools/remote.sh '~/.local/share/pad-mouse/install.sh'

# Remove, restoring the previous controller profile.
uninstall: _upload
    tools/remote.sh '~/.local/share/pad-mouse/install.sh uninstall && rm -rf ~/.local/share/pad-mouse'

# What is active right now.
status:
    tools/remote.sh '~/.local/bin/pad-mouse status'

# Controller as mouse again (the default in desktop sessions).
on:
    tools/remote.sh '~/.local/bin/pad-mouse on'

# Controller as gamepad until switched back or rebooted.
off:
    tools/remote.sh '~/.local/bin/pad-mouse off'

toggle:
    tools/remote.sh '~/.local/bin/pad-mouse toggle'

logs:
    tools/remote.sh 'journalctl --user -u pad-mouse -n 50 --no-pager'

# Fake stick and button input, check the virtual mouse. Uses sudo; hands off.
test: _upload
    tools/remote.sh 'sudo python3 -B ~/.local/share/pad-mouse/tools/device-test.py'

# Drive a thor-win4wine shell headless: reactos, xp or win7. Uses sudo; hands off.
test-shell shell: _upload
    tools/remote.sh "sudo python3 -B .local/share/pad-mouse/tools/test-win4wine.py {{quote(shell)}}"
