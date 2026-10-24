# Omarchy Arcade: Plan

Status: **approved and in implementation**. M0/M1 MVP and M2 scanners are in-tree; see [`README.md`](README.md). Decisions on all open questions are locked in §9. [`ARCHITECTURE.md`](ARCHITECTURE.md) covers how it is built. [`COMPETITIVE_ANALYSIS.md`](COMPETITIVE_ANALYSIS.md) covers what already exists and why we build rather than wrap.

## 1. What it is

A controller-first, full-screen game library and in-game quick menu for Omarchy, in the spirit of Steam Big Picture. It runs inside Omarchy's own desktop shell, so it uses the current theme's colors, borders, fonts and motion, and it re-colors live when the theme changes. It finds every installed game on the machine (Steam, Heroic, Lutris, Bottles, itch, Flatpak and native `.desktop` games, GeForce NOW, emulators). It launches them, tracks them, and brings you back when they exit. A Guide-button chord system mirrors Omarchy's keyboard binds and is configured in one plain text file.

### Proposed name

**Omarchy Arcade.** The manifest id is `matt-dance.arcade`, the repo is `omarchy-arcade`, the display name is "Arcade", and the IPC target is `matt-dance.arcade`.

Why not "Game Mode":

- "GameMode" is already Feral's `gamemoded`, a performance daemon that many Arch gamers have installed.
- `silvaio.gamemode` ("Game Mode Switcher") is already the top-ranked Omarchy gaming plugin. It is a desktop-optimization toggle, not a library. Using the same name would confuse users of both, and we want to integrate with it (see §7).
- "Arcade" says "a place where you pick a game and play". It is short, and it reads well in the Omarchy menu as Gaming › Arcade.

**Decision (locked):** Omarchy Arcade / `matt-dance.arcade`.

### Non-goals

- No store, no installs or updates of games, no login flows. Those stay in Steam, Heroic and the other launchers. Arcade launches through them.
- No replacement session. We do not log you out of Hyprland into Gamescope the way SteamOS, Bazzite and `gamescope-session` do. Arcade sits on top of your desktop and gets out of the way instantly.
- No controller remapping for games. We do not grab the pad or create virtual controllers in the MVP. Steam Input, InputPlumber and Keymasq already do that.

## 2. Key research findings that shape the plan

