#!/usr/bin/env bash
# orion-wrapper.sh — symlinked to ~/.local/bin/orion.
# Activates the managed venv and execs the real orion CLI.

OPENORION_HOME="${OPENORION_HOME:-$HOME/.orion}"
VENV="$OPENORION_HOME/.venv"

if [[ ! -d "$VENV" ]]; then
    echo "orion: venv not found at $VENV" >&2
    echo "Re-run the installer: curl -fsSL https://orion.ai/install.sh | bash" >&2
    exit 1
fi

exec "$VENV/bin/orion" "$@"
