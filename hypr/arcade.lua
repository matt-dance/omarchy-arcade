-- Omarchy Arcade — keyboard launch bind + overlay blur.
-- Installed to ~/.config/hypr/arcade.lua by scripts/install.sh.
-- Loaded from hyprland.lua via require_optional. Uninstall removes this file.

-- Omarchy's shell loader prefers kind "panel" over "overlay" when a plugin
-- declares both, and `toggle <id>` has no kind argument. Arcade therefore
-- declares only overlay+service, so this bind opens the library (Arcade.qml).
o.bind("SUPER + CTRL + G", "Arcade", "omarchy-shell shell toggle matt-dance.arcade '{}'")
-- Game key on some keyboards (optional; harmless if the key does not exist)
o.bind("XF86Game", "Arcade", "omarchy-shell shell toggle matt-dance.arcade '{}'")

-- Frost the desktop behind Arcade. The overlay namespace is
-- WlrLayershell.namespace in Arcade.qml / QuickMenu.qml. ignore_alpha
-- keeps Hyprland blurring pixels that are only partly transparent.
-- pcall: older Hyprland Lua without layer rules still loads the binds.
pcall(function()
  if hl and hl.layer_rule then
    hl.layer_rule({
      match = { namespace = "matt-dance-arcade" },
      blur = true,
      ignore_alpha = 0.2,
    })
  end
end)