1. **Omarchy now has a real plugin system.** Omarchy "Quattro" runs the whole desktop as one long-lived Quickshell (Qt 6 QML) process, `omarchy-shell`. A third-party plugin is a git repo with a root `manifest.json` (`schemaVersion: 1`, an `author.name` id, `kinds`, `entryPoints`), installed to `~/.config/omarchy/plugins/<id>/` by `omarchy plugin add <git-url> [--enable]`, and removed with `omarchy plugin remove <id>`. The kinds are `overlay`, `panel`, `menu`, `service`, `bar-widget` and `bar`. `omarchy plugin add` **never runs install hooks, never compiles, and never uses sudo**. `omarchy plugin validate` rejects symlinks. The listing site is [plugins.omarchy.org](https://plugins.omarchy.org), which uses a root `preview.png`.
2. **Your GFN plugin is the convention reference.** `matt-dance.gfn-omarchy` uses `overlay` plus `service` with `keepLoaded: true`, Python and Bash helpers under `scripts/` driven from QML `Process`, a separate idempotent `scripts/install-menu-extension.sh` that merges a managed `BEGIN`/`END` block into `~/.config/omarchy/extensions/omarchy-menu.jsonc` (with `--dry-run` and a `.bak.<timestamp>` backup), summoning via `omarchy-shell shell summon <id> '{}'`, and `.desktop` files tagged `X-Omarchy-Plugin=` and `X-GFN-*`. Arcade follows all of that, and it reads GFN's `.desktop` files as a game source.
3. **Hyprland config is Lua.** User binds go in `~/.config/hypr/bindings.lua` as `o.bind("SUPER + CTRL + G", "Arcade", "omarchy-shell shell toggle matt-dance.arcade '{}'")`. Plugins cannot register binds themselves, so a companion installer script is needed, just like GFN's menu helper. Runtime rules can also be pushed with `hyprctl eval` (the approach `silvaio.gamemode` uses for its key-lock submap).
4. **The shell has no controller input.** Qt 6 dropped QtGamepad, and Quickshell has no gamepad API. Controller input needs a small companion daemon. `co.klair.controller-control` proves the pattern inside Omarchy: a pure-Python-stdlib evdev daemon, started by a QML `service`, streaming JSON lines over stdout, and exiting when the shell closes its stdin.
5. **Omarchy's own gaming installers leave fingerprints we can read.** These include Steam, Heroic, Lutris, RetroArch (ROMs in `~/Games/roms`, plus per-game `.desktop` launchers from `omarchy-games-retro-install` tagged `Categories=Game;Emulator;`), Battle.net (`omarchy-launch-battlenet` with a umu/GE-Proton prefix in `~/Games/battlenet`), Xbox Cloud (an `omarchy-webapp-install` web app), GeForce NOW (Flatpak `com.nvidia.geforcenow`), Minecraft and Moonlight.

### Build, fork or wrap?

**Build** a native shell plugin that **delegates** launching to the existing launchers. The full table of 29 projects and the six options considered are in [`COMPETITIVE_ANALYSIS.md`](COMPETITIVE_ANALYSIS.md).

- Controller-first UIs (Steam Big Picture, OpenGamepadUI, ES-DE, Pegasus, Deck-style sessions) cover one ecosystem or take over the session.
- All-source aggregators (Cartridges, now archived; Klay; Lutris) are mouse-and-keyboard desktop apps.
- Nothing is native to Omarchy's shell.
- Wrapping Pegasus or ES-DE would still require our own scanners, session tracking and Hyprland work, which are most of the effort, while losing the native look.

## 3. Recommended stack

### Decision

| Layer | Choice |
|---|---|
| UI | A **Quickshell QML plugin inside `omarchy-shell`**, using the `overlay` kind (full-screen library), `panel` (in-game quick menu) and `service` (`keepLoaded`, owns the state and the daemon) |
| Theming | The shell's `qs.Commons` singletons: `Commons.Color.*`, `Style.*` and `Border.*`, plus `BorderSurface` from `qs.Ui`. No theme parsing of our own |
| Controller input and session tracking | **`arcaded`**, a long-lived **Python 3 standard-library** daemon. It reads evdev directly with `ioctl` and `select`, and it uses `pidfd` and inotify through `os` and `ctypes`. It speaks JSON lines to the service |
| Library scanners and art fetcher | Python 3 standard library, using `sqlite3`, `json`, `tomllib`, `urllib` and a small binary-VDF parser. They run as one-shot subprocesses |
| Config | TOML (`tomllib`), with defaults in the plugin and user overrides in `~/.config/omarchy/arcade/arcade.toml` |
| Distribution | A plain git repo installed with `omarchy plugin add`. Nothing to compile, no pip, no sudo. Optional integration via `scripts/install.sh` |
| License | MIT, matching Omarchy and its plugin ecosystem. This means no copying from the GPL projects in the competitive analysis; we re-implement from file-format knowledge |

### Why a shell plugin and not a separate app

| Option | Native Omarchy look | Fits the plugin system | Focus and fullscreen handling | Controller input | Startup | Verdict |
|---|---|---|---|---|---|---|
| **Quickshell plugin (chosen)** | Exact: same tokens and live theme switching for free | Yes, it is the plugin system | Layer-shell overlay on `overlay` layer, exclusive keyboard focus, no window rules to fight | Needs a companion daemon (any option except Godot/SDL apps does) | About 30 ms summon from the warm shell | **Best fit** |
| GTK4 / libadwaita app | No. It would need its own CSS generated from `colors.toml`, and Adwaita's look fights Omarchy's | Would need a wrapper plugin | Regular window, needs Hyprland rules, focus races with the game | Needs SDL or evdev | Cold start of 300 ms or more | No |
| Qt/QML standalone app | Close, but it duplicates Quickshell and can't use the shell singletons | Would need a wrapper plugin | Same window problems as GTK | Same | Cold start | No, since it's strictly worse than a plugin |
| Tauri / web UI | Re-implemented by hand | No | Webview window, worst-case focus and input latency | Gamepad API in WebKitGTK is unreliable on Wayland | Slow, heavy | No |
| Godot (like OpenGamepadUI) | No | No | Designed for Gamescope sessions | Built-in SDL input, which is good | Slow, about 100 MB | No |
| Standalone layer-shell app (Rust + iced/GTK layer-shell) | Re-implemented by hand | No | Good, the same as ours | SDL3 natively | Fast | Viable plan B if the shell API ever blocks us |

The plugin route has risks. Plugins run unsandboxed in the shell process, so a hang in our QML freezes the bar. Plugin hot-reload doesn't replace a kept service. The QML facade for third-party plugins is narrower than for built-ins. We mitigate these by keeping all I/O and parsing in subprocesses, virtualizing every list, and decoding images asynchronously. See §8.

### Controller input library

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **Raw evdev via Python stdlib (chosen for M1)** | No dependencies, nothing to compile, works for every pad the kernel knows (`xpad`, `xpadneo`, `hid-playstation`, `hid-nintendo`, `hid-steam`, 8BitDo in X-input mode). The kernel gamepad spec already normalizes `BTN_SOUTH`/`BTN_EAST`/…/`BTN_MODE`. Proven in Omarchy by Controller Control. Reading `/dev/input` needs the `input` group, which Omarchy's Xbox-controller installer already adds; newer systemd versions also grant a `uaccess` ACL on joysticks. Setup detects and explains both | Odd or generic pads need a small quirks table. No gyro or touchpad | **Yes** |
| SDL3 via `ctypes` (optional backend, M3) | `gamecontrollerdb` mappings for oddball pads, plus glyph and type detection | Must force `SDL_JOYSTICK_HIDAPI=0`, otherwise SDL opens hidraw and can switch DualShock and DualSense report modes under Steam. Depends on `libSDL3.so` (usually present as a Steam dependency) | Optional fallback for unmapped pads |
| libinput | It's what Hyprland uses | libinput ignores joysticks entirely | No |
| Rust daemon with SDL3 or gilrs | Fast, typed | Needs a build step or committed binaries for x86 and aarch64, which goes against `omarchy plugin add`'s "no build" model | Revisit only if Python proves too slow (it won't at about 1 kHz of events) |
| InputPlumber (optional integration, M5) | Real intercept mode: grabs the pad and re-emits a virtual one, so Guide chords never leak into games | Root system service, GPL, aimed at handhelds | Opt-in "exclusive chords" mode later |

