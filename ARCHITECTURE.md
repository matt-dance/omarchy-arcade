# Omarchy Arcade: Architecture

This document describes how Arcade is built. [`PLAN.md`](PLAN.md) covers scope, milestones and open questions.

## Process and surface layout

```text
omarchy-shell (Quickshell, Qt 6, one long-lived process)
└── plugin matt-dance.arcade  (~/.config/omarchy/plugins/matt-dance.arcade/)
    ├── Service.qml       kind: service, keepLoaded
    │   ├── IpcHandler target "matt-dance.arcade": toggle | open | close | rescan | status | action <name>
    │   ├── Process: bin/arcaded --exit-with-stdin   (long-lived, JSON lines both ways)
    │   ├── Process: bin/arcade-scan --json          (one-shot, on open/rescan/file change)
    │   ├── Process: bin/arcade-art <ids…>           (one-shot batches, low priority)
    │   ├── Process: bin/arcade-meta <ids…>          (one-shot, metadata cache, never on the UI thread)
    │   ├── Hyprland event stream (Quickshell.Hyprland) for window open/close/focus
    │   ├── IdleInhibitor while Arcade is open or a tracked game runs
    │   └── FileView watches: arcade.toml, library sources, theme changes are automatic
    ├── Arcade.qml        kind: overlay   full-screen library on the overlay layer
    │                     also reads library.json + runs arcade-scan if the service is absent
    └── QuickMenu.qml     in-game side sheet (child of Arcade.qml, not a plugin kind)

bin/arcaded (Python 3 stdlib)
├── input/     evdev discovery (inotify on /dev/input), capability filter, per-device reader
├── combos/    chord recogniser: tap, hold, repeat, chord window, latch-until-release
├── session/   launch through systemd-run scope, pidfd exit wait, Steam reaper watch
├── uinput/    optional virtual keyboard, only for bindings with `keys =`
└── config/    tomllib loader, defaults + user merge, validation report
```

### Why this split

- **QML holds no blocking work.** File parsing, SQLite, HTTP and evdev all run in subprocesses, because a stall in QML freezes Omarchy's bar and notifications.
- **One long-lived daemon, not several.** Input and session tracking both need to outlive the overlay, and both block on file descriptors (`select` on evdev, inotify and pidfds). The daemon uses no timers while idle, which keeps to Omarchy's "react to events, never poll" rule.
- **Scanners run one-shot.** They do heavy I/O for a second, then exit. They are not resident.
- **Daemon lifetime is tied to the shell.** The service holds the daemon's stdin. When the shell exits or reloads, stdin closes and the daemon exits, so there are never two daemons firing each chord twice. This is the pattern Controller Control uses, and it is a good one.

## Wire protocol (daemon ⇄ service)

The daemon and the service exchange newline-delimited JSON. Each message carries a `t` type field.

Daemon to service:

```json
{"t":"hello","version":1,"pid":1234}
{"t":"pads","pads":[{"id":"usb-045e:0b12","name":"Xbox Wireless Controller","kind":"xbox","virtual":false}]}
{"t":"nav","dir":"down","repeat":true}
{"t":"intent","name":"accept"}            // accept|back|options|search|menu|tab_next|tab_prev|page_up|page_down|favorite|sort
{"t":"action","name":"arcade.toggle"}     // a global chord fired
{"t":"glyphs","set":"playstation"}        // last-used pad changed
{"t":"session","state":"running","game":"steam:1245620","pid":5678}
{"t":"session","state":"exited","game":"steam:1245620","code":0,"seconds":3121}
{"t":"config","ok":false,"errors":["bindings.\"GUIDE + Q\": unknown button Q"]}
```

Service to daemon:

```json
{"t":"mode","ui":true}                    // Arcade visible: emit nav/intents; else only global chords
{"t":"launch","game":"steam:1245620","argv":["steam","steam://rungameid/1245620"],"track":{"steam_appid":1245620}}
{"t":"close","game":"steam:1245620","force":false}
{"t":"reload"}
```

`exec` and `keys` actions from bindings run inside the daemon, so they work even while the overlay is not loaded. Actions that are Arcade-internal, such as `arcade.toggle` or `game.close`, go to the service.

## Unified game model

