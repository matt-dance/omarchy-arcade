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
- **Browse:** D-pad / left stick / arrow keys / `hjkl`
- **Play:** `A` / Enter
- **Search:** `Y` / `/` then type
- **Home ↔ Library:** `LB` / `RB` / Tab
- **Settings:** `Start` / `M`
- **Close Arcade:** `B` / Esc from Home
- **While a game runs:** tap `Guide` for the Quick Menu (resume, volume, screenshot, close game, back to Arcade)

### Rescan

```bash
omarchy-shell shell call matt-dance.arcade rescan '{}'
# or from a checkout:
python3 bin/arcade-scan --json
```

Library cache: `${XDG_CACHE_HOME:-~/.cache}/matt-dance.arcade/library.json`

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

Without a key, Arcade uses local launcher art and themed typographic cards.

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
├── bin/arcade-art         # Optional SteamGridDB fetch
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
printf '{"t":"ping"}\n' | python3 bin/arcaded --plugin-dir .   # Ctrl+D to exit
```

On Omarchy:

```bash
omarchy plugin validate ~/.config/omarchy/plugins/matt-dance.arcade
qmllint -I "$OMARCHY_PATH/shell" Arcade.qml QuickMenu.qml Service.qml
```

## Hardware testing

These cannot be fully verified in CI. On a real Omarchy host with a controller:

1. **Plugin load** — `omarchy plugin validate` and enable; bar stays healthy
2. **Summon** — `Super + Ctrl + G` opens Arcade; Esc closes; theme switch recolors live
3. **Scan** — with Steam/Heroic/etc installed, games appear with covers
4. **Keyboard nav** — arrows/`hjkl`, Enter launch, `/` search
5. **Controller nav** — D-pad and stick move focus; A launches; B backs
6. **Guide chords** — `Guide+Start` toggles; volume/screenshot chords work; hold-B closes a game
7. **Guide tap** — opens Quick Menu over a running game; B resumes
8. **Steam Input coexistence** — no double input; with Steam running, physical pad preferred over virtual `28de:11ff`
9. **Launch/return** — Proton game hides Arcade, quitting returns focus to the same card within ~2s
10. **Idle inhibit** — browsing with only a controller for >3 minutes does not start the screensaver
11. **GFN** — titles added via GeForce NOW Menu appear under GeForce NOW and launch through `gfn-play.sh`
12. **Install/uninstall** — `install.sh` / `uninstall.sh` leave no leftover managed blocks

## Design docs

- [`PLAN.md`](PLAN.md) — stack, milestones, decisions
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — modules, wire protocol, scanners
- [`COMPETITIVE_ANALYSIS.md`](COMPETITIVE_ANALYSIS.md) — why we build

## License

MIT — see [LICENSE](LICENSE).
