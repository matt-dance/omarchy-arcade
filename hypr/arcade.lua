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
-- match is a regex, so one rule covers both. Hyprland 0.53+ wants
-- hl.layer_rule; keyword layerrule is the runtime fallback Arcade also
-- applies when the overlay opens. Many Omarchy themes ship
-- decoration.blur.enabled = false — layer rules then do nothing until
-- Arcade turns decoration blur on for the session.
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

local function arcade_keyword(rule)
  local quoted
  if o and o.shell_quote then
    quoted = o.shell_quote(rule)
  else
    quoted = "'" .. tostring(rule):gsub("'", "'\\''") .. "'"
  end
  if hl and hl.exec_cmd then
    pcall(hl.exec_cmd, "hyprctl keyword layerrule " .. quoted)
  else
    os.execute("hyprctl keyword layerrule " .. quoted .. " >/dev/null 2>&1")
  end
end

-- 0.53+ syntax first, then the pre-0.53 form.
arcade_keyword("blur on, match:namespace " .. ARCADE_NS)
arcade_keyword("ignore_alpha 0.2, match:namespace " .. ARCADE_NS)
arcade_keyword("blur, " .. ARCADE_NS)
arcade_keyword("ignorealpha 0.2, " .. ARCADE_NS)