**How input reaches the UI.** `arcaded` never types keys into the focused window to drive Arcade. It sends intents (`{"t":"nav","dir":"down"}`) to the service, and the overlay handles them through the same code path as keyboard `Keys`. Typing synthetic keys through `uinput` is used only for user bindings with a `keys =` action, for example the MangoHud toggle.

### Hyprland integration

- **Arcade's own surface** is a `WlrLayershell` window on the `overlay` layer of the focused monitor, with `keyboardFocus: Exclusive` while open, plus a `no_anim` layer rule pushed at runtime. It is not a client window, so tiling, `float` rules and focus-stealing prevention don't apply.
- **Launching a game** hides the overlay first, so the layer releases focus, and then runs the launch command through `uwsm-app -- …` inside a transient `systemd-run --user --scope --unit=arcade-<slug>-<n>` scope. The scope collects every child process, including Proton, `umu`, wine servers and the Steam `reaper`. Hyprland then focuses the new toplevel normally.
- **Recognizing the game window** uses Quickshell's `Hyprland` event stream (`openwindow`, `closewindow`, `activewindow`), not polling. The game is the first new toplevel whose pid is in our scope, or whose class matches per-source hints such as `steam_app_<appid>`, `GeForceNOW`, `com.libretro.RetroArch` and `steam_app_battlenet`.
- **Fullscreen** is set by a per-game `fullscreen = "auto" | "always" | "never"` option. `auto` leaves the game alone, because most games manage their own fullscreen.
- **When the game exits**, meaning the tracked window closed and the scope or pidfd is gone, Arcade re-summons on the same monitor and restores the workspace it launched from. Launchers that hand off and stay alive (Steam, Heroic) are handled per source: for Steam, the game is "done" when `reaper … AppId=<id>` exits.
- **Idle.** Controller input bypasses Hyprland's idle timers, because evdev gamepads aren't seat input, so a controller-only session would hit Omarchy's screensaver at 150 s. Arcade holds a Wayland idle inhibitor while it is open and while a tracked game runs. This is a real gotcha that every competitor ignores.
- **Optional key lock** while a game runs. This is a runtime `hyprctl eval` submap like `silvaio.gamemode`'s, or a delegation to that plugin when it is installed.

### Coexisting with Steam Input and other input tools