```jsonc
{
  "id": "heroic:gog:1207658924",        // "<source>:<sub>:<native id>", stable across scans
  "title": "The Witcher 3: Wild Hunt",
  "sortTitle": "witcher 3 wild hunt",
  "source": "heroic",                   // steam|heroic|legendary|lutris|bottles|itch|desktop|gfn|retroarch|roms|moonlight|webapp
  "store": "gog",                       // steam|epic|gog|amazon|itch|gfn|xbox-cloud|battlenet|null
  "runner": "proton",                   // native|proton|wine|flatpak|emulator|cloud|stream
  "platform": null,                     // for emulation: "snes", "psx", …
  "installed": true,
  "launch": { "kind": "uri", "value": "heroic://launch?appName=1207658924&runner=gog" },
  "track":  { "windowClass": null, "steamAppId": null, "handoff": true },
  "art": { "cover": "file://…/cover.webp", "hero": null, "logo": null, "icon": "…" },
  "steamAppId": 292030,                 // when known, for SteamGridDB lookup and dedupe
  "playtimeMinutes": 5120,
  "lastPlayed": "2026-10-20T21:14:00Z",
  "dedupeKeys": ["title:witcher3wildhunt", "steam:292030"],
  "alsoOn": [                           // filled by the merger: other sources of the same game
    { "id": "gfn:gfn-107820252", "source": "gfn", "title": "Enshrouded", "launch": { "kind": "desktop", "value": "…" } }
  ]
}
```

- **Library cache:** `${XDG_CACHE_HOME}/matt-dance.arcade/library.json`. It is rebuilt by `arcade-scan` and atomically replaced.
- **Metadata cache:** `${XDG_CACHE_HOME}/matt-dance.arcade/meta/<id>.json` plus images in `meta/<id>/`. Written by `arcade-meta`. Fresh for 14 days; stale cache is still shown while a refresh runs.
- **User state:** `${XDG_STATE_HOME}/matt-dance.arcade/state.json` holds favorites, hidden games, per-game options, Arcade's own last-played times and playtime, and the "Play on" preference. It survives rescans and cache wipes.
- **Merging:** a `.desktop` entry whose `Exec` launches `steam://rungameid/`, `heroic://`, `lutris:rungameid/` or `itch://` is folded into that source's entry. Titles that match after normalization (including stripping a `GFN - ` prefix) across different stores collapse into one card with `alsoOn` launch payloads for the Play on… picker.

## Scanners

Each scanner is a pure function, `scan(home, env) -> list[Game]`, that never raises. Failures become `{"source":"steam","error":"…"}` entries, which Settings shows. Every scanner checks both the native and the Flatpak location.

| Source | Where we read | Launch | Exit tracking |
|---|---|---|---|
| Steam | `~/.local/share/Steam`, `~/.steam/steam`, `~/.var/app/com.valvesoftware.Steam/.local/share/Steam`. `steamapps/libraryfolders.vdf` → each library's `appmanifest_*.acf` (installed when `StateFlags` has bit 4). Tools such as Proton, Steam Linux Runtime and Steamworks redistributables are filtered by appid list and `type`. `userdata/<id>/config/shortcuts.vdf` (binary VDF) holds non-Steam shortcuts. `localconfig.vdf` has playtime and last played. `config.vdf` `CompatToolMapping` gives the Proton badge | `steam steam://rungameid/<appid>`. For shortcuts, the game id is `(shortcutAppId << 32) \| 0x02000000` | `reaper SteamLaunch AppId=<id>` process via pidfd, plus the `steam_app_<id>` window class |
| Heroic | `~/.config/heroic` or `~/.var/app/com.heroicgameslauncher.hgl/config/heroic`: `legendaryConfig/legendary/installed.json` (Epic), `gog_store/installed.json` plus `gog_store/library.json` (GOG), `nile_config/nile/installed.json` (Amazon), `sideload_apps/library.json`. Art from the `store_cache/*library*.json` URLs | `heroic://launch?appName=<id>&runner=<legendary\|gog\|nile\|sideload>` through `xdg-open` (version-checked, with the older `heroic://launch/<runner>/<id>` as a fallback) | Hand-off: a new window plus a matching process within N seconds, then pidfd |
| Legendary (standalone) | `~/.config/legendary/installed.json` | `legendary launch <app>` | Scope |
| Lutris | `~/.local/share/lutris/pga.db` (SQLite, `games` where `installed = 1`), Flatpak `~/.var/app/net.lutris.Lutris/data/lutris`. Covers in `coverart/<slug>.jpg`, banners in `banners/` | `lutris lutris:rungameid/<id>` | Hand-off via `lutris-wrapper` process, pidfd |
| Bottles | `~/.local/share/bottles/bottles/*/bottle.yml` → `External_Programs`, plus the Flatpak data dir | `bottles-cli run -b <bottle> -p <program>`, or `flatpak run --command=bottles-cli com.usebottles.bottles …` | Scope |
| itch | `~/.config/itch/db/butler.db` (SQLite: `caves` joined to `games` for title and `cover_url`) | `xdg-open itch://caves/<caveId>/launch` | Hand-off |
| Desktop entries | `$XDG_DATA_DIRS/applications`, `~/.local/share/applications`, and the Flatpak exports (`/var/lib/flatpak/exports/share/applications`, `~/.local/share/flatpak/exports/share/applications`). Entries with `Categories` containing `Game`, minus `NoDisplay`/`Hidden`, minus the launchers themselves (Steam, Heroic, Lutris, Bottles, itch). Recognized special cases: **GFN** (`X-Omarchy-Plugin=matt-dance.gfn-omarchy`, `X-GFN-*`), **RetroArch game launchers** (`Categories=Game;Emulator;`), **Battle.net** (`omarchy-launch-battlenet`), **Minecraft**, **Xbox Cloud** and other cloud web apps (`omarchy-launch-webapp` with a known URL, regardless of categories) | `gio launch <file>`-equivalent: parse `Exec`, strip field codes, run in a scope. GFN entries keep their own `gfn-play.sh` | Scope, or the window class for web apps and GFN |
| RetroArch playlists (M4) | `~/.config/retroarch/playlists/*.lpl` (JSON: `path`, `label`, `core_path`, `db_name`) | `retroarch -L <core> <rom>` | Scope, `com.libretro.RetroArch` |
| ROM folders (M4) | `~/Games/roms/<system>/*` with an extension-to-system-to-core table (Omarchy layout) | Same as above | Scope |
| Moonlight (M4) | `~/.config/Moonlight Game Streaming Project/Moonlight.conf` hosts and apps | `moonlight stream <host> <app>` | Scope |

