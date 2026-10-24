#!/bin/bash
# Install Omarchy Arcade integration (Hyprland bind + Gaming menu rows).
# `omarchy plugin add` does not run this — call it after enable.
#
# Usage:
#   scripts/install.sh [--dry-run]
#
# Idempotent. Backs up changed files to *.bak.<timestamp>.

set -euo pipefail

PLUGIN_ID="matt-dance.arcade"
BEGIN_MARK="// BEGIN ${PLUGIN_ID}"
END_MARK="// END ${PLUGIN_ID}"
HYPR_BEGIN="-- BEGIN ${PLUGIN_ID}"
HYPR_END="-- END ${PLUGIN_ID}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help)
      sed -n '2,10p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

die() { echo "error: $*" >&2; exit 1; }

# Patterns such as `-- BEGIN matt-dance.arcade` start with `--`. Without this,
# GNU grep treats the pattern as an option (`grep: unrecognized option '-- BEGIN …'`).
file_contains() {
  local file="$1" pat="$2"
  [[ -f "$file" ]] && grep -Fq -- "$pat" "$file"
}

refresh_integrations() {
  # `omarchy menu refresh` is documented but often missing as an IPC method;
  # on a real host it prints a bare `unknown` to stdout. Swallow that.
  if command -v omarchy >/dev/null 2>&1; then
    omarchy menu refresh >/dev/null 2>&1 || true
  fi
  if command -v hyprctl >/dev/null 2>&1; then
    hyprctl reload >/dev/null 2>&1 || true
  fi
}

backup() {
  local file="$1"
  local bak="${file}.bak.$(date +%Y%m%d%H%M%S)"
  if (( DRY_RUN )); then
    echo "would backup ${file} -> ${bak}"
    return
  fi
  cp -a "$file" "$bak"
  echo "backup: ${bak}"
}

write_file() {
  local file="$1"
  local content="$2"
  if (( DRY_RUN )); then
    echo "---- would write ${file} ----"
    printf '%s' "$content"
    echo "---- end ----"
    return
  fi
  mkdir -p "$(dirname "$file")"
  if [[ -f "$file" ]]; then
    backup "$file"
  fi
  printf '%s' "$content" >"$file"
  echo "wrote ${file}"
}

# --- Hyprland bind ----------------------------------------------------------

install_hypr() {
  local src="${REPO_ROOT}/hypr/arcade.lua"
  local dest="${XDG_CONFIG_HOME:-$HOME/.config}/hypr/arcade.lua"
  local hyprland="${XDG_CONFIG_HOME:-$HOME/.config}/hypr/hyprland.lua"
  [[ -f "$src" ]] || die "missing ${src}"

  write_file "$dest" "$(cat "$src")"$'\n'

  local require_line='require("default.hypr.require_optional").module("hypr.arcade")'
  # Fallback if require_optional API differs — also accept a plain dofile
  local require_block
  require_block=$(cat <<EOF
${HYPR_BEGIN}
pcall(function()
  require("default.hypr.require_optional").module("hypr.arcade")
end)
-- If the optional helper is unavailable, load the file directly:
if not package.loaded["hypr.arcade"] then
  local f = (os.getenv("HOME") or "") .. "/.config/hypr/arcade.lua"
  if io.open(f, "r") then dofile(f) end
end
${HYPR_END}
EOF
)

  if [[ ! -f "$hyprland" ]]; then
    echo "note: ${hyprland} not found — wrote arcade.lua only. Add the require yourself."
    return
  fi

  if file_contains "$hyprland" "$HYPR_BEGIN"; then
    if (( DRY_RUN )); then
      echo "would refresh managed block in ${hyprland}"
      return
    fi
    backup "$hyprland"
    local tmp
    tmp="$(mktemp)"
    awk -v begin="$HYPR_BEGIN" -v end="$HYPR_END" -v block="$require_block" '
      $0 == begin { print block; skip=1; next }
      $0 == end { skip=0; next }
      !skip { print }
    ' "$hyprland" >"$tmp"
    # If markers were unpaired, just append
    if ! file_contains "$tmp" "$HYPR_BEGIN"; then
      printf '\n%s\n' "$require_block" >>"$tmp"
    fi
    mv "$tmp" "$hyprland"
    echo "updated managed block in ${hyprland}"
  elif grep -Eq -- 'hypr\.arcade|arcade\.lua' "$hyprland"; then
    echo "note: ${hyprland} already references arcade — left unchanged"
  else
    if (( DRY_RUN )); then
      echo "would append managed block to ${hyprland}"
      return
    fi
    backup "$hyprland"
    printf '\n%s\n' "$require_block" >>"$hyprland"
    echo "appended managed block to ${hyprland}"
  fi
}