- **No exclusive grabs by default.** `arcaded` reads pads read-only, beside Steam, the games and Controller Control.
- **Steam's virtual pad.** When Steam is running with Steam Input on, it reads the real pad over hidraw and creates a virtual Xbox pad (VID `28de`, PID `11ff`). The daemon prefers physical devices and ignores the virtual pad when a physical one is present, so input never doubles. A Steam Controller or Deck controller is visible only through Steam's virtual pad while Steam runs, and in that case we accept it.
- **The Guide button.** Steam opens its overlay or Big Picture on Guide. Our setup screen tells users to turn off Steam › Settings › Controller › "Guide button focuses Steam" and offers a one-key alternative: the modifier is configurable, with `SELECT` held as the fallback.
- **Chords leak into games.** Without a grab, a game also sees the `A` in `GUIDE + A`. That's why the default chords pair Guide with buttons that are harmless in-game (D-pad, shoulders, Start/Select), and why destructive actions need a hold. A true intercept mode is the optional InputPlumber integration later.
- **Controller Control** (`co.klair.controller-control`). If it is installed, Arcade asks it to pause while Arcade's UI is open, through `omarchy-shell controller disable` and `enable`, and it warns about chord conflicts in Settings.

## 4. Module breakdown

The detail is in [`ARCHITECTURE.md`](ARCHITECTURE.md). In summary:

| Module | Lives in | Responsibility |
|---|---|---|
| `manifest.json` | root | Id `matt-dance.arcade`, kinds `overlay`, `panel`, `service`, `keepLoaded: true` |
| `Service.qml` | QML | Singleton state: library model, session state machine, IPC target, starts and stops `arcaded`, routes intents |
| `Arcade.qml` + `screens/` | QML | Full-screen overlay: Home, Library, Game details, Search, Settings, Power |
| `QuickMenu.qml` | QML | In-game side panel: resume, close game, volume, screenshot, record, performance overlay, Omarchy menu, back to Arcade |
| `ui/` | QML | Focus-grid navigation, game cards, shelves, button-hint footer, on-screen keyboard, glyph sets |
| `bin/arcaded` | Python | Long-lived daemon: input (`input/`), chord engine (`combos/`), session tracker (`session/`), config loader and watcher |
| `bin/arcade-scan` | Python | One-shot scanner run: every `scanners/*.py` → unified `library.json` |
| `scanners/` | Python | `steam`, `heroic`, `legendary`, `lutris`, `bottles`, `itch`, `desktop` (Flatpak, native, GFN, Omarchy web apps, Battle.net, Minecraft), `retroarch`, `roms`, `moonlight` |
| `bin/arcade-art` | Python | Art resolver: local caches → SteamGridDB → generated typographic card |
| `default/arcade.toml` | TOML | Default settings and bindings (documented, mirrors `bindings.lua` style) |
| `extensions/omarchy-menu.jsonc` | JSONC | Gaming › Arcade menu rows |
| `hypr/arcade.lua` | Lua | The launch bind, copied to `~/.config/hypr/arcade.lua` by the installer |
| `scripts/install.sh`, `scripts/uninstall.sh` | Bash | Idempotent integration (bind, menu), with `--dry-run`, backups and managed blocks |
| `tests/` | Python + Bash | Scanner fixtures, chord-engine tests, VDF parser tests, installer tests, `omarchy plugin validate` in CI |

## 5. Default bindings

Bindings use Omarchy's `+` syntax and live in `arcade.toml`. "Guide" is the Xbox, PS or Home button. Button names are positional (`A` means the bottom face button on every pad), and the UI shows the right glyph (A/✕, B/○, X/□, Y/△) for the connected pad.

### Global chords (work everywhere: desktop, in-game, in Arcade)