The binary VDF and text VDF/ACF parsers are about 150 lines of our own code, with fixture tests. We copy nothing from GPL projects.

## Game metadata

`bin/arcade-meta` fills the Home detail panel. It is a one-shot subprocess (same rule as scan/art): QML never does HTTP or JSON parsing of store APIs.

1. **Cache first.** `~/.cache/matt-dance.arcade/meta/<id>.json` (colons in the game id become `_`). If `fetchedAt` is newer than 14 days, return it. Local Steam playtime from `localconfig.vdf` is overlaid on every read.
2. **Steam store** (`https://store.steampowered.com/api/appdetails`) when a Steam appid is known: short description, genres, developers/publishers, release date, Metacritic, screenshots. GFN titles with `store=Steam` (or no appid yet) go through the store search API and cache the mapped appid.
3. **ProtonDB** summary API for that appid (Linux compatibility tier).
4. **Local Steam playtime / last played** from `userdata/<id>/config/localconfig.vdf`.
5. **IGDB** via Twitch client credentials, only when both keys are set. Used for non-Steam *games* (World of Warcraft, desktop titles) and to fill gaps. Match is exact normalized title only — a contains match would map the Battle.net launcher onto *Warcraft II: Battle.net Edition*. Known launchers (Battle.net, Steam, Lutris, Heroic, EA app, Ubisoft Connect, GOG Galaxy, GeForce NOW client) skip IGDB and get a short launcher description instead.
6. **SteamGridDB**, only when a key is set. Grid / hero / logo. Preferred over a weak icon-only cover (the WoW `.desktop` icon case, and launchers such as Battle.net). Steam `librarycache` 600×900 art is left alone. Every Home and Library card renders `meta.art.cover` when present (from an in-memory `metaById` map hydrated off the disk cache), even if the library row is still `iconOnly`.

Missing sources are skipped; errors are recorded without secrets. `--offline` uses cache + local playtime only. The overlay `FileView`s the selected game's meta JSON and starts `arcade-meta <id>` if it is missing or stale. The service prefetches the eight most recently played games after a scan.

Optional keys live only in `~/.config/matt-dance.arcade/keys.json` (fields `steamgriddb_api_key`, `twitch_client_id`, `twitch_client_secret`) with env-var overrides `ARCADE_STEAMGRIDDB_API_KEY`, `ARCADE_TWITCH_CLIENT_ID`, `ARCADE_TWITCH_CLIENT_SECRET`. The repo ships `keys.example.json` with empty values. If the keys file is group/world readable, Arcade warns and tells the user to `chmod 600` it. Key values are never logged.

