# Omarchy Arcade: Roadmap

A prioritized list of improvements based on a full read of the codebase:
`Arcade.qml`, `QuickMenu.qml`, `Service.qml`, `ArcadeModel.js`, the `arcade`
Python package (`daemon`, `session`, `combos`, `linux_input`, scanners,
`meta/*`, `sysmenu`), `bin/*`, `scripts/install.sh` and the tests.

Items are ranked by user impact. Real bugs come first, then controller UX,
then features. Each item lists where the problem is and what changes.

Status key: **Done (PR)** means a PR is open with the change. **Planned** means
not started.

---

## 1. Session tracking pops Arcade over running games (bug, high)

**Problem.** `SessionTracker.poll()` (`arcade/session.py`) cannot tell when
most games are really running:

- Every Steam, Heroic, Lutris, Legendary, itch and GeForce NOW entry is
  `handoff = true`. For those, the comment says exit is "detected by the QML
  Hyprland watcher", but no such watcher exists. Every handoff launch sits in
  `starting` for 90 s. Then the tracker reports `exited`, and `Service.qml`
  sends **"Game ended"** and re-summons Arcade **on top of the game**.
- `.desktop` launches (World of Warcraft through umu, Battle.net, Flatpak
  games) go through `gio launch`, which returns at once. The tracker reads
  that as the game exiting. Arcade comes back right after launch.
- After a false exit the session is `idle`, so a Guide tap toggles Arcade
  instead of opening the system menu. Close game / Force quit kill only the
  (empty) launcher scope.
- For non-handoff games, `poll()` runs `systemctl --user is-active` on every
  daemon loop iteration (up to 20 forks a second for the whole session), and
  the result is never used because `mark_running()` is never called.
- A failed launch (unknown id, daemon error) leaves `Service.sessionState`
  stuck at `starting`, so every later launch says "Already playing".

**Change.** Track by evidence, polled every ~1.5 s instead of every loop:
the Hyprland window class (`steam_app_<id>`, `StartupWMClass`, GFN), Steam's
`reaper SteamLaunch AppId=<id>` process, the launch scope or direct child, and,
as a last resort, a new window that appeared after launch. States are
`starting → running → exited`. A handoff that never shows evidence becomes
`lost` (stop tracking quietly, no "Game ended", no re-summon). Close game
closes the tracked window. Force quit kills the tracked pids. Launch errors
reset the session. The system menu hides Close game / Force quit when nothing
is running.

**Status: Done (PR A, session tracking).**

## 2. Play history for every game, not only Steam (feature, high)

**Problem.** Home's "recently played first" order uses `lastPlayed`, which
comes only from Steam's `localconfig.vdf`. World of Warcraft, Battle.net,
GeForce NOW and Heroic titles never appear as recent, however often they are
played. `ARCHITECTURE.md` describes a `state.json` with Arcade's own play
history, but nothing writes it.

**Change.** `arcade/state.py` owns `${XDG_STATE_HOME}/matt-dance.arcade/state.json`.
The daemon records `lastPlayed` on every launch and adds the session's seconds
on exit. `arcade-scan` merges the newest `lastPlayed` (and Arcade playtime
when the store has none) into `library.json`, and the overlay overlays the
same file live so the Home row reorders as soon as you come back from a game.

**Status: Done (PR C, library state).**

## 3. Controller navigation: hold-to-repeat and the left stick (UX, high)

**Problem.** In UI mode `arcaded` emits one `nav` event per D-pad press.
`repeat` is always `false`, so moving through a 100-game library means 100
presses. The left stick does nothing in Arcade, although `ARCHITECTURE.md`
describes a 35 % dead zone with 400/110 ms repeat. Two related daemon bugs:
`refresh_devices()` re-emits `pads` every 2 s, and with
`auto_open_on_connect = true` it toggles Arcade **every 2 s** while a pad is
connected. `README` says `arcade.toml` "reloads live", but `Service.qml`
never sends `reload`.

