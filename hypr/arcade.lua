-- Omarchy Arcade — keyboard launch bind.
-- Installed to ~/.config/hypr/arcade.lua by scripts/install.sh.
-- Loaded from hyprland.lua via require_optional.

o.bind("SUPER + CTRL + G", "Arcade", "omarchy-shell shell toggle matt-dance.arcade '{}'")
-- Game key on some keyboards (optional; harmless if the key does not exist)
o.bind("XF86Game", "Arcade", "omarchy-shell shell toggle matt-dance.arcade '{}'")
