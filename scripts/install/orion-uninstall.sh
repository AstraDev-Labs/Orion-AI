#!/usr/bin/env bash
# orion-uninstall.sh — clean removal of Orion from $HOME.
#
# Removes:
#   ~/.orion/
#   ~/.local/bin/orion
#   ~/.local/bin/orion-uninstall
#
# Does NOT remove: ollama, uv, or the Rust toolchain.

set -euo pipefail

OPENORION_HOME="${OPENORION_HOME:-$HOME/.orion}"

if [[ -f "$OPENORION_HOME/.state/bg.pid" ]]; then
    pid=$(cat "$OPENORION_HOME/.state/bg.pid" 2>/dev/null || echo "")
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
        echo "Stopping background work (pid=$pid)..."
        kill "$pid" 2>/dev/null || true
    fi
fi

if command -v ollama >/dev/null 2>&1; then
    ollama stop >/dev/null 2>&1 || true
fi

if [[ -d "$OPENORION_HOME" ]]; then
    rm -rf "$OPENORION_HOME"
    echo "Removed $OPENORION_HOME"
fi

for f in "$HOME/.local/bin/orion" "$HOME/.local/bin/orion-uninstall"; do
    if [[ -L "$f" ]] || [[ -f "$f" ]]; then
        rm -f "$f"
        echo "Removed $f"
    fi
done

cat <<EOF

Orion removed.

Left intact (may be used by other tools):
  - Ollama       (uninstall: brew uninstall ollama  /  rm -f /usr/local/bin/ollama)
  - uv           (uninstall: rm -rf ~/.local/share/uv ~/.cargo/bin/uv)
  - Rust toolchain (uninstall: rustup self uninstall)
EOF