**Change.** A `NavRepeater` in the daemon turns D-pad and left stick (with
`stick_deadzone`, using each device's `EVIOCGABS` range) into nav events with
`repeat_delay_ms` / `repeat_interval_ms` auto-repeat. `pads` is sent only
when the set changes. Auto-open fires only when a new pad is connected. The
service watches `arcade.toml` and sends `reload`. While you scroll, the
overlay waits a moment before fetching metadata, so holding right does not
start a stream of `arcade-meta` processes.

**Status: Done (PR B, controller navigation).**

## 4. Search that works from a controller (UX, high)

**Problem.** `Y` switches to the search screen but there is no way to type
without a keyboard. With a keyboard there are focus bugs: once the search
box has focus, Enter, Esc and the arrow keys never reach the key handler
(it is a sibling item, not an ancestor), so you cannot leave search or
launch a result without the mouse. Typing `s` to start a search is swallowed
by a dead `Key_S` branch.

**Change.** An on-screen keyboard (`Osk.qml`) opens on `Y` when the request
came from a pad: D-pad to move, A to type, X backspace, Y space, B or Start to
close. Results update live and you can navigate them right away. The search
field forwards navigation keys to the same handler as the rest of the
overlay. The `s` key starts a search like any other letter.

**Status: Done (PR B, controller navigation).**

## 5. Favorites, hide, sort and filter (feature, high)

**Problem.** The daemon already emits `favorite` (R3) and `sort` (Select)
intents, but the overlay ignores them. There is no way to pin a game, hide a
launcher or tool you do not want, or sort the Library by anything other than
title. Options (X) only opens the Play on… picker, and only for merged titles.

**Change.** A per-game **Options** sheet (X) with Play on…, Favorite, Hide
and Refresh metadata. R3 toggles favorite and Select cycles the Library sort
(A–Z, Recently played, Most played, Source). A filter row (All, Favorites,
Steam, GeForce NOW, …, Hidden) is reachable with LT/RT. Home order becomes
recently played, then favorites, then the rest. All of this lives in
`state.json`, so it survives rescans and cache wipes.

**Status: Done (PR C, library state).**

## 6. In-app setup for IGDB and SteamGridDB keys (feature, medium-high)

**Problem.** Better art and non-Steam metadata need keys in
`~/.config/matt-dance.arcade/keys.json`, which means a terminal, a text editor
and `chmod 600`. Arcade never tells you whether a key works. Adding a key
later has no effect for 14 days, because cached metadata is still "fresh".
Changing the Twitch client keeps a cached IGDB token for the old client.

**Change.** Settings gets a **Metadata keys** section that shows whether each
key is set, never its value. **Paste from clipboard** (`wl-paste`, run by
Python so the secret never goes through QML or argv) works from a pad.
Typing works too. **Test** checks each key against its API. Keys are written
atomically with mode 0600. A **Remove** option and a link to each provider's
key page are included, plus a terminal fallback (`bin/arcade-keys setup`). A
one-time Home card on first run points to it, and the system menu gets an
**Arcade › Metadata keys** row. Saving clears the IGDB token cache. Cached
metadata that was fetched without a provider that is now configured is
refreshed instead of waiting 14 days. Everything still works with no keys.

**Status: Done (PR D, API keys).**

## 7. Per-game launch options (feature, medium)

Per-game environment variables (`MANGOHUD=1`, `PROTON_ENABLE_WAYLAND=1`,
`DXVK_HUD`), wrappers (`gamemoderun`, `mangohud`, `gamescope -f -- %command%`)
and extra arguments, edited from the Options sheet and stored in `state.json`.
`session.py` already accepts `LaunchSpec.env`. Wrappers only apply to `argv`
and `.desktop` launches. Steam and Heroic own their own launch options, so for
those the sheet should say so instead of silently doing nothing.

**Status: Planned.**

## 8. Rendering cost on large libraries (performance, medium)

Every Home and Library delegate calls `Model.lookupMeta`, `coverUrl` and
`isSmallArt` three or four times per binding. `rememberMeta` copies the whole
`metaById` map for every ingested record, which re-evaluates every delegate.
`refreshList()` writes a `console.warn` on every call. Batch the meta ingest
(one copy per `--cached-art` payload), cache the resolved cover per delegate
in a property, and keep the noisy log behind a debug flag.

**Status: Partly done.** PR B debounces metadata fetches while scrolling, and
PR C stops logging on every list refresh. Memoizing the delegates is planned.

## 9. Show scan errors and source counts in Settings (UX, medium)

`library.json` carries per-source `errors` (bad VDF, unreadable Lutris DB),
but Settings never shows them. Settings should list each source with its game
count and last error, and offer a **Rescan** action you can reach with a pad
(today it is only on F5, the IPC call, or the Omarchy menu).

**Status: Planned.**

## 10. Daemon restart backoff and controller glyphs (polish, low)

`Service.qml` restarts `arcaded` every 3 s forever, even when it crashes in a
loop. It should back off (3 s, 6 s, 12 s, … up to 60 s) and show the last
stderr line in Settings. The hint bar always shows Xbox letters. The daemon
already reports each pad's `kind`, so the hint bar should show
Cross/Circle/Square/Triangle for PlayStation pads and swap the A/B labels for
Nintendo pads.

**Status: Planned.**
