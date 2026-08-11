#!/usr/bin/env bash
# Installs obiobi into its own venv and puts `obiobi` on your PATH.
#   ./install.sh              # auto: uses ollama if present, else a local gguf
#   ./install.sh heuristic    # no model at all (rule-based, instant)
#   ./install.sh ollama|llama-cpp
set -euo pipefail

BACKEND="${1:-auto}"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIX="${OBIOBI_HOME:-$HOME/.local/share/obiobi}"
VENV="$PREFIX/venv"
BIN="${OBIOBI_BIN:-$HOME/.local/bin}"

command -v python3 >/dev/null || { echo "python3 is required"; exit 1; }

echo ":: creating venv at $VENV"
mkdir -p "$PREFIX" "$BIN"
python3 -m venv "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip
echo ":: installing obiobi"
"$VENV/bin/pip" install --quiet "$SRC"

cat > "$BIN/obiobi" <<EOF
#!/usr/bin/env bash
exec "$VENV/bin/python" -m obiobi "\$@"
EOF
chmod +x "$BIN/obiobi"

echo ":: fetching the model"
"$VENV/bin/python" -m obiobi install --backend "$BACKEND" || true

case ":$PATH:" in
  *":$BIN:"*) ;;
  *) echo ":: add this to your shell rc:  export PATH=\"$BIN:\$PATH\"" ;;
esac
echo ":: done - run: obiobi"