Home UI: a horizontal game row on top; the bottom panel keeps art, title, source list and Play, then shows a clamped description, genre/developer chips, release year, rating, playtime, last played, a ProtonDB badge and a screenshot strip. Empty fields are hidden. The detail panel is a `BorderSurface` using `Border.hyprlandActiveSpec` (theme accent / Hyprland active-border color and width, `Style.cornerRadius` matching window rounding). Hero art is clipped inside that border.

## Artwork pipeline

Arcade resolves each art slot (cover 600×900, hero 1920×620, logo, icon) in order, stopping at the first hit:

1. **The source's local cache.** Steam's `appcache/librarycache/<appid>/` (newer per-app folders and older flat `<appid>_library_600x900.jpg`), Steam custom grids in `userdata/<id>/config/grid/`, Heroic and Lutris caches, the GFN `Icon=` box art.
2. **SteamGridDB**, when a key is configured. Lookup goes by Steam appid when known, otherwise by a title search with the top match verified by normalized title. Requests run about 4 per second with exponential back-off.
3. **A generated typographic card.** This is a QML component, not an image: the title in the Omarchy monospace font on the theme's background, with an accent rule and a source glyph. It re-colors with the theme, and it is the deliberate "Omarchy look" fallback, not a placeholder.

Downloads are written to `${XDG_CACHE_HOME}/matt-dance.arcade/art/<id>/<slot>.<ext>` atomically. QML loads them with `asynchronous: true`, `sourceSize` set to the card size, and `cache: false` for offscreen delegates.

## Session tracker state machine

```text
idle ──launch──▶ starting ──evidence seen──▶ running ──no evidence for 2 polls──▶ exited ──▶ returning ──▶ idle
  ▲                 │ launcher exit ≠ 0 → exited (failed): "Couldn't start", return to Arcade
  │                 │ no evidence after 180 s (hand-off) / 90 s → lost: stop tracking quietly
  └─────────────────┘
```

- **`starting`.** The overlay is hidden, idle is inhibited, and a toast reads "Launching …".
- **Evidence** (polled every 1.5 s by `arcade/session.py`, not on every daemon loop): a Hyprland client whose class matches `track.windowClass` (`steam_app_<id>`, a `.desktop` `StartupWMClass`, `GeForceNOW`) or `steam_app_<steamAppId>`; Steam's `reaper SteamLaunch AppId=<id>` process; the launch scope or direct child for in-place launches; and, as a last resort while starting, a window that appeared after launch and is not a launcher (Steam, Heroic, Lutris, …).
- **Hand-off.** `uri` and `desktop` launches, `uwsm-app`, and scanners that set `track.handoff` return immediately while the game keeps running elsewhere. Their launcher exit code 0 means nothing. A non-zero exit code means the launch failed.
- **`running`.** Global chords and the Quick Menu are active. Optionally the key-lock submap or the Game Mode Switcher performance session is on.
- **`lost`.** No evidence ever showed up (for example an unknown window class and the window was already open). Arcade stops tracking without "Game ended" and without re-summoning itself over the game.
- **`returning`.** Arcade restores the workspace, re-summons the overlay, restores focus to the launched card, records playtime, and releases the inhibitor.
- **Close game.** Arcade sends `closewindow` to the tracked window's address and `SIGTERM` to the launch scope. **Force quit** sends `SIGKILL` to the scope, the tracked window's pid, Steam's reaper for the app, and all their descendants.

## Input and chord engine

- **Discovery.** On start and on inotify events in `/dev/input`, the daemon opens `event*` nodes that report `EV_KEY` with `BTN_GAMEPAD` or `BTN_SOUTH` plus `EV_ABS`. It skips touchpads and the DualSense motion sensor nodes. Device inspection is cached per node.
- **Normalization.** `BTN_SOUTH` maps to `A` and `BTN_EAST` to `B`. For Nintendo pads, the kernel's positional mapping is used and glyphs are swapped in the UI only. The D-pad is accepted from either `ABS_HAT0X/Y` or `BTN_DPAD_*`. Triggers are analog, with a press threshold at 60 %. Sticks produce navigation with a 35 % dead zone, a 400 ms initial repeat and 110 ms repeats after that.
- **Steam virtual pad rule.** `28de:11ff` devices are ignored while any physical gamepad is present. They are used when they are the only pad, which covers the Steam Controller and Deck while Steam runs.
- **Chord rules,** compatible with Controller Control's semantics, so users of both get one mental model:
  - A binding fires on press, unless a longer binding containing the held set exists. In that case Arcade waits up to `combo_window_ms`.
  - A fired chord latches until one of its buttons is released, and never fires its parts on release.
  - `hold = true` fires after `hold_ms` and shows a progress ring in the UI.
  - `repeat = true` repeats while held.
  - A tap of the modifier alone fires its `tap` action on release, only if no chord fired.
