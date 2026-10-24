import QtQuick
import Quickshell
import Quickshell.Io
import "ArcadeModel.js" as Model

// Headless singleton: owns arcaded, library cache, launch/session, IPC.
Item {
  id: root

  property var shell: null
  property var manifest: null
  property string omarchyPath: Quickshell.env("OMARCHY_PATH")

  readonly property string pluginDir: {
    var home = Quickshell.env("HOME") || ""
    return home + "/.config/omarchy/plugins/" + Model.pluginId(root.manifest)
  }
  readonly property string cacheDir: {
    var xdg = Quickshell.env("XDG_CACHE_HOME")
    var home = Quickshell.env("HOME") || ""
    var base = (xdg && xdg.length) ? xdg : (home + "/.cache")
    return base + "/matt-dance.arcade"
  }
  readonly property string libraryFile: root.cacheDir + "/library.json"
  readonly property string daemonBin: root.pluginDir + "/bin/arcaded"
  readonly property string scanBin: root.pluginDir + "/bin/arcade-scan"
  readonly property string artBin: root.pluginDir + "/bin/arcade-art"

  property var games: []
  property var scanErrors: []
  property string lastAction: ""
  property string lastError: ""
  property string sessionState: "idle"
  property var sessionGame: null
  property var pads: []
  property var configErrors: []
  property bool cheatSheetOpen: false
  property bool daemonReady: false
  property bool quickMenuWanted: false
  property bool uiOpen: false

  signal libraryChanged()
  signal sessionChanged()
  signal nav(string dir, bool repeat)
  signal intent(string name)
  signal actionFired(string name, string reason)
  signal padsChanged()
  signal quickMenuRequested()

  // Controller input does not reset Hyprland/Omarchy idle timers.
  // Hold a systemd idle inhibit while Arcade UI is open or a game is tracked.
  // HARDWARE TEST: browse with only a pad for >3 minutes; screensaver must not start.
  function refreshIdleInhibit() {
    var need = root.uiOpen || root.sessionState === "starting" || root.sessionState === "running"
    if (need && !inhibitProcess.running) {
      inhibitProcess.command = [
        "systemd-inhibit",
        "--what=idle",
        "--who=Omarchy Arcade",
        "--why=Controller session",
        "--mode=block",
        "sleep", "infinity"
      ]
      inhibitProcess.running = true
    } else if (!need && inhibitProcess.running) {
      inhibitProcess.signal(15) // SIGTERM
    }
  }

  function notifySend(summary, body) {
    if (notifyProcess.running)
      notifyProcess.running = false
    notifyProcess.command = [
      "omarchy-notification-send",
      "--app-name", "Arcade",
      String(summary || ""),
      String(body || "")
    ]
    notifyProcess.running = true
  }

  function rescan(payloadJson) {
    root.lastAction = "scan:pending"
    root.lastError = ""
    if (scanProcess.running)
      scanProcess.running = false
    scanProcess.command = [root.scanBin, "--plugin-dir", root.pluginDir]
    scanProcess.running = true
    return "ok"
  }

  function loadLibraryFromDisk() {
    try {
      var text = libraryView.text()
      if (!text || !text.length) {
        root.games = []
        root.scanErrors = []
        root.libraryChanged()
        return
      }
      var data = JSON.parse(text)
      root.games = data.games || []
      root.scanErrors = data.errors || []
      root.lastAction = "scan:done"
      root.libraryChanged()
    } catch (e) {
      root.lastError = String(e)
      root.lastAction = "scan:failed"
    }
  }

  function findGame(id) {
    for (var i = 0; i < root.games.length; i++) {
      if (root.games[i].id === id)
        return root.games[i]
    }
    return null
  }

  function launchGame(game) {
    if (!game)
      return false
    if (root.sessionState === "starting" || root.sessionState === "running") {
      root.notifySend("Already playing", (root.sessionGame && root.sessionGame.title) || "")
      return false
    }
    var argv = Model.launchArgv(game)
    if (!argv) {
      root.lastError = "No launch command"
      root.notifySend("Cannot launch", game.title || "")
      return false
    }
    root.sessionGame = game
    root.sessionState = "starting"
    root.sessionChanged()
    root.notifySend("Launching", game.title || "")
    root.sendDaemon({
      t: "launch",
      game: game.id,
      argv: argv,
      track: game.track || {}
    })
    root.setUiMode(false)
    if (root.shell && typeof root.shell.hide === "function")
      root.shell.hide(Model.pluginId(root.manifest))
    return true
  }

  function closeGame(force) {
    root.sendDaemon({ t: "close", force: !!force })
    if (force) {
      root.sessionState = "idle"
      root.sessionGame = null
      root.sessionChanged()
      root.returnToArcade()
    }
  }

  function returnToArcade() {
    root.sessionState = "returning"
    root.sessionChanged()
    Quickshell.execDetached([
      "omarchy-shell", "shell", "summon", Model.pluginId(root.manifest), "{}"
    ])
    Qt.callLater(function() {
      root.sessionState = "idle"
      root.sessionGame = null
      root.sessionChanged()
      root.refreshIdleInhibit()
    })
  }

  function focusGame() {
    var g = root.sessionGame
    if (!g || !g.track || !g.track.windowClass)
      return
    Quickshell.execDetached([
      "hyprctl", "dispatch", "focuswindow", "class:" + g.track.windowClass
    ])
  }

  function toggleArcade() {
    Quickshell.execDetached([
      "omarchy-shell", "shell", "toggle", Model.pluginId(root.manifest), "{}"
    ])
  }

  function openQuickMenu() {
    if (root.sessionState === "running" || root.sessionState === "starting") {
      root.quickMenuWanted = true
      root.quickMenuRequested()
      Quickshell.execDetached([
        "omarchy-shell", "shell", "call", Model.pluginId(root.manifest), "showQuickMenu", "{}"
      ])
    } else {
      root.toggleArcade()
    }
  }

  function showQuickMenu(payloadJson) {
    root.quickMenuWanted = true
    root.quickMenuRequested()
    return "ok"
  }

  function setUiMode(on) {
    root.uiOpen = !!on
    root.sendDaemon({ t: "mode", ui: !!on })
    root.refreshIdleInhibit()
  }

  function sendDaemon(obj) {
    if (!daemon.running)
      root.startDaemon()
    if (daemon.running)
      daemon.write(JSON.stringify(obj) + "\n")
  }

  function startDaemon() {
    if (daemon.running)
      return
    daemon.command = [
      root.daemonBin,
      "--exit-with-stdin",
      "--plugin-dir", root.pluginDir
    ]
    daemon.running = true
  }

  function handleDaemonLine(line) {
    var msg
    try {
      msg = JSON.parse(line)
    } catch (e) {
      return
    }
    var t = msg.t
    if (t === "hello") {
      root.daemonReady = true
      root.setUiMode(false)
    } else if (t === "pads") {
      root.pads = msg.pads || []
      root.padsChanged()
    } else if (t === "config") {
      root.configErrors = msg.errors || []
    } else if (t === "nav") {
      root.nav(msg.dir || "", !!msg.repeat)
    } else if (t === "intent") {
      root.intent(msg.name || "")
    } else if (t === "action") {
      root.actionFired(msg.name || "", msg.reason || "")
      root.dispatchAction(msg.name || "")
    } else if (t === "session") {
      root.onSessionEvent(msg)
    } else if (t === "error") {
      root.lastError = msg.error || "daemon error"
      root.notifySend("Arcade", root.lastError)
    }
  }

  function dispatchAction(name) {
    if (name === "arcade.toggle")
      root.toggleArcade()
    else if (name === "arcade.quick_menu")
      root.openQuickMenu()
    else if (name === "arcade.cheat_sheet")
      root.cheatSheetOpen = !root.cheatSheetOpen
    else if (name === "game.close")
      root.closeGame(false)
    else if (name === "game.force_quit")
      root.closeGame(true)
    else if (name === "game.focus")
      root.focusGame()
  }

  function onSessionEvent(msg) {
    var state = msg.state || ""
    if (state === "starting") {
      root.sessionState = "starting"
      root.sessionChanged()
      root.refreshIdleInhibit()
    } else if (state === "running") {
      root.sessionState = "running"
      root.sessionChanged()
      root.refreshIdleInhibit()
    } else if (state === "exited") {
      var title = (root.sessionGame && root.sessionGame.title) || "Game"
      root.notifySend("Game ended", title)
      root.returnToArcade()
      root.refreshIdleInhibit()
    }
  }

  function markSessionRunning() {
    if (root.sessionState === "starting") {
      root.sessionState = "running"
      root.sessionChanged()
    }
  }

  function status() {
    return JSON.stringify({
      daemon: root.daemonReady,
      games: root.games.length,
      session: root.sessionState,
      pads: root.pads.length,
      errors: root.scanErrors
    })
  }

  Component.onCompleted: {
    root.startDaemon()
    root.rescan()
  }

  FileView {
    id: libraryView
    path: root.libraryFile
    watchChanges: true
    onFileChanged: root.loadLibraryFromDisk()
    onLoaded: root.loadLibraryFromDisk()
  }

  Process { id: notifyProcess }
  Process { id: inhibitProcess }

  Process {
    id: scanProcess
    stdout: StdioCollector {
      onStreamFinished: {
        root.loadLibraryFromDisk()
        if (!artProcess.running) {
          artProcess.command = [root.artBin, "--plugin-dir", root.pluginDir, "--limit", "10"]
          artProcess.running = true
        }
      }
    }
    stderr: StdioCollector {
      onStreamFinished: {
        if (text && text.length)
          root.lastError = text.trim()
      }
    }
  }

  Process {
    id: artProcess
    stdout: StdioCollector {
      onStreamFinished: {
        try {
          var data = JSON.parse(text)
          if (data.updated > 0)
            root.loadLibraryFromDisk()
        } catch (e) {}
      }
    }
  }

  Process {
    id: daemon
    stdinEnabled: true
    running: false
    stdout: SplitParser {
      onRead: function(line) { root.handleDaemonLine(line) }
    }
    stderr: SplitParser {
      onRead: function(line) {
        if (line && line.trim() !== "")
          console.log("arcaded:", line)
      }
    }
    onExited: function(exitCode, exitStatus) {
      root.daemonReady = false
      if (exitCode === 127)
        return
      daemonRestart.interval = 3000
      daemonRestart.restart()
    }
  }

  Timer {
    id: daemonRestart
    interval: 3000
    repeat: false
    onTriggered: {
      if (!daemon.running)
        root.startDaemon()
    }
  }
}
