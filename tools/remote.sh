#!/usr/bin/env bash
# ssh to the handheld using THOR_HOST, THOR_USER and THOR_SSH_KEY.
set -euo pipefail
: "${THOR_HOST:?set THOR_HOST to the handheld, and optionally THOR_USER and THOR_SSH_KEY}"
options=(-o ConnectTimeout=10)
[[ -z ${THOR_SSH_KEY:-} ]] || options+=(-i "$THOR_SSH_KEY")
# A terminal lets sudo ask for its password; piped uploads must not get one.
[[ ! -t 0 ]] || options+=(-t)
exec ssh "${options[@]}" "${THOR_USER:+$THOR_USER@}$THOR_HOST" "$@"
