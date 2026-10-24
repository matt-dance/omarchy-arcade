# Competitive analysis

Researched on 2026-10-24. Activity is the last push or release seen on GitHub, GitLab or the project site on that date. Star counts are rounded. "All sources" means it detects games from Steam, Epic/GOG/Amazon, Lutris, Bottles, itch, Flatpak/`.desktop`, emulators and cloud services without manual setup per game.

## Omarchy ecosystem

There are **zero** listings on [plugins.omarchy.org](https://plugins.omarchy.org) today; the page shows "0 community plugins". The projects below come from GitHub and from OmaPicks' gaming page.

| Project | What it does | Controller-first | All sources | Fits Omarchy / Hyprland | Activity | License |
|---|---|---|---|---|---|---|
| [Game Mode Switcher](https://github.com/silvaio/gamemode-switcher) (`silvaio.gamemode`) | Bar chip that toggles a "game mode": do not disturb, animations, blur and gaps off, performance profile, key-lock submap. Optionally starts Steam in Gamescope or Big Picture. Quick-launch buttons for installed clients | No (mouse click on the bar) | No (launches clients, not games) | Native Quattro plugin | v1.2.0, Aug 2026, ~8★. OmaPicks gaming "champion" | MIT |
| [Controller Control](https://github.com/perminder-klair/omarchy-controller-control) (`co.klair.controller-control`) | evdev daemon plus bar widget that maps pad chords to keys or commands, with a bindings editor, Game/OS modes and a pointer mode | Input only, no UI for games | None | Native Quattro plugin, pure Python stdlib | v0.3.0, Oct 2026, ~2★ | MIT |
| [OmaSwiss](https://github.com/glasschan/oma-swiss) | Six Hyprland tools in one bar icon, including a gaming-mode toggle | No | No | Native plugin | v0.5.0, Sep 2026, ~5★ | MIT |
| [W.O.P.R.](https://github.com/28allday/W.O.P.R) | Installer plus `gum` TUI that launches Steam inside Gamescope with resolution and MangoHud presets, with keybinds | No (TUI) | Steam only | Script, not a plugin; edits the system | **Archived**, Nov 2025, ~85★ | MIT |
| [omarchy-steam-gaming-mode](https://github.com/cephalization/omarchy-steam-gaming-mode) | Setup script that switches Hyprland to a Gamescope Steam Big Picture session on `Super+F12` | Via Steam | Steam only | Script; writes `/usr/local/bin` | Jul 2026, ~64★ | MIT |
| [GeForce NOW Menu](https://github.com/matt-dance/omarchy-gfn-menu-plugin) (`matt-dance.gfn-omarchy`) | Search the GFN catalog, add titles as Omarchy `.desktop` launchers, direct `--url-route` launch | Keyboard menu | GFN only | Native plugin | v0.1.1, 2026 | MIT |

Nothing in the Omarchy ecosystem is a game *library* UI. The existing pieces are a desktop toggle, a chord mapper and Steam-session scripts. Arcade should integrate with them rather than compete.

## Steam and Deck-style sessions

| Project | What it does | Controller-first | All sources | Fits Omarchy / Hyprland | Activity | License |
|---|---|---|---|---|---|---|
| Steam Big Picture (`steam -gamepadui`) | Valve's 10-foot client. The best controller UX on Linux, with Steam Input and an in-game overlay | Yes | Steam, plus manual non-Steam shortcuts (or Steam ROM Manager) | Runs as a window in Hyprland; Steam's look, not themeable; Guide button owned by Steam | Very active | Proprietary |
| [Gamescope](https://github.com/ValveSoftware/gamescope) | Valve's micro-compositor: nested or embedded, upscaling, frame limiting | n/a | n/a | Works nested inside Hyprland as a per-game wrapper | Very active, Oct 2026, ~5.2k★ | BSD-2-Clause |
| [gamescope-session](https://github.com/ChimeraOS/gamescope-session) / [-steam](https://github.com/ChimeraOS/gamescope-session-steam) | A display-manager session that boots straight into Steam in Gamescope, like a Deck | Yes | Steam only | A separate session: you log out of Hyprland | Jan 2026 / Dec 2024 | MIT |
| [Bazzite](https://github.com/ublue-os/bazzite) | Fedora Atomic gaming distro with a Steam Gaming Mode session | Yes | Steam (plus Steam ROM Manager) | Replaces Omarchy | Very active, ~9.2k★ | Apache-2.0 |
| [ChimeraOS](https://github.com/ChimeraOS/chimeraos) | Arch-based immutable couch-gaming distro | Yes | Steam plus its own web app for adding other sources | Replaces Omarchy | Aug 2026, ~2k★ | MIT |
| [HoloISO](https://github.com/HoloISO/releases) | Unofficial SteamOS 3 rebuild for PCs | Yes | Steam | Replaces Omarchy | **Inactive** since Sep 2024 | Unlicense/mixed |

## Frontends and launchers

| Project | What it does | Controller-first | All sources | Fits Omarchy / Hyprland | Activity | License |
|---|---|---|---|---|---|---|
| [OpenGamepadUI](https://github.com/ShadowBlip/OpenGamepadUI) | Godot 4 gamepad-native launcher and overlay, with plugins (Steam, SteamGridDB), InputPlumber input, PowerStation TDP | Yes | Partial: Steam via plugin, desktop entries; no Heroic, Lutris or Bottles importers | Designed for Gamescope sessions; Godot look; its own session repo is archived | v0.46.1, Sep 2026, ~1k★; README still says "very early stages" | GPL-3.0 |
| [Pegasus Frontend](https://github.com/mmatyas/pegasus-frontend) | Qt 5 / QML frontend with QML themes. Auto-imports Steam, Lutris, ES/Skraper gamelists, Playnite (Windows), GOG Galaxy (Windows) | Yes | Partial: no Heroic, Bottles, itch or cloud | Standalone Qt 5 window; themes are QML, so it could be skinned in Omarchy colors, but not live | Continuous build Sep 2026; last tagged release Alpha 16 in 2022; Qt 5 is end-of-life; ~1.9k★ | GPL-3.0 |
| [ES-DE](https://gitlab.com/es-de/emulationstation-de) | The leading emulation frontend: huge preconfigured emulator set, scraper, themes | Yes | Emulators excellent; PC stores only via manual shortcut files | Standalone full-screen app with its own theme format | Very active, 3.5.0 on 2026-09-30 | MIT |
| [RetroArch](https://github.com/libretro/RetroArch) | libretro emulator plus frontend (XMB/Ozone) | Yes | ROMs only | Preinstalled by Omarchy's installer; best used as Arcade's emulation backend | Very active, ~14k★ | GPL-3.0 |
| [Lutris](https://github.com/lutris/lutris) | GTK game manager with many runners and installers, plus Steam/GOG/Epic service integrations | No | Good, but desktop-first | Regular app; Omarchy installer exists | Active, Oct 2026, ~10k★ | GPL-3.0 |
| [Heroic](https://github.com/Heroic-Games-Launcher/HeroicGamesLauncher) | Electron launcher for Epic, GOG and Amazon, plus sideloaded games | Partial gamepad navigation | Its own stores only | Regular app; Omarchy installer exists | Very active, ~12.5k★ | GPL-3.0 |
| [Cartridges](https://github.com/kra-mo/cartridges) | GTK4 / libadwaita aggregator for Steam, Lutris, Heroic, Bottles, itch, Legendary, RetroArch, Flatpak and desktop entries | No (a controller-capable rewrite was planned) | **Yes**, the best importer set | GTK look; not a plugin | **Ceased development, archived** Sep 2026 | GPL-3.0 |
| [Klay](https://github.com/gshipley/Klay) | PySide6 / KDE successor to Cartridges; adds GeForce NOW (from the Flatpak cache) and IGDB | No | **Yes**, including GFN | KDE / Qt look; Flatpak app | Active, Oct 2026, ~17★ | GPL-3.0 |
| [GameHub](https://github.com/tkashkin/GameHub) | Vala unified library | No | Yes (dated) | GTK | **Archived** | GPL-3.0 |
| [Playnite](https://github.com/JosefNemec/Playnite) | The gold standard aggregator on Windows, with a controller "Fullscreen mode" | Yes (fullscreen mode) | Yes, via extensions | **No Linux version yet** (planned for 2026, desktop mode first) | Active, ~14k★ | MIT |
| [Steam ROM Manager](https://github.com/SteamGridDB/steam-rom-manager) | Pushes ROMs and other launchers into Steam as shortcuts with SteamGridDB art | Via Steam | Yes, through Steam | A tool, not a UI | Active, ~2.6k★ | GPL-3.0 |

## Controller-on-Hyprland tools

Hyprland has no native gamepad support; [the feature request was closed](https://github.com/hyprwm/Hyprland/issues/1211).

| Project | What it does | Controller-first | Fits Hyprland | Activity | License |
|---|---|---|---|---|---|
| [Keymasq](https://github.com/nyrda/keymasq) | GTK4 remapper with layered per-app profiles, chords, macros and Hyprland Lua dispatcher actions | Remapper | Yes (Hyprland ≥ 0.55) | Very active, Oct 2026 | MIT |
| [Makima](https://github.com/cyber-sushi/makima) | TOML evdev remapper with per-window-class configs | Remapper | Yes | Jan 2026, ~250★ | GPL-3.0 |
| [AntiMicroX](https://github.com/AntiMicroX/antimicrox) | Classic Qt pad-to-keyboard/mouse mapper | Remapper | Works under XWayland and Wayland | Active, ~4k★ | GPL-3.0 |
| [InputPlumber](https://github.com/ShadowBlip/InputPlumber) | Root service that intercepts and recomposes input devices (handhelds) | Input layer | Compositor-agnostic | Very active, Oct 2026 | GPL-3.0 |
| [game-shell / tv-shell](https://github.com/jedwards1230/tv-shell) | Quickshell plus Hyprland kiosk couch shell for Moonlight, with a Rust daemon (EVIOCGRAB to uinput) | Yes | Yes, but as a dedicated kiosk session | Small, mid-2026 | GPL-3.0 |

## What the landscape tells us

1. **Controller-first UIs** (Big Picture, OpenGamepadUI, ES-DE, Pegasus, Deck-style sessions) either cover one ecosystem (Steam, or emulation) or expect to own the whole session.
2. **All-source aggregators** (Cartridges, Klay, Lutris, GameHub) are desktop mouse-and-keyboard apps, and the best one just died.
3. **Nothing is native to Omarchy's shell.** Every candidate is a separate toolkit window that ignores Omarchy themes, or a session that throws away the desktop.
4. **The Omarchy plugins** each solve one slice: desktop tweaks, chord mapping, GFN launchers. None is a library.

The gap is exactly the intersection: controller-first, all sources, native to Omarchy, no session switch.

## Options considered

| Option | Effort | Result | Verdict |
|---|---|---|---|
| **A. Wrap Steam Big Picture.** Use Steam ROM Manager-style export to push every non-Steam game into Steam as a shortcut, plus Game Mode Switcher for the session | Low | Best controller UX on day one, but it looks like Steam, can't follow Omarchy themes, needs Steam running, the Guide button belongs to Valve, and it's proprietary | Keep as a *tile* ("Open Steam Big Picture"), not the product |
| **B. Wrap Pegasus with an Omarchy theme** plus generated metadata files from our scanners | Medium | QML themes could mimic Omarchy, but it is a Qt 5 alpha, a separate window with no live theme tokens, has no in-game quick menu, no Hyprland session handling, and needs our scanners anyway | No: we would write the hard parts anyway and inherit Qt 5 |
| **C. Wrap ES-DE** | Medium | Excellent for emulation; PC stores need generated shortcut files; its own theme engine; separate SDL window | No as the product; possible "Open ES-DE" tile |
| **D. Fork OpenGamepadUI** | High | Godot, Gamescope-centric, GPL; would need a rewrite to look Omarchy-native and to run on the Hyprland desktop | No |
| **E. Fork Cartridges or Klay** | High | Good importers, but a GTK4 or KDE desktop app with no controller UI, archived or young, GPL | No; study their source *formats* only, copy no code |
| **F. Build a native Quickshell plugin, delegating everything else** | Medium | Native look and live themes, all sources, Hyprland-aware sessions, one install command | **Recommended** |

## Recommendation: build, as a native Omarchy plugin that delegates

Build Arcade from scratch as a Quattro shell plugin, but keep it small by **delegating** instead of re-implementing:

- **Launching and installing** stays in Steam, Heroic, Lutris, Bottles, itch, RetroArch and GFN. Arcade only calls their URI or CLI entry points.
- **GeForce NOW** comes from your GFN plugin's launchers and `gfn-play.sh`.
- **The performance session** is delegated to Game Mode Switcher when present.
- **Chord semantics** match Controller Control, and Arcade pauses it while open.
- **Gamescope and MangoHud** are per-game wrappers, not a session.
- **Emulation** uses RetroArch and Omarchy's `~/Games/roms` layout.

This is the only option that delivers the "native to Omarchy" requirement. Every wrap option would leave us writing the scanners, session tracking and Hyprland integration anyway, which is most of the work.

### Concrete differentiators

1. **It is part of the desktop, not a window on it.** It renders inside `omarchy-shell` with the theme's own tokens, gradient borders, monospace type and motion curve, and it re-colors live on `omarchy theme set`. No competitor can do this.
2. **One library for everything Omarchy installs.** Steam (including Proton and non-Steam shortcuts), Heroic (Epic, GOG, Amazon), Lutris, Bottles, itch, Flatpak and native games, **GeForce NOW titles**, Xbox Cloud, Battle.net, Minecraft, RetroArch launchers and ROMs. That is Cartridges' coverage plus cloud, inside a controller UI.
3. **Instant in, instant out.** No session switch or logout. `GUIDE + START` or `SUPER + CTRL + G` opens it in about 30 ms from the warm shell, and games return you to the exact card you launched.
4. **Hyprland-aware session handling.** Scope-based process tracking, Steam `reaper` and window-class exit detection, workspace and focus restore, and an idle inhibitor (controller-only play otherwise triggers Omarchy's screensaver).
5. **Omarchy-style binds for the controller.** A `GUIDE +` chord table that reads like `bindings.lua`, lives in one TOML file with descriptions, reloads live, and has a cheat sheet like `omarchy menu keybindings`.
6. **Keyboard is a first-class citizen.** Every action has a key, including `hjkl`, `/` for search and `Tab` for shelves, and the hint bar switches between key caps and Xbox, PlayStation or Nintendo glyphs as you switch devices.
7. **Themed typographic covers** for games without art. Missing art looks intentional, not broken.
8. **Plays well with the existing plugins** (GFN Menu, Game Mode Switcher, Controller Control) instead of fighting them over the Guide button or the same binds.
9. **The Omarchy install model.** `omarchy plugin add … --enable`, then one reviewed `install.sh`. No compile, no sudo, no system files, a clean uninstall. MIT.