| Chord | Action | Notes |
|---|---|---|
| `GUIDE + START` | Toggle Arcade (open, or return to it) | The controller launch combo |
| `GUIDE` (tap) | Open the Quick Menu when a game runs; open Arcade otherwise | Fires on release, only if no chord happened |
| `GUIDE + B` (hold 0.8 s) | Close the current game (graceful, then force after confirm) | Hold because it is destructive |
| `GUIDE + DPAD_UP` / `DPAD_DOWN` | Volume up / down (repeats) | `omarchy-audio-output-volume` |
| `GUIDE + DPAD_LEFT` / `DPAD_RIGHT` | Previous / next workspace | |
| `GUIDE + RB` | Screenshot | `omarchy-capture-screenshot` |
| `GUIDE + LB` | Start or stop screen recording | `omarchy-capture-screenrecording` |
| `GUIDE + Y` | Toggle the MangoHud performance overlay | `keys = "SHIFT_R + F12"` via uinput |
| `GUIDE + X` | Omarchy menu | `keys = "SUPER + SPACE"` |
| `GUIDE + A` | Focus the running game (resume) | |
| `GUIDE + R3` | Mute microphone | |
| `GUIDE + SELECT` | Show the bindings cheat sheet | Like `omarchy menu keybindings` |
| `GUIDE + SELECT + START` (hold 2 s) | Emergency exit: kill the game scope, restore the desktop, open Arcade | Always on, can't be unbound |

### Inside Arcade

| Controller | Keyboard | Action |
|---|---|---|
| D-pad / left stick | Arrows / `h` `j` `k` `l` | Move focus |
| `A` | `Enter` | Launch, or select |
| `B` | `Esc` / `Backspace` | Back, or close Arcade from Home |
| `X` | `i` | Game details and options |
| `Y` | `/` | Search (on-screen keyboard with a pad, plain typing with a keyboard) |
| `LB` / `RB` | `Shift+Tab` / `Tab` | Previous / next shelf or tab |
| `LT` / `RT` | `PgUp` / `PgDn` | Jump a page or letter |
| `SELECT` | `s` | Sort and filter (source, installed, runner, recent) |
| `START` | `m` | Arcade menu (Settings, Power, Rescan, Exit) |
| `R3` | `f` | Toggle favorite |

### Keyboard launch

- **`SUPER + CTRL + G`**: toggle Arcade. This combo is unused in Omarchy's defaults. `silvaio.gamemode` *suggests* it as an optional bind, so the installer checks `hyprctl binds` and the user's `bindings.lua`. On a conflict it asks, offering `SUPER + CTRL + Y` as the fallback. See Q4.
- `XF86Game`, the game key on some keyboards, is also bound when present.

### Config example (abridged `default/arcade.toml`)

```toml
[input]
modifier = "GUIDE"          # or "SELECT" if Steam keeps the Guide button
combo_window_ms = 45
hold_ms = 800
ignore_steam_virtual_pad = "auto"

[ui]
scale = 1.25                # 10-foot multiplier on top of the theme's spacing
open_on = "focused"         # or a monitor name, e.g. "HDMI-A-1" for the TV
glyphs = "auto"             # auto | xbox | playstation | nintendo | keyboard

[launch]
fullscreen = "auto"
return_to_arcade = true
idle_inhibit = true

[sources]
steam = true
heroic = true
lutris = true
bottles = true
itch = true
desktop = true
retroarch = true
roms = false                # opt in; scans ~/Games/roms
steamgriddb_key_file = "~/.config/omarchy/arcade/steamgriddb.key"

[bindings]
"GUIDE + START"     = { action = "arcade.toggle", description = "Arcade" }
"GUIDE + B"         = { action = "game.close", hold = true, description = "Close game" }
"GUIDE + DPAD_UP"   = { exec = "omarchy-audio-output-volume raise", repeat = true, description = "Volume up" }
"GUIDE + RB"        = { exec = "omarchy-capture-screenshot", description = "Screenshot" }
"GUIDE + Y"         = { keys = "SHIFT_R + F12", description = "Performance overlay" }
# "GUIDE + LT"      = false   # unbind a default
```

Users override single keys. The user file is merged over the defaults per binding, the same split as `default/hypr` versus `~/.config/hypr`. Edits apply live.

## 6. Milestones

Each milestone ends with a tagged release that passes `omarchy plugin validate` and the test suite.

### M0: Feasibility spike (throwaway branch)

Prove the four risky seams before building UI.

- An overlay plugin is summoned by `omarchy-shell shell toggle matt-dance.arcade` from a bind.
- `arcaded` started by `Service.qml` prints pad events that reach QML, and it exits when the shell restarts.
- Launching a Steam Proton game from QML: detect its window (`steam_app_<id>`) and its exit (`reaper` gone), then re-summon.
- The idle inhibitor held from the plugin prevents the screensaver.

**Acceptance:** all four are demonstrated on real hardware with an Xbox pad and a DualSense, with Steam running and with it closed.

### M1: MVP, "Steam and desktop games, fully on the couch"

