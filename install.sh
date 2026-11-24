#!/usr/bin/env bash
# Run on the handheld, as your normal user. Everything goes into your home
# directory: no sudo, no packages, no changes to the system image.
#
#   ./install.sh            install or upgrade
#   ./install.sh check      only check prerequisites
#   ./install.sh uninstall  remove, restoring the stock controller profile
set -euo pipefail

src=$(cd "$(dirname "$0")" && pwd)/src
config=${XDG_CONFIG_HOME:-$HOME/.config}
data=${XDG_DATA_HOME:-$HOME/.local/share}
program=$HOME/.local/bin/pad-mouse
mappings=$config/pad-mouse/mappings.yaml
unit=$config/systemd/user/pad-mouse.service
launcher=$data/applications/pad-mouse-toggle.desktop
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}

die() { echo "pad-mouse: $*" >&2; exit 1; }

check() {
    [[ $EUID -ne 0 ]] || die 'run as your normal user, not root'
    command -v busctl >/dev/null || die 'busctl (systemd) is required'
    python3 -c 'import yaml' 2>/dev/null || die 'python3 with PyYAML is required (Armada ships both)'
    busctl --system status org.shadowblip.InputPlumber >/dev/null 2>&1 \
        || die 'InputPlumber is not running (Armada ships and starts it)'
    # InputPlumber's polkit rule lets these groups load profiles without a password.
    id -nG | tr ' ' '\n' | grep -qxE 'wheel|inputplumber' \
        || die "user $(id -un) must be in the wheel or inputplumber group"
    echo 'Prerequisites OK.'
}

install_all() {
    check
    install -Dm755 "$src/pad-mouse" "$program"
    if [[ -e $mappings ]]; then
        cmp -s "$src/mappings.yaml" "$mappings" || echo "Keeping your edited $mappings"
    else
        install -Dm644 "$src/mappings.yaml" "$mappings"
    fi
    install -Dm644 "$src/pad-mouse.service" "$unit"
    mkdir -p "$(dirname "$launcher")"
    sed "s|@HOME@|$HOME|g" "$src/pad-mouse-toggle.desktop" > "$launcher"
    systemctl --user daemon-reload
    systemctl --user enable --quiet pad-mouse.service
    systemctl --user restart pad-mouse.service
    sleep 3
    "$program" status
}

uninstall() {
    # Stopping the service runs ExecStopPost, which restores the previous profile.
    systemctl --user disable --now --quiet pad-mouse.service 2>/dev/null || true
    [[ ! -x $program ]] || "$program" restore || true
    if [[ -e $mappings ]] && cmp -s "$src/mappings.yaml" "$mappings"; then
        rm -f "$mappings"
        rmdir "$config/pad-mouse" 2>/dev/null || true
    elif [[ -e $mappings ]]; then
        echo "Left your edited $mappings in place."
    fi
    rm -f "$program" "$unit" "$launcher" "$XDG_RUNTIME_DIR"/pad-mouse/{off,lock,previous.json}
    rmdir "$XDG_RUNTIME_DIR/pad-mouse" 2>/dev/null || true
    systemctl --user daemon-reload
    echo 'Removed.'
}

case ${1:-install} in
    install) install_all ;;
    check) check ;;
    uninstall) uninstall ;;
    *) die "usage: $0 [install|check|uninstall]" ;;
esac
