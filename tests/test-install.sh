#!/bin/bash
# Installer regression: grep -- patterns, idempotent managed blocks, no "unknown".
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export HOME="$TMP/home"
export XDG_CONFIG_HOME="$HOME/.config"
mkdir -p "$HOME/.config/hypr" "$HOME/.config/omarchy/extensions" "$HOME/bin"

# Fake helpers that reproduce the stray `unknown` the real Omarchy IPC prints
# when `omarchy menu refresh` is not a registered method.
cat >"$HOME/bin/omarchy" <<'EOF'
#!/bin/bash
echo unknown
exit 0
EOF
cat >"$HOME/bin/hyprctl" <<'EOF'
#!/bin/bash
echo unknown
exit 0
EOF
chmod +x "$HOME/bin/omarchy" "$HOME/bin/hyprctl"
export PATH="$HOME/bin:$PATH"

# Existing Hyprland Lua + a GFN-owned menu file (shared gaming root).
cat >"$HOME/.config/hypr/hyprland.lua" <<'EOF'
-- user hyprland
require("user.bindings")
EOF

cat >"$HOME/.config/omarchy/extensions/omarchy-menu.jsonc" <<'EOF'
{
  "gaming": {
    "icon": "x",
    "label": "Gaming"
  },
  "gaming.geforce-now.search": {
    "label": "Search GeForce NOW"
  }
}
EOF

count_matches() {
  local file="$1" pat="$2"
  grep -Fc -e "$pat" -- "$file" || true
}

echo "---- first install ----"
out1="$TMP/install1.out"
bash "$ROOT/scripts/install.sh" >"$out1" 2>"$TMP/install1.err" || {
  echo "install.sh failed:" >&2
  cat "$TMP/install1.err" >&2
  cat "$out1" >&2
  exit 1
}

if grep -q 'unrecognized option' "$TMP/install1.err" "$out1"; then
  echo "grep treated BEGIN marker as an option" >&2
  cat "$TMP/install1.err" "$out1" >&2
  exit 1
fi
if grep -qx 'unknown' "$out1" || grep -qx 'unknown' "$TMP/install1.err"; then
  echo "stray 'unknown' leaked from omarchy/hyprctl" >&2
  cat "$out1" "$TMP/install1.err" >&2
  exit 1
fi

[[ -f "$HOME/.config/hypr/arcade.lua" ]] || { echo "missing arcade.lua" >&2; exit 1; }
grep -Fq -- '-- BEGIN matt-dance.arcade' "$HOME/.config/hypr/hyprland.lua" \
  || { echo "missing hypr managed block" >&2; exit 1; }
grep -Fq -- '// BEGIN matt-dance.arcade' "$HOME/.config/omarchy/extensions/omarchy-menu.jsonc" \
  || { echo "missing menu managed block" >&2; exit 1; }
# Reused the existing gaming root instead of rewriting it.
[[ "$(count_matches "$HOME/.config/omarchy/extensions/omarchy-menu.jsonc" '"gaming"')" -eq 1 ]] \
  || { echo "gaming root was duplicated" >&2; exit 1; }

echo "---- second install (must stay idempotent) ----"
bash "$ROOT/scripts/install.sh" >"$TMP/install2.out" 2>"$TMP/install2.err"

[[ "$(count_matches "$HOME/.config/hypr/hyprland.lua" '-- BEGIN matt-dance.arcade')" -eq 1 ]] \
  || { echo "duplicate hypr BEGIN block after reinstall" >&2; exit 1; }
[[ "$(count_matches "$HOME/.config/hypr/hyprland.lua" '-- END matt-dance.arcade')" -eq 1 ]] \
  || { echo "duplicate hypr END block after reinstall" >&2; exit 1; }
[[ "$(count_matches "$HOME/.config/omarchy/extensions/omarchy-menu.jsonc" '// BEGIN matt-dance.arcade')" -eq 1 ]] \
  || { echo "duplicate menu BEGIN block after reinstall" >&2; exit 1; }
[[ "$(count_matches "$HOME/.config/hypr/arcade.lua" 'SUPER + CTRL + G')" -eq 1 ]] \
  || { echo "arcade.lua bind missing or duplicated" >&2; exit 1; }
if grep -q 'unrecognized option' "$TMP/install2.err" "$TMP/install2.out"; then
  echo "reinstall grep option error" >&2
  cat "$TMP/install2.err" "$TMP/install2.out" >&2
  exit 1
fi
if grep -qx 'unknown' "$TMP/install2.out" || grep -qx 'unknown' "$TMP/install2.err"; then
  echo "stray 'unknown' leaked on reinstall" >&2
  exit 1
fi

echo "---- uninstall ----"
bash "$ROOT/scripts/uninstall.sh" >"$TMP/un.out" 2>"$TMP/un.err"
if grep -Fq -- '-- BEGIN matt-dance.arcade' "$HOME/.config/hypr/hyprland.lua"; then
  echo "uninstall left hypr managed block" >&2
  exit 1
fi
if grep -Fq -- '// BEGIN matt-dance.arcade' "$HOME/.config/omarchy/extensions/omarchy-menu.jsonc"; then
  echo "uninstall left menu managed block" >&2
  exit 1
fi
[[ ! -f "$HOME/.config/hypr/arcade.lua" ]] || { echo "arcade.lua not removed" >&2; exit 1; }

echo "install.sh / uninstall.sh ok"