- Manifest, `Service.qml`, overlay with Home (Recently played, All games) and a Library grid.
- Scanners: Steam (installed apps, Proton badge, non-Steam shortcuts) and `.desktop` games (native, Flatpak, GFN plugin entries, RetroArch launchers, Battle.net, Minecraft).
- Art from local caches only (Steam's `librarycache`, `.desktop` icons), with a generated typographic card as the fallback.
- Controller and keyboard navigation, launch, session tracking, return to Arcade on exit, idle inhibit.
- Global chords `GUIDE + START`, `GUIDE + B` (hold) and the emergency exit; keyboard bind `SUPER + CTRL + G`.
- `scripts/install.sh` and `uninstall.sh` (bind plus menu rows), README, `preview.png`.

**Acceptance:**

- `omarchy plugin add <repo> --enable && bash scripts/install.sh`, then `SUPER + CTRL + G` opens Arcade with no other setup.
- With 500 cached games, the first frame appears in under 150 ms after the bind, and scrolling stays at 60 fps on an Intel iGPU.
- Every action reachable with a controller is reachable with a keyboard, and vice versa (enforced by a checklist test).
- Launching a Proton game hides Arcade and focuses the game. Quitting the game brings Arcade back, focused on the same card, within 2 s.
- Switching the Omarchy theme while Arcade is open re-colors it with no restart.
- `uninstall.sh` followed by `omarchy plugin remove` leaves no managed blocks, no processes and no binds behind.
- Steam scanner fixture tests cover multiple library folders, a Flatpak Steam, and binary `shortcuts.vdf`.

### M2: Every PC source, art and details

- Scanners for Heroic (Epic, GOG, Amazon, sideloaded; native and Flatpak), Legendary, Lutris, Bottles, itch, and Omarchy web apps (Xbox Cloud).
- Dedupe: a `.desktop` entry that wraps a Steam, Heroic or Lutris game merges into the source game. The same title from two stores becomes one card with a "Play on…" picker.
- SteamGridDB art (portrait, hero, logo) with an on-disk cache and rate limiting, using the user's own key (see Q6).
- A Game details screen: hero, playtime, last played, source, favorite, hide, "open in launcher".
- Search with an on-screen keyboard; sort and filter.
- Background rescans on change: watch the Steam `steamapps/`, Heroic `installed.json`, Lutris `pga.db` and `applications/` directories through `FileView`/inotify, with no polling.

**Acceptance:**

- On a fixture home with one game from each source, every one appears exactly once with art and launches.
- A rescan after installing a game in Steam or Heroic shows it within 5 s without reopening Arcade.
- With no network or SGDB key, nothing breaks; typographic cards show.

### M3: Combo engine, Quick Menu and config

- Full chord engine: tap, hold, repeat, chord windows, latch-until-release, multi-pad.
- The in-game Quick Menu panel; the cheat sheet; glyph sets that follow the last-used pad or keyboard.
- `arcade.toml` with live reload and validation errors shown in Settings; a Settings screen with a controller tester and a binding viewer.
- Per-game options: fullscreen policy, run in nested Gamescope, MangoHud, extra environment and arguments.
- Integrations: pause Controller Control while Arcade is open; call `silvaio.gamemode` `toggleMode` for "Performance session" when it is installed; optional key-lock submap.
- Optional SDL3 `ctypes` input backend for unmapped pads.

**Acceptance:**

- Engine unit tests cover chord resolution, including `A` and `A + B` coexisting, and hold versus tap, using virtual-pad fixtures.
- In a running game, `GUIDE` tap opens the Quick Menu over a fullscreen game within 150 ms, and `B` returns focus to the game.
- A malformed `arcade.toml` never crashes the daemon. The last good config stays active, and the error is reported.
- Each default chord has a test and a doc row.

### M4: Emulation and streaming

- RetroArch playlists (`~/.config/retroarch/playlists/*.lpl`) as a source, with system grouping.
- An opt-in ROM folder scan of `~/Games/roms/<system>/`, with a built-in extension-to-core table that uses Omarchy's preinstalled cores (`omarchy-games-retro-cores`).
- Optional import of ES-DE `gamelist.xml` metadata when present.
- Moonlight hosts and apps as a "Stream" shelf; the GeForce NOW library beyond the GFN plugin's added titles (see Q7).

**Acceptance:**

- A ROM dropped into `~/Games/roms/snes/` appears under "SNES" after a rescan and launches in RetroArch with the right core.
- Emulation can be fully disabled, and when disabled it costs nothing (no scan, no shelf).

### M5: Polish and publishing

- Big-screen mode: choose the TV output, scale presets, and an optional automatic open on pad connect (Q8).
- Motion pass following Omarchy's `motion.md` rules (`Style.duration`, `Style.easeOut`, and reduce-motion respected).
- Performance budgets in CI (scanner time on a 2 000-game fixture, QML load), and translations through the shell's `I18n` if it is exposed to plugins.
- Optional InputPlumber "exclusive chords" mode.
- Listing on plugins.omarchy.org.

**Acceptance:**

- Full scan of a 2 000-game fixture in under 2 s; idle CPU of the daemon under 0.1 % when no pad is connected.
- The listing is live, and the install instructions work verbatim on a fresh Omarchy install.

## 7. Integrations with the existing Omarchy gaming plugins

| Plugin | Integration |
|---|---|
| `matt-dance.gfn-omarchy` (GeForce NOW Menu) | Its `gfn-*.desktop` files (`X-Omarchy-Plugin`, `X-GFN-CmsId`, `X-GFN-AppStore`) become a "GeForce NOW" source with the box art from `Icon=`. Arcade launches through its `scripts/gfn-play.sh`, so busy-window handling and WirePlumber recovery are reused. An "Add from GeForce NOW…" tile summons the GFN overlay. Both menu extensions share the `gaming` root key, and the installers skip a key the other already owns |
| `silvaio.gamemode` (Game Mode Switcher) | An optional "performance session" while a game runs (do not disturb, animations off, power profile), delegated over its IPC instead of duplicated. A Steam "Gaming Mode" tile uses its Gamescope/Big Picture flow |
| `co.klair.controller-control` | Paused while Arcade is open; chord conflicts surfaced in Settings |

## 8. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| A bug in our QML hangs or crashes the whole `omarchy-shell` (bar, notifications, lock) | High | All I/O and parsing in subprocesses; virtualized views; async image decoding; a hard cap on in-memory art; a soak test |
| The third-party plugin facade lacks an API we need (for example an idle inhibitor, layer config or Hyprland events) | High | Proven in M0 before any UI work. Quickshell types (`IdleInhibitor`, `WlrLayershell`, `Quickshell.Hyprland`) are importable directly; the fallback is a tiny `systemd-inhibit`/`hyprctl` path through the daemon |
| The Guide button is also captured by Steam | Medium | Setup guidance, a configurable modifier, the `SELECT` fallback |
| Chords leak into games without a grab | Medium | Harmless default partners, hold for destructive actions, optional InputPlumber mode later |
| Game exit detection is wrong for launchers that hand off (Steam, Heroic, Battle.net, GFN) | Medium | Per-source strategies (Steam `reaper` AppId, a window-class map, scope membership), plus a manual "I'm done" in the Quick Menu |
| On-disk formats change (Steam `librarycache` layout, Heroic file paths) | Medium | Fixture tests per source version; scanners fail soft per source with a visible "Steam: couldn't read library" notice |
| The Omarchy plugin API changes (Quattro is young) | Medium | Pin a minimum Omarchy version in the README; CI runs `omarchy plugin validate` and `qmllint` against Omarchy's `shell/` |
| SteamGridDB terms and rate limits | Low | The user's own key, caching, and a polite request rate |
| Multi-monitor and TV focus quirks | Low | `open_on` setting; tested in M5 |

## 9. Decisions (locked)

| # | Topic | Decision |
|---|---|---|
| Q1 | Name | **Omarchy Arcade** (`matt-dance.arcade`) |
| Q2 | Helper language | **Python stdlib**, no compile step |
| Q3 | Combo engine | **Build our own** |
| Q4 | Keyboard bind | **`Super + Ctrl + G`** |
| Q5 | Guide tap | **Opens the Arcade quick menu** (or Arcade when idle) |
| Q6 | SteamGridDB | **Optional**, user's own key; fall back to local art |
| Q7 | GeForce NOW | **Only** titles added through the GFN Menu plugin |
| Q8 | Auto-open on connect | **Off by default**, config option |
| Q9 | Workspace | Games launch on the **current workspace** |
| Q10 | Emulation | **RetroArch + ROM folders only** |
| Q11 | Distribution | Repo **omarchy-arcade**, GFN integration **optional** |
