# Omarchy Arcade

Controller-first game library for [Omarchy](https://omarchy.org) — Steam Big Picture energy, Omarchy native look.

| | |
|---|---|
| Manifest id | `matt-dance.arcade` |
| Display name | **Arcade** |
| Keyboard | `Super + Ctrl + G` |
| Controller | `Guide + Start` (open) · `Guide` tap (quick menu / Arcade) |

Finds games from Steam (including Proton and non-Steam shortcuts), Heroic (Epic/GOG/Amazon), Legendary, Lutris, Bottles, itch.io, Flatpak/native `.desktop` games, GeForce NOW titles added through [GeForce NOW Menu](https://github.com/matt-dance/omarchy-gfn-menu-plugin), RetroArch playlists, and optionally `~/Games/roms`.

> **Status:** M1 MVP + M2 scanners implemented. Python unit tests pass in CI. **QML, controller input, game launch/return, and idle inhibit need verification on a real Omarchy machine with a controller** (see [Hardware testing](#hardware-testing)).

## Install

Requires Omarchy with Quattro shell plugins (`omarchy-shell`).

```bash
omarchy plugin add https://github.com/matt-dance/omarchy-arcade.git --enable
bash ~/.config/omarchy/plugins/matt-dance.arcade/scripts/install.sh
```

Review-first:

```bash
omarchy plugin add https://github.com/matt-dance/omarchy-arcade.git
# inspect ~/.config/omarchy/plugins/matt-dance.arcade/
omarchy plugin enable matt-dance.arcade
bash ~/.config/omarchy/plugins/matt-dance.arcade/scripts/install.sh
```

`install.sh` is idempotent, supports `--dry-run`, backs up changed files, and:

1. Writes `~/.config/hypr/arcade.lua` (`Super + Ctrl + G`)
2. Appends a managed require block to `~/.config/hypr/hyprland.lua`
3. Merges Gaming › Arcade rows into `~/.config/omarchy/extensions/omarchy-menu.jsonc` (reuses an existing `gaming` root from the GFN plugin when present)

Plugins run **unsandboxed** inside `omarchy-shell`. Read the code before enabling.

### Local checkout

```bash
cp -a . ~/.config/omarchy/plugins/matt-dance.arcade
omarchy-shell shell rescanPlugins
omarchy plugin enable matt-dance.arcade
bash ~/.config/omarchy/plugins/matt-dance.arcade/scripts/install.sh
```

### Remove

```bash
bash ~/.config/omarchy/plugins/matt-dance.arcade/scripts/uninstall.sh
omarchy plugin remove matt-dance.arcade
```

## Usage

- **Open:** `Super + Ctrl + G`, Gaming › Arcade, or `Guide + Start` on a controller
- **Home:** horizontal row of larger covers (recently played first, then the rest of the library). The focused card scales up. The details pane below shows hero/banner art, title, source badges including merged **Play on…** stores, last played or playtime, and **Play** / **Options**
- **Browse Home:** D-pad left/right along the row, down into Play/Options, up back to the row. `A` plays, `X` opens Options (Play on… picker)
- **Library:** `LB` / `RB` / Tab keeps the grid
- **Search:** `Y` / `/` then type
- **Settings:** `Start` / `M`
- **Close Arcade:** `B` / Esc from the Home row
- **While a game runs:** tap `Guide` for the Steam Deck-style system menu (game, audio, display, Bluetooth, Wi-Fi, performance, capture, notifications, power). Power actions ask for **A** to confirm and **B** to cancel. Rows whose tools are missing stay hidden.

### Rescan

```bash
omarchy-shell shell call matt-dance.arcade rescan '{}'
# or from a checkout:
python3 bin/arcade-scan --json
```

Library cache: `${XDG_CACHE_HOME:-~/.cache}/matt-dance.arcade/library.json`

The overlay reads that file itself. If the service is missing, Arcade still shows the cached games and can scan/launch without it.

## Recovering a dead service

Omarchy keeps a loaded service instance across plugin file updates (`keepLoaded`). A service that **failed** to load (QML error) is not registered, but disable/enable does not always remount it, and there is no success log unless Arcade prints one.

After updating Arcade, or if Super+Ctrl+G shows Home with an empty library while `library.json` has games, or `pgrep -a arcaded` is empty:

```bash
omarchy-restart-shell
```

That is the reliable recovery. Then:

```bash
journalctl --user -n 80 --grep matt-dance.arcade
pgrep -a arcaded
python3 ~/.config/omarchy/plugins/matt-dance.arcade/bin/arcade-scan --json | head
```

You should see journal lines like:

- `matt-dance.arcade: service loaded; pluginDir=…`
- `matt-dance.arcade: starting arcaded /usr/bin/python3 …/bin/arcaded …`
- `matt-dance.arcade: arcaded starting pid=…`
- `matt-dance.arcade: arcaded hello pid=…`
- `matt-dance.arcade: overlay cache … games=5 service=yes`

`omarchy plugin disable matt-dance.arcade` then `enable` is worth trying, but **restart the shell** if arcaded still does not appear. A hot-reload after a failed QML load is not enough.

## Default controller bindings

Configured in `default/arcade.toml`. Override in `~/.config/omarchy/arcade/arcade.toml` (live reload). Set a binding to `false` to disable it.

| Chord | Action |
|---|---|
| `GUIDE + START` | Toggle Arcade |
| `GUIDE` (tap) | Quick Menu (in-game) or Arcade (idle) |
| `GUIDE + B` (hold) | Close game |
| `GUIDE + DPAD_UP/DOWN` | Volume up/down |
| `GUIDE + DPAD_LEFT/RIGHT` | Previous/next workspace |
| `GUIDE + RB` | Screenshot |
| `GUIDE + LB` | Start/stop recording |
| `GUIDE + Y` | MangoHud / performance overlay (`Shift_R+F12`) |
| `GUIDE + X` | Omarchy menu |
| `GUIDE + A` | Focus running game |
| `GUIDE + R3` | Mute mic |
| `GUIDE + SELECT` | Bindings cheat sheet flag |
| `GUIDE + SELECT + START` (hold 2s) | Emergency force-quit |

**Steam tip:** turn off Steam › Settings › Controller › “Guide button focuses Steam”, or set `modifier = "SELECT"` in your config.

## Optional SteamGridDB art

```bash
mkdir -p ~/.config/omarchy/arcade
echo 'YOUR_API_KEY' > ~/.config/omarchy/arcade/steamgriddb.key
omarchy-shell shell call matt-dance.arcade rescan '{}'
```

Without a key, Arcade uses local launcher art (Steam `library_hero` when present) and themed typographic cards. Home prefers SteamGridDB hero art, then the Steam library hero, then a dimmed cover.

## Optional ROM scan

In `~/.config/omarchy/arcade/arcade.toml`:

```toml
[sources]
roms = true
```

ROMs are read from `~/Games/roms/<system>/` (Omarchy RetroArch layout).

## Layout

```text
.
├── manifest.json          # Omarchy plugin manifest
├── Arcade.qml             # Fullscreen library overlay (the toggle target)
├── QuickMenu.qml          # In-game quick menu (hosted by Arcade.qml)
├── Service.qml            # keepLoaded service (daemon + library)
├── ArcadeModel.js
├── bin/arcaded            # Python stdlib daemon (evdev + session)
├── bin/arcade-scan        # One-shot library scan
├── bin/arcade-art         # Optional SteamGridDB cover + hero fetch
├── bin/arcade-sys         # System menu probes/actions (wpctl, nmcli, …)
├── arcade/                # Python package
├── default/arcade.toml
├── extensions/omarchy-menu.jsonc
├── hypr/arcade.lua
├── scripts/install.sh
├── scripts/uninstall.sh
├── tests/
├── PLAN.md
├── ARCHITECTURE.md
└── COMPETITIVE_ANALYSIS.md
```

## Development

```bash
export PYTHONPATH=.
python3 -m unittest discover -s tests -v
# or
./tests/run.sh

python3 bin/arcade-scan --json
python3 bin/arcade-sys items
printf '{"t":"ping"}\n' | python3 bin/arcaded --plugin-dir .   # Ctrl+D to exit
```

On Omarchy:

```bash
omarchy plugin validate ~/.config/omarchy/plugins/matt-dance.arcade
qmllint -I "$OMARCHY_PATH/shell" Arcade.qml QuickMenu.qml Service.qml
```

## Hardware testing

These cannot be fully verified in CI. On a real Omarchy host with a controller:

1. **Plugin load** — `omarchy plugin validate` and enable; bar stays healthy; journal shows `service loaded` and `starting arcaded`
2. **Summon** — `Super + Ctrl + G` opens Arcade; Esc closes; theme switch recolors live
3. **Scan** — with Steam/Heroic/etc installed, games appear with covers (from the service *or* `library.json` if the service is down)
4. **Keyboard nav** — arrows/`hjkl`, Enter launch, `/` search; Home down/up between the row and Play/Options
5. **Controller nav** — D-pad and stick move focus; A launches; B backs; Home left/right along the shelf
6. **Guide chords** — `Guide+Start` toggles; volume/screenshot chords work; hold-B closes a game
7. **Guide tap** — opens the system menu over a running game; B closes or cancels a power confirm; A confirms lock/suspend/restart/shutdown/log out
8. **System menu tools** — volume/mute/output (wpctl / omarchy-audio-*), brightness, night light, Bluetooth scan/pair, Wi-Fi picker, MangoHud, power profile, screenshot/record, do-not-disturb; missing tools stay hidden; battery shown for the machine and pads when sysfs exposes it
9. **Steam Input coexistence** — no double input; with Steam running, physical pad preferred over virtual `28de:11ff`
10. **Launch/return** — Proton game hides Arcade, quitting returns focus to the same card within ~2s
11. **Idle inhibit** — browsing with only a controller for >3 minutes does not start the screensaver
12. **GFN** — titles added via GeForce NOW Menu appear under GeForce NOW and launch through `gfn-play.sh`
13. **Install/uninstall** — `install.sh` / `uninstall.sh` leave no leftover managed blocks

## Design docs

- [`PLAN.md`](PLAN.md) — stack, milestones, decisions
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — modules, wire protocol, scanners
- [`COMPETITIVE_ANALYSIS.md`](COMPETITIVE_ANALYSIS.md) — why we build

## License

MIT — see [LICENSE](LICENSE).