# --- Menu extension ---------------------------------------------------------

install_menu() {
  local src="${REPO_ROOT}/extensions/omarchy-menu.jsonc"
  local dest="${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/extensions/omarchy-menu.jsonc"
  [[ -f "$src" ]] || die "missing ${src}"

  # Body keys only (no outer braces, no leading comments)
  local body
  body="$(awk '
    BEGIN { seen=0 }
    /^[[:space:]]*\/\// { if (!seen) next }
    /^[[:space:]]*$/ { if (!seen) next }
    { seen=1; print }
  ' "$src" | sed '1d;$d' | awk '
    /^[[:space:]]*\/\// { next }
    /^[[:space:]]*$/ { next }
    { print }
  ')"

  # Drop the "gaming" root key if the user already has one (e.g. from GFN plugin)
  if [[ -f "$dest" ]] && grep -Eq '"gaming"[[:space:]]*:' "$dest"; then
    body="$(printf '%s\n' "$body" | awk '
      /"gaming"[[:space:]]*:/ { skip=1; depth=0 }
      skip {
        depth += gsub(/\{/, "{")
        depth -= gsub(/\}/, "}")
        if (depth <= 0 && /\}/) { skip=0; next }
        next
      }
      { print }
    ')"
    # Trim leading comma leftover
    body="$(printf '%s\n' "$body" | sed '1s/^[[:space:]]*,//')"
  fi

  local block
  block=$(printf '%s\n%s\n%s\n' "$BEGIN_MARK" "$body" "$END_MARK")

  mkdir -p "$(dirname "$dest")"
  if [[ ! -f "$dest" ]]; then
    write_file "$dest" $'{\n'"${block}"$'\n}\n'
    return
  fi

  if file_contains "$dest" "$BEGIN_MARK"; then
    if (( DRY_RUN )); then
      echo "would refresh managed menu block in ${dest}"
      return
    fi
    backup "$dest"
    local tmp
    tmp="$(mktemp)"
    awk -v begin="$BEGIN_MARK" -v end="$END_MARK" -v block="$block" '
      $0 ~ begin { print block; skip=1; next }
      $0 ~ end { skip=0; next }
      !skip { print }
    ' "$dest" >"$tmp"
    mv "$tmp" "$dest"
    echo "updated managed menu block in ${dest}"
  elif grep -Eq '"gaming\.arcade"' "$dest"; then
    echo "note: ${dest} already has gaming.arcade keys — left unchanged"
  else
    if (( DRY_RUN )); then
      echo "would insert managed menu block into ${dest}"
      return
    fi
    backup "$dest"
    local tmp
    tmp="$(mktemp)"
    # Insert before the final closing brace
    awk -v block="$block" '
      { lines[NR] = $0 }
      END {
        last = NR
        while (last > 0 && lines[last] ~ /^[[:space:]]*$/) last--
        # Find last }
        for (i = last; i >= 1; i--) if (lines[i] ~ /^[[:space:]]*\}[[:space:]]*$/) { close_at=i; break }
        if (!close_at) { for (i=1;i<=NR;i++) print lines[i]; print block; exit }
        for (i=1; i<close_at; i++) print lines[i]
        # Ensure previous line has a trailing comma if it looks like a key
        if (close_at > 1 && lines[close_at-1] !~ /,$/ && lines[close_at-1] !~ /^[[:space:]]*\/\// && lines[close_at-1] !~ /^[[:space:]]*\{/) {
          # already printed; cannot amend — add comma on block start instead
        }
        print ","
        print block
        for (i=close_at; i<=NR; i++) print lines[i]
      }
    ' "$dest" >"$tmp"
    mv "$tmp" "$dest"
    echo "inserted managed menu block into ${dest}"
  fi
}

echo "Omarchy Arcade install (${PLUGIN_ID})"
install_hypr
install_menu

if (( ! DRY_RUN )); then
  refresh_integrations
  echo
  echo "Done. Open Arcade with Super+Ctrl+G, or Gaming › Arcade in the Omarchy menu."
  echo "Controller: Guide+Start (or Guide tap when idle)."
  echo
  echo "If this was an update (or Arcade showed no games after a failed service load),"
  echo "restart the desktop shell so Service.qml and arcaded remount:"
  echo "  omarchy-restart-shell"
  echo "Then: journalctl --user -n 80 --grep matt-dance.arcade"
fi
