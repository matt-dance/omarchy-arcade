#!/bin/bash
# Remove Omarchy Arcade integration written by scripts/install.sh.
# Does not remove the plugin checkout — use: omarchy plugin remove matt-dance.arcade

set -euo pipefail

PLUGIN_ID="matt-dance.arcade"
BEGIN_MARK="// BEGIN ${PLUGIN_ID}"
END_MARK="// END ${PLUGIN_ID}"
HYPR_BEGIN="-- BEGIN ${PLUGIN_ID}"
HYPR_END="-- END ${PLUGIN_ID}"
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) echo "Usage: uninstall.sh [--dry-run]"; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

# Patterns such as `-- BEGIN matt-dance.arcade` start with `--`.
file_contains() {
  local file="$1" pat="$2"
  [[ -f "$file" ]] && grep -Fq -- "$pat" "$file"
}

strip_block() {
  local file="$1" begin="$2" end="$3"
  [[ -f "$file" ]] || return 0
  if ! file_contains "$file" "$begin"; then
    echo "no managed block in ${file}"
    return 0
  fi
  if (( DRY_RUN )); then
    echo "would strip managed block from ${file}"
    return 0
  fi
  local bak tmp
  bak="${file}.bak.$(date +%Y%m%d%H%M%S)"
  cp -a "$file" "$bak"
  tmp="$(mktemp)"
  awk -v begin="$begin" -v end="$end" '
    $0 ~ begin { skip=1; next }
    $0 ~ end { skip=0; next }
    !skip { print }
  ' "$file" >"$tmp"
  mv "$tmp" "$file"
  echo "stripped ${file} (backup ${bak})"
}

HYPR="${XDG_CONFIG_HOME:-$HOME/.config}/hypr/hyprland.lua"
MENU="${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/extensions/omarchy-menu.jsonc"
ARCADE_LUA="${XDG_CONFIG_HOME:-$HOME/.config}/hypr/arcade.lua"

strip_block "$HYPR" "$HYPR_BEGIN" "$HYPR_END"
strip_block "$MENU" "$BEGIN_MARK" "$END_MARK"

if [[ -f "$ARCADE_LUA" ]]; then
  if (( DRY_RUN )); then
    echo "would remove ${ARCADE_LUA}"
  else
    rm -f "$ARCADE_LUA"
    echo "removed ${ARCADE_LUA}"
  fi
fi

if (( ! DRY_RUN )); then
  if command -v omarchy >/dev/null 2>&1; then
    omarchy menu refresh >/dev/null 2>&1 || true
  fi
  if command -v hyprctl >/dev/null 2>&1; then
    hyprctl reload >/dev/null 2>&1 || true
  fi
  echo "Integration removed. Plugin files (if any) remain until: omarchy plugin remove ${PLUGIN_ID}"
fi
