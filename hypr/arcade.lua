-- Omarchy Arcade — keyboard launch bind + overlay blur.
-- Installed to ~/.config/hypr/arcade.lua by scripts/install.sh.
-- Loaded from hyprland.lua via require_optional. Uninstall removes this file.

-- Omarchy's shell loader prefers kind "panel" over "overlay" when a plugin
-- declares both, and `toggle <id>` has no kind argument. Arcade therefore
-- declares only overlay+service, so this bind opens the library (Arcade.qml).
o.bind("SUPER + CTRL + G", "Arcade", "omarchy-shell shell toggle matt-dance.arcade '{}'")
-- Game key on some keyboards (optional; harmless if the key does not exist)
o.bind("XF86Game", "Arcade", "omarchy-shell shell toggle matt-dance.arcade '{}'")

-- Frost the desktop behind Arcade. WlrLayershell.namespace in Arcade.qml is
-- "matt-dance-arcade" (QuickMenu uses "matt-dance-arcade-quickmenu"). The
-- match is a regex, so one rule covers both.
--
-- Hyprland 0.56 (Lua config) wants a named hl.layer_rule:
--   hl.layer_rule({
--     name = "…",
--     match = { namespace = "matt-dance-arcade" },  -- regex
--     blur = true,
--     ignore_alpha = 0.2,  -- 0.0–1.0; skip pixels at or below this alpha
--     xray = false,
--   })
-- See wiki Configuring / Layer rules. `hyprctl -j layerrules` is an
-- unknown request on 0.56.2 — do not query it. `hyprctl keyword` is a
-- no-op on the Lua parser (exit 0, "Use eval"). Runtime apply is
-- arcade-hypr via `hyprctl eval 'hl.config({decoration={blur={enabled=true}}})'`
-- and `hyprctl eval 'hl.layer_rule({...})'`. Legacy hyprlang hosts still
-- accept `blur on, match:namespace matt-dance-arcade` from arcade-hypr.
-- Many Omarchy themes ship decoration.blur.enabled = false — layer rules
-- then do nothing until Arcade turns decoration blur on for the session
-- and restores it on close.
local ARCADE_NS = "matt-dance-arcade"

pcall(function()
  if hl and hl.layer_rule then
    hl.layer_rule({
      name = "matt-dance-arcade-blur",
      match = { namespace = ARCADE_NS },
      blur = true,
      ignore_alpha = 0.2,
      xray = false,
    })
  end
end)