- **Modes.** When `ui = true`, all buttons produce intents and the global chords still apply. When `ui = false`, only modifier chords are recognized. In both cases the daemon reads without grabbing.

## Theming

The overlay uses only shell tokens:

- **Surfaces:** `Commons.Color.menu.background`, `.text`, `.border`, `.scrim`, `.selectedBackground` and `.selectedText`. Card focus rings use the `[controls]` focus tokens (`focus-color`, `focus-border` with gradients through `BorderSurface`), so a theme's gradient border shows on the focused game. The Home detail panel uses `Border.hyprlandActiveSpec(Commons.Color.accent, …)` so it tracks the current theme's Hyprland active window border (color and thickness) and `Style.cornerRadius` (Hyprland `decoration:rounding`). No hardcoded hex colors.
- **Type:** `Style.font.*`, scaled by `ui.scale` for 10-foot viewing. The family is the user's `monospace`, which makes Arcade look unmistakably Omarchy next to Big Picture.
- **Spacing:** `Style.spacing.*` and `Style.space(px)`. Radius: `Style.cornerRadius`.
- **Motion:** every animation goes through `Style.duration(ms)` with `Style.easeOut`. Reduce-motion is honored automatically.
- **Backdrop:** the current wallpaper (Omarchy's background), blurred and dimmed by the menu scrim, or the focused game's hero art crossfaded over it.
- **Live switching:** theme switches push through `applyTheme`, and the singletons update bindings, so Arcade needs no code for it.

## Integration files written by `scripts/install.sh`

All writes are idempotent, support `--dry-run`, make a `.bak.<timestamp>` backup before changing a user file, and are reversed by `scripts/uninstall.sh`.

| Target | What |
|---|---|
| `~/.config/hypr/arcade.lua` | A whole file owned by the plugin: `o.bind("SUPER + CTRL + G", "Arcade", "omarchy-shell shell toggle matt-dance.arcade '{}'")`, plus the optional `XF86Game` bind. Omarchy's host prefers kind `panel` over `overlay` when both are declared and `toggle <id>` has no kind argument, so Arcade declares only `overlay` + `service` — this bind opens the library, not the Quick Menu. |
| `~/.config/hypr/hyprland.lua` | One managed line, `require("default.hypr.require_optional").module("hypr.arcade")`, so deleting the file can never break Hyprland's config |
| `~/.config/omarchy/extensions/omarchy-menu.jsonc` | A managed `BEGIN`/`END matt-dance.arcade` block: `gaming.arcade` (Open Arcade) and `gaming.arcade.rescan`. It reuses an existing `gaming` root, such as the one from the GFN plugin, instead of redefining it |
| `~/.config/omarchy/arcade/arcade.toml` | Created only if absent, as a commented copy of the defaults |

When Arcade is opened before `install.sh` has run (from the menu or IPC), Settings shows a "Finish setup" card. It runs the installer in `omarchy-launch-floating-terminal-with-presentation`, keeping Omarchy's "confirm in a terminal" ethos.

## Repository layout

```text
.
├── manifest.json
├── preview.png
├── Service.qml
├── Arcade.qml            overlay entry (library + hosts QuickMenu)
├── QuickMenu.qml
├── screens/            Home.qml, Library.qml, Details.qml, Search.qml, Settings.qml, Power.qml
├── ui/                 FocusGrid.qml, GameCard.qml, TypeCard.qml, Shelf.qml, HintBar.qml, Osk.qml, Glyphs.js
├── bin/                arcaded, arcade-scan, arcade-art, arcade-meta   (Python entry points, #!/usr/bin/python3)
├── arcade/             Python package: input/, combos/, session/, uinput/, config/, scanners/, art/, meta/, vdf.py, model.py
├── keys.example.json   empty optional API key template (never commit real keys)
├── default/arcade.toml
├── extensions/omarchy-menu.jsonc
├── hypr/arcade.lua
├── scripts/            install.sh, uninstall.sh
├── tests/              fixtures/<source>/…, test_*.py, test-install.sh
├── .github/workflows/test.yml   unit tests + `omarchy plugin validate` + qmllint against Omarchy's shell/
├── PLAN.md  ARCHITECTURE.md  COMPETITIVE_ANALYSIS.md  README.md  LICENSE
```

The tree contains no symlinks, as `omarchy plugin validate` requires. Bash follows Omarchy's style: `#!/bin/bash`, `[[ ]]` and `(( ))`, and `omarchy-notification-send` instead of `notify-send`.
