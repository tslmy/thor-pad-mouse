# thor-pad-mouse

Use the built-in controls of an **AYN Thor running [ArmadaOS](https://github.com/armada-os/armada)**
as a mouse in desktop sessions, like a ROG Ally in desktop mode.

| Control | Does |
| --- | --- |
| Right stick | Moves the cursor |
| R1 | Left button (hold it to drag) |
| R2 | Right button |

Every other control keeps its normal mapping, and Gaming Mode is left alone.
It works in Plasma Desktop Mode and in the ReactOS, Windows XP and Windows 7
shells from [thor-win4wine](https://github.com/tslmy/thor-win4wine).

## Install

On the handheld (Konsole or SSH):

```bash
git clone https://github.com/tslmy/thor-pad-mouse
cd thor-pad-mouse
./install.sh
```

Or from a computer with SSH access and [`just`](https://github.com/casey/just):

```bash
export THOR_HOST=your-thor THOR_USER=your-login   # and THOR_SSH_KEY if needed
just install
```

No sudo, packages or system-image changes: everything goes into your home
directory. Your user must be in the `wheel` or `inputplumber` group (the default
Armada user is). `./install.sh uninstall` or `just uninstall` removes it and
restores the previous controller profile.

## Use

- Start a desktop session and the mouse works within a few seconds. Gaming Mode
  gets the normal controller back.
- **Playing an emulator or game in desktop mode?** Run *Toggle Controller Mouse*
  from the application menu (in the Windows-style shells, from the Linux
  programs menu), or run `~/.local/bin/pad-mouse off` (and `on`). This is not
  remembered across reboots.
- Cursor speed and mappings are in `~/.config/pad-mouse/mappings.yaml`
  (`speed_pps`, default 800). Apply edits with
  `systemctl --user restart pad-mouse`.
- Troubleshooting: `~/.local/bin/pad-mouse status` and
  `journalctl --user -u pad-mouse`.

## How it works

[InputPlumber](https://github.com/ShadowBlip/InputPlumber), which Armada already
runs, owns the controller and can drive a virtual mouse. `pad-mouse` is a small
user service that decides *when*:

- A desktop compositor (`kwin_wayland` or `labwc`) is running and no `gamescope`
  is: add the three mappings in [`src/mappings.yaml`](src/mappings.yaml) on top
  of whatever InputPlumber profile is active.
- Otherwise: put the previous profile back.

The result is a kernel input device, so any compositor, and Wine inside it, sees
an ordinary mouse. The mappings are reapplied if InputPlumber restarts (Armada
restarts it for gyro and calibration changes). The service used about 0.6% of
one CPU core on the Thor.

While mouse mode is on, the right stick, R1 and R2 do not reach the virtual
gamepad, so Steam started in desktop mode will not see them either.

## Why not an existing tool?

As of November 2026:

- ArmadaOS has no desktop-mode mouse of its own
  ([armada#22](https://github.com/armada-os/armada/issues/22) is open). With
  the Thor's default controller type, desktop mode sees a virtual Steam Deck
  pad, and without Steam running nothing turns it into a cursor.
- Steam's desktop layout needs Steam running, which the Windows-style shells do
  not do.
- InputPlumber's bundled `mouse_keyboard_wasd` profile uses other buttons, turns
  the rest of the pad into keyboard keys, and stays loaded in Gaming Mode.
- [armada-controller-remapper](https://github.com/mrdidit/armada-controller-remapper)
  does not edit stick movement;
  [armada-trackpad-daemon](https://github.com/nikitautiu/armada-trackpad-daemon)
  is about the touchscreen.

So the translation itself is off the shelf (InputPlumber configuration). Only
the switching between sessions is new.

## Tests

```bash
just check            # unit tests, no handheld needed
just test             # on the handheld: fake input in, virtual mouse out
just test-shell xp    # or reactos, win7 (needs thor-win4wine)
```

Run the last two while a desktop session is in mouse mode. `just test` and
`just test-shell` write fake events into the controller's device
node, so they need sudo and you should not touch the controls while they run.
`test-shell` runs the shell's own labwc headless but with real libinput; your
session is not switched, and a full-screen window shields the desktop from the
test clicks.

### What has been verified

AYN Thor, Armada `20261109.dfed5d6`, InputPlumber 0.83.0, 24 November 2026:

- Cursor directions, both buttons, nothing from the left-hand controls, and
  nothing at all when switched off.
- A Plasma application received the movement and clicks.
- ReactOS, XP and Win7: the stick steered the cursor, R1 opened and closed the
  Start menu, and R2 opened the desktop context menu.
- Service: off/on, profile reset, InputPlumber restart, service stop, and a
  stand-in `gamescope` process.

**Not yet verified:** a human thumb on the real controls (tests inject events at
the device node), the shells on the physical screen after a real session switch,
a real switch to Gaming Mode, suspend/resume, and other handhelds.

Known quirk: in the XP shell, after a desktop right-click menu is dismissed, the
Start button ignores the next click (click again). Synthetic X11 clicks hit the
same thing, so it is not caused by this mapping.

## Other handhelds and desktops

Nothing here should be specific to the Thor beyond what InputPlumber calls the
controller, but only the Thor has been tried. The controller is matched against
the device-tree model name, falling back to the first one with a right stick, R1
and R2. To override either choice, run `systemctl --user edit pad-mouse`:

```ini
[Service]
Environment=PAD_MOUSE_DEVICE=AYN Thor
Environment="PAD_MOUSE_COMPOSITORS=kwin_wayland labwc"
```
