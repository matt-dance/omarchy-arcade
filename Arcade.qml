import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "ArcadeModel.js" as Model

// Fullscreen Arcade library overlay.
// Summon: omarchy-shell shell toggle matt-dance.arcade '{}'
//
// The in-game Quick Menu lives here as a child surface. Omarchy's host
// prefers kind "panel" over "overlay" when both are declared, so Arcade
// does not register a panel entry point — otherwise this bind would open
// QuickMenu.qml instead of the library.
Item {
  id: root

  property string omarchyPath: Quickshell.env("OMARCHY_PATH")
  property var shell: null
  property var manifest: null
  property var pluginRegistry: null
  property var service: null

  property bool opened: false
  property string screen: "home"   // home | library | search | settings
  property string filterText: ""
  property int selectedIndex: 0
  property var visibleGames: []
  property string statusText: "Scanning library…"
  property bool showCheatSheet: false
  property bool playOnOpen: false
  property var playOnChoices: []
  property int playOnIndex: 0
  property var localGames: []
  property var localScanErrors: []
  property bool localScanPending: false
  property string localScanError: ""
  property string focusZone: "shelf"   // shelf | details
  property int detailButton: 0         // 0 Play, 1 Options
  property var focusedGame: null
  property var selectedMeta: ({})
  property var metaById: ({})
  property string pendingMetaId: ""
  property bool menuPinned: false
  property bool libraryBeneathMenu: false
  property var libraryState: Model.parseStateText("")
  property string libraryTab: "all"
  property string sortMode: "recent"
  property string optionsTitle: ""
  property string lastListLog: ""
  property bool pendingMetaForce: false
  property point lastPointer: Qt.point(-1, -1)

  readonly property string pluginDir: Model.pluginDirPath(Quickshell.env("HOME") || "", root.manifest)
  readonly property string libraryFile: Model.libraryFilePath(
    Quickshell.env("HOME") || "",
    Quickshell.env("XDG_CACHE_HOME") || ""
  )
  readonly property string scanBin: root.pluginDir + "/bin/arcade-scan"
  readonly property string metaBin: root.pluginDir + "/bin/arcade-meta"
  readonly property string stateBin: root.pluginDir + "/bin/arcade-state"
  readonly property string stateFile: Model.stateFilePath(
    Quickshell.env("HOME") || "",
    Quickshell.env("XDG_STATE_HOME") || ""
  )
  property var libraryTabs: Model.libraryTabs([])
  readonly property string metaFile: Model.metaFilePath(
    Quickshell.env("HOME") || "",
    Quickshell.env("XDG_CACHE_HOME") || "",
    root.focusedGame ? root.focusedGame.id : ""
  )

  readonly property color background: Commons.Color.menu.background
  readonly property color foreground: Commons.Color.menu.text
  readonly property color scrim: Commons.Color.menu.scrim
  readonly property color selectedBackground: Commons.Color.menu.selectedBackground
  readonly property color selectedText: Commons.Color.menu.selectedText
  readonly property color muted: Commons.Color.menu.text
  readonly property int cornerRadius: Style.cornerRadius
  readonly property string fontFamily: Style.font.menuFamily
  readonly property real uiScale: 1.25
  readonly property int cardW: Style.space(Math.round(160 * uiScale))
  readonly property int cardH: Style.space(Math.round(240 * uiScale))
  readonly property int homeCardW: Style.space(Math.round(220 * uiScale))
  readonly property int homeCardH: Style.space(Math.round(330 * uiScale))
  readonly property int gridGap: Style.space(Math.round(16 * uiScale))
  readonly property bool homeActive: root.screen === "home" && root.filterText.length === 0
  readonly property var defaultHints: [
    { key: "A", label: "Play" },
    { key: "B", label: "Back" },
    { key: "Y", label: "Search" },
    { key: "LB/RB", label: "Tabs" },
    { key: "Select", label: "Sort" },
    { key: "X", label: "Options" },
    { key: "R3", label: "Favorite" },
    { key: "Start", label: "Settings" }
  ]
  readonly property var homeShelfHints: [
    { key: "A", label: "Play" },
    { key: "Left/Right", label: "Games" },
    { key: "Down", label: "Details" },
    { key: "X", label: "Options" },
    { key: "LB/RB", label: "Library" },
    { key: "B", label: "Close" }
  ]
  readonly property var homeDetailsHints: [
    { key: "A", label: "Select" },
    { key: "Left/Right", label: "Buttons" },
    { key: "Up", label: "Games" },
    { key: "X", label: "Options" },
    { key: "B", label: "Row" }
  ]

  function open(payloadJson) {
    var payload = {}
    try {
      if (payloadJson && String(payloadJson).length)
        payload = JSON.parse(payloadJson)
    } catch (e) {
      payload = {}
    }
    if (payload && payload.surface === "quickmenu") {
      console.warn("matt-dance.arcade: open surface=quickmenu persist=" + !!payload.persist
                   + " library=" + root.opened)
      root.showQuickMenu(payloadJson)
      return
    }
    if (quickMenu && quickMenu.opened && !root.menuPinned)
      quickMenu.close()
    root.playOnOpen = false
    root.opened = true
    root.screen = "home"
    root.filterText = ""
    root.selectedIndex = 0
    root.lastPointer = Qt.point(-1, -1)
    root.focusZone = "shelf"
    root.detailButton = 0
    if (stateView && typeof stateView.reload === "function")
      stateView.reload()
    root.loadLibraryFromDisk()
    root.refreshList()
    root.ensureLibrary()
    if (root.service && typeof root.service.setUiMode === "function")
      root.service.setUiMode(true)
    Qt.callLater(function() { keyCatcher.forceActiveFocus() })
  }

  function close() {
    root.opened = false
    if (root.menuPinned) {
      console.warn("matt-dance.arcade: close library; system menu stays pinned")
      return
    }
    if (root.service && typeof root.service.setUiMode === "function")
      root.service.setUiMode(false)
  }

  function dismiss() {
    if (root.menuPinned && quickMenu && quickMenu.opened) {
      console.warn("matt-dance.arcade: dismiss skipped; system menu is pinned")
      return
    }
    root.close()
    if (root.shell && typeof root.shell.hide === "function")
      root.shell.hide(Model.pluginId(root.manifest))
  }

  function libraryGames() {
    return Model.applyState(Model.resolvedGames(root.service, root.localGames), root.libraryState)
  }

  function loadStateFromDisk() {
    var text = ""
    try {
      text = stateView.text()
    } catch (e) {
      text = ""
    }
    root.libraryState = Model.parseStateText(text)
    root.sortMode = root.libraryState.sort
    root.refreshKeepingFocus()
  }

  function runStateCommand(args) {
    Quickshell.execDetached(["/usr/bin/python3", root.stateBin].concat(args))
  }

  function focusedGameOrNull() {
    if (root.selectedIndex < 0 || root.selectedIndex >= root.visibleGames.length)
      return null
    return root.visibleGames[root.selectedIndex]
  }

  // Update the in-memory state immediately; state.json catches up via FileView.
  function toggleStateMember(listName, game) {
    if (!game || !game.id)
      return
    var next = Model.parseStateText(JSON.stringify({
      favorites: Object.keys(root.libraryState.favorites),
      hidden: Object.keys(root.libraryState.hidden),
      games: root.libraryState.games,
      sort: root.libraryState.sort
    }))
    var on = !game[listName === "favorites" ? "favorite" : "hidden"]
    var ids = [String(game.id)]
    var extra = game.alsoOn || []
    for (var i = 0; i < extra.length; i++) {
      if (extra[i] && typeof extra[i] === "object" && extra[i].id)
        ids.push(String(extra[i].id))
    }
    for (var j = 0; j < ids.length; j++) {
      if (on && j === 0)
        next[listName][ids[j]] = true
      else if (!on)
        delete next[listName][ids[j]]
    }
    root.libraryState = next
    root.refreshKeepingFocus()
    var cmd = listName === "favorites" ? "favorite" : "hide"
    root.runStateCommand([cmd, String(game.id), on ? "--on" : "--off"])
    for (var k = 1; k < ids.length && !on; k++)
      root.runStateCommand([cmd, ids[k], "--off"])
  }

  function toggleFavorite(game) {
    root.toggleStateMember("favorites", game || root.focusedGameOrNull())
  }

  function toggleHidden(game) {
    root.toggleStateMember("hidden", game || root.focusedGameOrNull())
  }

  function cycleSort() {
    root.sortMode = Model.nextSort(root.sortMode)
    root.libraryState.sort = root.sortMode
    root.selectedIndex = 0
    root.refreshList()
    root.runStateCommand(["sort", root.sortMode])
  }

  function libraryTabIndex() {
    for (var i = 0; i < root.libraryTabs.length; i++) {
      if (root.libraryTabs[i].id === root.libraryTab)
        return i
    }
    return -1
  }

  function libraryTabLabel() {
    var i = root.libraryTabIndex()
    return i >= 0 ? root.libraryTabs[i].label : "All games"
  }

  // LB/RB walk Home → All games → Favorites → each store → Hidden → Home.
  function stepTab(delta) {
    var tabs = root.libraryTabs
    var pos = root.screen === "library" ? root.libraryTabIndex() : -1
    var next = pos + delta
    if (root.screen !== "library" && delta < 0)
      next = tabs.length - 1
    if (next < 0 || next >= tabs.length) {
      root.screen = "home"
    } else {
      root.screen = "library"
      root.libraryTab = tabs[next].id
    }
    root.filterText = ""
    root.selectedIndex = 0
    root.focusZone = "shelf"
    root.detailButton = 0
    root.refreshList()
  }

  // Hover only counts when the pointer really moved. A sheet or list that
  // appears under a resting pointer must not steal the controller's focus.
  function pointerMoved(scenePos) {
    var lastX = root.lastPointer.x
    var lastY = root.lastPointer.y
    root.lastPointer = Qt.point(scenePos.x, scenePos.y)
    return lastX >= 0 && (scenePos.x !== lastX || scenePos.y !== lastY)
  }

  function loadLibraryFromDisk() {
    var text = ""
    try {
      text = libraryView.text()
    } catch (e2) {
      text = ""
    }
    var parsed = Model.parseLibraryText(text)
    root.localGames = parsed.games
    root.localScanErrors = parsed.errors
    if (!parsed.ok)
      root.localScanError = parsed.error || "library.json parse failed"
    console.warn("matt-dance.arcade: overlay cache " + root.libraryFile + " games=" + root.localGames.length
                 + " service=" + (root.service && root.service.games ? root.service.games.length : "no"))
    root.refreshList()
    root.loadCachedArt()
  }

  function startLocalScan() {
    if (localScanProcess.running)
      return
    root.localScanPending = true
    root.localScanError = ""
    localScanProcess.command = ["/usr/bin/python3", root.scanBin, "--plugin-dir", root.pluginDir]
    console.warn("matt-dance.arcade: overlay starting arcade-scan " + root.scanBin)
    localScanProcess.running = true
  }

  function ensureLibrary() {
    if (root.libraryGames().length)
      return
    if (root.service && typeof root.service.rescan === "function")
      root.service.rescan()
    root.startLocalScan()
  }

  function launchResolved(game) {
    if (root.service && typeof root.service.launchGame === "function")
      return root.service.launchGame(game)
    var argv = Model.launchArgv(game)
    if (!argv) {
      console.warn("matt-dance.arcade: cannot launch, no command and no service")
      return false
    }
    console.warn("matt-dance.arcade: launching without service: " + argv.join(" "))
    Quickshell.execDetached(argv)
    return true
  }

  function refreshKeepingFocus() {
    var current = root.focusedGameOrNull()
    root.refreshList()
    if (!current)
      return
    for (var i = 0; i < root.visibleGames.length; i++) {
      if (root.visibleGames[i].id === current.id) {
        if (i !== root.selectedIndex)
          root.selectedIndex = i
        return
      }
    }
  }

  function refreshList() {
    var games = root.libraryGames()
    root.libraryTabs = Model.libraryTabs(games)
    if (root.screen === "library" && root.libraryTabIndex() < 0)
      root.libraryTab = "all"
    if (root.homeActive)
      root.visibleGames = Model.homeShelf(games)
    else if (root.screen === "library" && !root.filterText.length)
      root.visibleGames = Model.sortGames(Model.tabGames(games, root.libraryTab), root.sortMode)
    else
      root.visibleGames = Model.filterGames(games, root.filterText)
    if (root.selectedIndex >= root.visibleGames.length)
      root.selectedIndex = Math.max(0, root.visibleGames.length - 1)
    root.updateFocused()
    var cacheN = root.localGames ? root.localGames.length : 0
    var serviceN = (root.service && root.service.games) ? root.service.games.length : 0
    var listLog = "shelf=" + root.visibleGames.length
                  + " cache=" + cacheN
                  + " service=" + serviceN
                  + " resolved=" + games.length
    if (listLog !== root.lastListLog) {
      root.lastListLog = listLog
      console.warn("matt-dance.arcade: " + listLog)
    }
    var n = games.length
    var scanning = root.localScanPending || (root.service && root.service.lastAction === "scan:pending")
    if (scanning && n === 0)
      root.statusText = "Scanning library…"
    else if (n === 0)
      root.statusText = "No games found — install Steam, Heroic, or add .desktop games"
    else if (!root.service)
      root.statusText = n + " games (cached) · service not loaded — omarchy-restart-shell"
    else if (root.screen === "home")
      root.statusText = "Home · " + n + " games"
    else if (root.screen === "library" && !root.filterText.length)
      root.statusText = root.libraryTabLabel() + " · " + root.visibleGames.length + " games · " + Model.sortLabel(root.sortMode)
    else
      root.statusText = root.visibleGames.length + " of " + n + " games"
  }

  function updateFocused() {
    if (root.selectedIndex >= 0 && root.selectedIndex < root.visibleGames.length)
      root.focusedGame = root.visibleGames[root.selectedIndex]
    else
      root.focusedGame = null
    root.loadMetaFromDisk()
    root.ensureMeta(root.focusedGame)
  }

  function loadMetaFromDisk() {
    if (!root.metaFile) {
      if (!root.focusedGame)
        root.selectedMeta = {}
      return
    }
    var text = ""
    try {
      text = metaView.text()
    } catch (e) {
      text = ""
    }
    var parsed = Model.parseMetaText(text)
    if (parsed && parsed.id) {
      root.selectedMeta = parsed
      root.ingestMeta(parsed)
      console.warn("matt-dance.arcade: meta loaded id=" + parsed.id
                   + " file=" + root.metaFile)
    }
  }

  function ingestMeta(meta) {
    if (!meta || !meta.id)
      return
    root.metaById = Model.rememberMeta(root.metaById, meta)
  }

  function ingestCachedArt(payload) {
    if (!payload)
      return
    root.metaById = Model.rememberMetaMap(root.metaById, payload)
  }

  function loadCachedArt() {
    if (cachedArtProcess.running)
      return
    cachedArtProcess.command = [
      "/usr/bin/python3", root.metaBin, "--plugin-dir", root.pluginDir, "--cached-art"
    ]
    cachedArtProcess.running = true
  }

  function applyMetaStdout(text) {
    if (!text || !String(text).length)
      return
    var data
    try {
      data = JSON.parse(text)
    } catch (e) {
      return
    }
    if (data && data.meta && data.meta.id) {
      if (!root.focusedGame || data.meta.id === root.focusedGame.id)
        root.selectedMeta = data.meta
      root.ingestMeta(data.meta)
    }
    if (data && data.cachedArt)
      root.ingestCachedArt(data.cachedArt)
    if (data && data.artUpdated > 0)
      root.loadLibraryFromDisk()
  }

  function ensureMeta(game) {
    if (!game || !game.id)
      return
    if (root.selectedMeta && root.selectedMeta.id === game.id && Model.metaIsFresh(root.selectedMeta))
      return
    root.startMeta(game.id, false)
  }

  function startMeta(gameId, force) {
    if (metaProcess.running) {
      root.pendingMetaId = gameId
      root.pendingMetaForce = force
      return
    }
    root.pendingMetaId = ""
    root.pendingMetaForce = false
    var cmd = ["/usr/bin/python3", root.metaBin, "--plugin-dir", root.pluginDir]
    if (force)
      cmd.push("--force")
    cmd.push(gameId)
    metaProcess.command = cmd
    console.warn("matt-dance.arcade: overlay starting arcade-meta " + gameId
                 + (force ? " --force" : "") + " file=" + root.metaFile)
    metaProcess.running = true
  }

  function moveHome(dx, dy) {
    var count = root.visibleGames.length
    if (count === 0)
      return
    if (root.focusZone === "shelf") {
      if (dx !== 0)
        root.selectedIndex = Math.max(0, Math.min(count - 1, root.selectedIndex + dx))
      if (dy > 0)
        root.focusZone = "details"
      if (homeRow)
        homeRow.positionViewAtIndex(root.selectedIndex, ListView.Contain)
    } else {
      if (dx !== 0)
        root.detailButton = dx < 0 ? 0 : 1
      if (dy < 0)
        root.focusZone = "shelf"
    }
  }

  function moveSelection(dx, dy) {
    if (root.homeActive) {
      root.moveHome(dx, dy)
      return
    }
    var cols = Math.max(1, Math.floor((grid.width + gridGap) / (cardW + gridGap)))
    var count = root.visibleGames.length
    if (count === 0) return
    var idx = root.selectedIndex
    if (dx !== 0)
      idx = Math.max(0, Math.min(count - 1, idx + dx))
    if (dy !== 0)
      idx = Math.max(0, Math.min(count - 1, idx + dy * cols))
    root.selectedIndex = idx
    if (grid)
      grid.positionViewAtIndex(idx, GridView.Contain)
  }

  function activateSelected() {
    if (root.selectedIndex < 0 || root.selectedIndex >= root.visibleGames.length)
      return
    root.launchResolved(root.visibleGames[root.selectedIndex])
  }

  function openOptions() {
    var game = root.focusedGameOrNull()
    if (!game)
      return
    root.optionsTitle = game.title || ""
    root.playOnChoices = Model.optionItems(game)
    root.playOnIndex = 0
    root.playOnOpen = true
  }

  function launchPlayOnChoice() {
    if (!root.playOnOpen || root.playOnIndex < 0 || root.playOnIndex >= root.playOnChoices.length)
      return
    var item = root.playOnChoices[root.playOnIndex]
    var game = root.focusedGameOrNull()
    root.playOnOpen = false
    if (item.action === "play")
      root.launchResolved(item.choice)
    else if (item.action === "favorite")
      root.toggleFavorite(game)
    else if (item.action === "hide")
      root.toggleHidden(game)
    else if (item.action === "refresh" && game)
      root.startMeta(game.id, true)
  }

  // Host `shell call matt-dance.arcade <method>` hits this overlay item, not Service.qml.
  function rescan(payloadJson) {
    if (root.service && typeof root.service.rescan === "function")
      return root.service.rescan(payloadJson)
    root.startLocalScan()
    return "ok"
  }

  function parsePayload(payloadJson) {
    try {
      if (payloadJson && String(payloadJson).length)
        return JSON.parse(payloadJson)
    } catch (e) {}
    return {}
  }

  function showQuickMenu(payloadJson) {
    var payload = root.parsePayload(payloadJson)
    var persist = !!(payload && payload.persist)
    console.warn("matt-dance.arcade: showQuickMenu persist=" + persist
                 + " library=" + root.opened
                 + " menu=" + (quickMenu && quickMenu.opened ? "open" : "closed")
                 + " service=" + (root.service ? "yes" : "no"))
    if (root.service) {
      root.service.quickMenuWanted = true
      if (typeof root.service.setUiMode === "function")
        root.service.setUiMode(true)
    }
    if (!quickMenu) {
      console.warn("matt-dance.arcade: showQuickMenu failed — QuickMenu child missing")
      return "unknown"
    }
    root.menuPinned = true
    if (root.opened)
      root.libraryBeneathMenu = true
    quickMenu.open(payloadJson || "{}")
    console.warn("matt-dance.arcade: showQuickMenu opened menuPinned=true libraryBeneath="
                 + root.libraryBeneathMenu)
    // Host `shell call` often unmaps the overlay after the method returns.
    // Re-summon as the menu surface so the plugin stays mapped.
    if (!persist && root.service && typeof root.service.persistQuickMenu === "function")
      root.service.persistQuickMenu()
    else if (!persist) {
      menuPersistTimer.ticks = 0
      menuPersistTimer.restart()
    }
    return "ok"
  }

  function onQuickMenuDismissed() {
    console.warn("matt-dance.arcade: system menu dismissed libraryBeneath=" + root.libraryBeneathMenu
                 + " library=" + root.opened)
    root.menuPinned = false
    if (root.service)
      root.service.quickMenuWanted = false
    if (root.libraryBeneathMenu && root.opened) {
      root.libraryBeneathMenu = false
      Qt.callLater(function() { keyCatcher.forceActiveFocus() })
      return
    }
    root.libraryBeneathMenu = false
    if (!root.opened && root.shell && typeof root.shell.hide === "function")
      root.shell.hide(Model.pluginId(root.manifest))
    if (root.service && typeof root.service.setUiMode === "function")
      root.service.setUiMode(false)
  }

  function status() {
    if (root.service && typeof root.service.status === "function")
      return root.service.status()
    return "{}"
  }

  function handleIntent(name) {
    if (quickMenu && quickMenu.opened)
      return
    if (!root.opened) return
    if (root.playOnOpen) {
      if (name === "accept") root.launchPlayOnChoice()
      else if (name === "back") root.playOnOpen = false
      return
    }
    if (name === "accept") {
      if (root.screen === "settings") {
        root.screen = "home"
        root.refreshList()
      } else if (root.homeActive && root.focusZone === "details" && root.detailButton === 1) {
        root.openOptions()
      } else {
        root.activateSelected()
      }
    } else if (name === "back") {
      if (root.filterText) root.filterText = ""
      else if (root.homeActive && root.focusZone === "details") root.focusZone = "shelf"
      else if (root.screen !== "home") {
        root.screen = "home"
        root.focusZone = "shelf"
      } else {
        root.dismiss()
      }
      root.refreshList()
    } else if (name === "search") {
      root.screen = "search"
      root.refreshList()
    } else if (name === "options") {
      root.openOptions()
    } else if (name === "menu") {
      root.screen = root.screen === "settings" ? "home" : "settings"
      root.focusZone = "shelf"
      root.refreshList()
    } else if (name === "tab_next") {
      root.stepTab(1)
    } else if (name === "tab_prev") {
      root.stepTab(-1)
    } else if (name === "sort") {
      if (root.screen === "library" && !root.filterText.length)
        root.cycleSort()
    } else if (name === "favorite") {
      if (root.screen !== "settings")
        root.toggleFavorite()
    } else if (name === "page_down") root.moveSelection(root.homeActive ? 4 : 0, root.homeActive ? 0 : 2)
    else if (name === "page_up") root.moveSelection(root.homeActive ? -4 : 0, root.homeActive ? 0 : -2)
  }

  onServiceChanged: {
    console.warn("matt-dance.arcade: overlay service=" + (root.service ? "attached" : "null"))
    root.refreshList()
  }

  Connections {
    target: root.service
    function onLibraryChanged() { root.refreshList() }
    function onNav(dir, repeat) {
      if (quickMenu && quickMenu.opened) return
      if (!root.opened) return
      if (root.playOnOpen) {
        var n = root.playOnChoices.length
        if (!n) return
        if (dir === "up" || dir === "left")
          root.playOnIndex = (root.playOnIndex - 1 + n) % n
        else if (dir === "down" || dir === "right")
          root.playOnIndex = (root.playOnIndex + 1) % n
        return
      }
      if (dir === "up") root.moveSelection(0, -1)
      else if (dir === "down") root.moveSelection(0, 1)
      else if (dir === "left") root.moveSelection(-1, 0)
      else if (dir === "right") root.moveSelection(1, 0)
    }
    function onIntent(name) { root.handleIntent(name) }
    function onCheatSheetOpenChanged() {
      if (root.service)
        root.showCheatSheet = root.service.cheatSheetOpen
    }
  }

  PanelWindow {
    id: panel
    visible: root.opened
    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    WlrLayershell.namespace: "matt-dance-arcade"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: root.opened ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None
    exclusionMode: ExclusionMode.Ignore

    Rectangle {
      anchors.fill: parent
      color: root.scrim
    }

    Rectangle {
      anchors.fill: parent
      anchors.margins: Style.gapsOut
      color: root.background
      radius: root.cornerRadius

      ColumnLayout {
        anchors.fill: parent
        anchors.margins: Style.spacing.panelPadding
        spacing: Style.spacing.md

        // Header
        RowLayout {
          Layout.fillWidth: true
          spacing: Style.spacing.lg

          Text {
            text: "Arcade"
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.display
            font.bold: true
          }

          Text {
            text: root.screen === "home" ? "Home" : (root.screen === "library" ? "Library" : (root.screen === "search" ? "Search" : "Settings"))
            color: root.foreground
            opacity: 0.7
            font.family: root.fontFamily
            font.pixelSize: Style.font.title
          }

          Item { Layout.fillWidth: true }

          Text {
            text: root.statusText
            color: root.foreground
            opacity: 0.55
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
          }
        }

        // Search field (visible on search screen or when filter active)
        Rectangle {
          Layout.fillWidth: true
          Layout.preferredHeight: Style.space(40)
          visible: root.screen === "search" || root.filterText.length > 0
          color: "transparent"
          border.color: root.foreground
          border.width: 1
          radius: root.cornerRadius
          opacity: 0.9

          TextInput {
            id: searchInput
            anchors.fill: parent
            anchors.margins: Style.spacing.controlPaddingX
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.title
            text: root.filterText
            selectedTextColor: root.selectedText
            selectionColor: Commons.Color.accent
            onTextChanged: {
              root.filterText = text
              root.screen = "search"
              root.refreshList()
            }
          }
        }

        // Settings pane
        ColumnLayout {
          Layout.fillWidth: true
          Layout.fillHeight: true
          visible: root.screen === "settings"
          spacing: Style.spacing.md

          Text {
            text: "Settings"
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.heading
          }
          Text {
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            color: root.foreground
            opacity: 0.75
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            text: "Config: ~/.config/omarchy/arcade/arcade.toml\nBindings reload live.\nOptional API keys: ~/.config/matt-dance.arcade/keys.json (chmod 600). Copy keys.example.json.\nSteamGridDB key (legacy): ~/.config/omarchy/arcade/steamgriddb.key\nFavorites, hidden games, and play history: " + root.stateFile + "\n\nService: " + (root.service ? "loaded" : "not loaded") + "\nDaemon: " + ((root.service && root.service.daemonReady) ? "ready" : (root.service ? "starting" : "not running — restart the shell")) + "\nControllers: " + ((root.service && root.service.pads) ? root.service.pads.length : 0) + "\nCache: " + root.libraryFile + " (" + root.localGames.length + " games)\n\nIf the service failed to load (or arcaded is not running), the library still reads library.json. Controller chords need the service.\nRecover: omarchy-restart-shell\nThen: journalctl --user -n 80 --grep matt-dance.arcade"
          }
          Text {
            visible: root.service && root.service.configErrors && root.service.configErrors.length
            color: Commons.Color.urgent
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            text: root.service ? ("Config errors:\n" + root.service.configErrors.join("\n")) : ""
          }
          Text {
            text: "A / Enter  back to library"
            color: root.foreground
            opacity: 0.5
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }
        }

        // Steam Deck-style Home: horizontal shelf + live details
        ColumnLayout {
          Layout.fillWidth: true
          Layout.fillHeight: true
          visible: root.screen === "home"
          spacing: Style.spacing.md

          ListView {
            id: homeRow
            Layout.fillWidth: true
            Layout.preferredHeight: root.homeCardH * 1.22 + root.gridGap
            orientation: ListView.Horizontal
            clip: true
            spacing: root.gridGap
            model: root.visibleGames
            boundsBehavior: Flickable.StopAtBounds
            highlightFollowsCurrentItem: true
            preferredHighlightBegin: Style.spacing.lg
            preferredHighlightEnd: width - root.homeCardW * 1.2
            highlightRangeMode: ListView.ApplyRange
            currentIndex: root.selectedIndex

            delegate: Item {
              width: root.homeCardW * 1.16
              height: homeRow.height
              required property var modelData
              required property int index
              z: index === root.selectedIndex ? 2 : 1

              Rectangle {
                id: homeCard
                width: root.homeCardW
                height: root.homeCardH
                anchors.centerIn: parent
                radius: root.cornerRadius
                clip: true
                color: index === root.selectedIndex ? root.selectedBackground : Qt.rgba(0, 0, 0, 0.25)
                border.width: index === root.selectedIndex ? Math.max(3, Style.space(3)) : 1
                border.color: index === root.selectedIndex ? Commons.Color.accent : Qt.rgba(1, 1, 1, 0.12)
                scale: index === root.selectedIndex ? 1.12 : 1.0
                opacity: index === root.selectedIndex ? 1 : 0.82
                Behavior on scale { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }
                Behavior on opacity { NumberAnimation { duration: 140 } }

                Image {
                  id: homeCover
                  anchors.fill: parent
                  anchors.margins: 3
                  clip: true
                  source: Model.coverUrl(modelData, Model.lookupMeta(modelData, root.metaById))
                  fillMode: Image.PreserveAspectCrop
                  asynchronous: true
                  visible: status === Image.Ready && !Model.isSmallArt(modelData, implicitWidth, implicitHeight, Model.lookupMeta(modelData, root.metaById))
                }

                Rectangle {
                  anchors.fill: parent
                  anchors.margins: 3
                  visible: !homeCover.visible
                  color: "transparent"
                  Image {
                    id: homeSmallIcon
                    anchors.centerIn: parent
                    source: Model.coverUrl(modelData, Model.lookupMeta(modelData, root.metaById))
                    visible: Model.isSmallArt(modelData, implicitWidth, implicitHeight, Model.lookupMeta(modelData, root.metaById)) && status === Image.Ready
                    asynchronous: true
                    fillMode: Image.Pad
                    cache: true
                  }
                  Column {
                    anchors.centerIn: parent
                    visible: homeSmallIcon.status !== Image.Ready
                    spacing: Style.spacing.sm
                    width: parent.width - Style.spacing.panelPadding
                    Text {
                      anchors.horizontalCenter: parent.horizontalCenter
                      text: Model.initials(modelData.title)
                      color: Commons.Color.accent
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.displayLarge
                      font.bold: true
                    }
                    Text {
                      width: parent.width
                      horizontalAlignment: Text.AlignHCenter
                      wrapMode: Text.WordWrap
                      maximumLineCount: 3
                      elide: Text.ElideRight
                      text: modelData.title || ""
                      color: root.foreground
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.body
                    }
                  }
                }

                Rectangle {
                  anchors.left: parent.left
                  anchors.top: parent.top
                  anchors.margins: Style.space(8)
                  width: homeBadge.implicitWidth + Style.space(10)
                  height: homeBadge.implicitHeight + Style.space(4)
                  radius: height / 2
                  color: Qt.rgba(0, 0, 0, 0.65)
                  Text {
                    id: homeBadge
                    anchors.centerIn: parent
                    text: Model.hasPlayOn(modelData)
                          ? "Play on…"
                          : Model.sourceLabel(modelData.source)
                    color: root.foreground
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                  }
                }

                Rectangle {
                  anchors.right: parent.right
                  anchors.top: parent.top
                  anchors.margins: Style.space(8)
                  visible: !!modelData.favorite
                  width: height
                  height: favStar.implicitHeight + Style.space(4)
                  radius: height / 2
                  color: Qt.rgba(0, 0, 0, 0.65)
                  Text {
                    id: favStar
                    anchors.centerIn: parent
                    text: "★"
                    color: Commons.Color.accent
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                  }
                }

                MouseArea {
                  anchors.fill: parent
                  hoverEnabled: true
                  onPositionChanged: function(mouse) {
                    if (!root.pointerMoved(mapToItem(null, mouse.x, mouse.y)))
                      return
                    root.selectedIndex = index
                    root.focusZone = "shelf"
                  }
                  onClicked: {
                    root.selectedIndex = index
                    root.focusZone = "shelf"
                    root.activateSelected()
                  }
                }
              }
            }
          }

          BorderSurface {
            id: homeDetail
            Layout.fillWidth: true
            Layout.fillHeight: true
            radius: root.cornerRadius
            color: root.background
            clip: true
            // Hyprland active window border from the current Omarchy theme
            // (accent color / gradient + window thickness). Fall back to a
            // flat accent stroke when an older shell lacks hyprlandActiveSpec.
            borderSpec: (typeof Border.hyprlandActiveSpec === "function")
                        ? Border.hyprlandActiveSpec(Commons.Color.accent, Math.max(2, Style.space(2)))
                        : Border.flat(Commons.Color.accent, Math.max(2, Style.space(2)))

            Item {
              id: homeDetailInner
              anchors.fill: parent
              anchors.topMargin: homeDetail.contentTopInset
              anchors.rightMargin: homeDetail.contentRightInset
              anchors.bottomMargin: homeDetail.contentBottomInset
              anchors.leftMargin: homeDetail.contentLeftInset
              clip: true

            Image {
              id: heroArt
              anchors.fill: parent
              source: Model.heroUrl(root.focusedGame, root.selectedMeta)
              fillMode: Image.PreserveAspectCrop
              asynchronous: true
              visible: status === Image.Ready
              opacity: 0.55
            }

            Image {
              anchors.fill: parent
              source: Model.coverUrl(root.focusedGame, root.selectedMeta)
              fillMode: Image.PreserveAspectCrop
              asynchronous: true
              visible: heroArt.status !== Image.Ready && status === Image.Ready
                       && !Model.isSmallArt(root.focusedGame, implicitWidth, implicitHeight, root.selectedMeta)
              opacity: 0.22
              scale: 1.18
            }

            Rectangle {
              anchors.fill: parent
              gradient: Gradient {
                GradientStop { position: 0.0; color: Qt.rgba(0, 0, 0, 0.15) }
                GradientStop { position: 0.45; color: Qt.rgba(0, 0, 0, 0.25) }
                GradientStop { position: 1.0; color: root.background }
              }
            }

            ColumnLayout {
              anchors.fill: parent
              anchors.margins: Style.spacing.lg
              spacing: Style.spacing.sm

              Text {
                Layout.fillWidth: true
                text: root.focusedGame ? (root.focusedGame.title || "") : "No games"
                color: root.foreground
                font.family: root.fontFamily
                font.pixelSize: Style.font.display
                font.bold: true
                elide: Text.ElideRight
                wrapMode: Text.WordWrap
                maximumLineCount: 2
              }

              Flow {
                Layout.fillWidth: true
                spacing: Style.spacing.sm
                Repeater {
                  model: Model.sourceBadges(root.focusedGame)
                  Rectangle {
                    required property var modelData
                    width: badgeText.implicitWidth + Style.space(14)
                    height: badgeText.implicitHeight + Style.space(6)
                    radius: height / 2
                    color: Qt.rgba(0, 0, 0, 0.45)
                    border.color: Commons.Color.accent
                    border.width: 1
                    Text {
                      id: badgeText
                      anchors.centerIn: parent
                      text: modelData
                      color: root.foreground
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.caption
                    }
                  }
                }
              }

              Text {
                Layout.fillWidth: true
                visible: Model.playMeta(root.focusedGame, root.selectedMeta).length > 0
                text: Model.playMeta(root.focusedGame, root.selectedMeta)
                color: root.foreground
                opacity: 0.75
                font.family: root.fontFamily
                font.pixelSize: Style.font.body
                wrapMode: Text.WordWrap
              }

              Flow {
                Layout.fillWidth: true
                spacing: Style.spacing.xs
                visible: Model.metaChips(root.selectedMeta).length > 0

                Repeater {
                  model: Model.metaChips(root.selectedMeta)
                  Rectangle {
                    required property var modelData
                    width: metaChipText.implicitWidth + Style.space(14)
                    height: metaChipText.implicitHeight + Style.space(6)
                    radius: height / 2
                    color: Qt.rgba(1, 1, 1, 0.08)
                    border.color: Qt.rgba(1, 1, 1, 0.16)
                    border.width: 1
                    Text {
                      id: metaChipText
                      anchors.centerIn: parent
                      text: modelData
                      color: root.foreground
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.caption
                    }
                  }
                }
              }

              Text {
                Layout.fillWidth: true
                visible: Model.descriptionText(root.focusedGame, root.selectedMeta).length > 0
                text: Model.descriptionText(root.focusedGame, root.selectedMeta)
                color: root.foreground
                opacity: 0.8
                font.family: root.fontFamily
                font.pixelSize: Style.font.body
                wrapMode: Text.WordWrap
                maximumLineCount: 4
                elide: Text.ElideRight
              }

              Row {
                Layout.fillWidth: true
                spacing: Style.spacing.xs
                visible: !!(root.selectedMeta && root.selectedMeta.screenshots && root.selectedMeta.screenshots.length)

                Repeater {
                  model: (root.selectedMeta && root.selectedMeta.screenshots) ? root.selectedMeta.screenshots : []
                  Image {
                    required property var modelData
                    width: Style.space(Math.round(120 * root.uiScale))
                    height: Style.space(Math.round(68 * root.uiScale))
                    source: modelData
                    fillMode: Image.PreserveAspectCrop
                    asynchronous: true
                    sourceSize.width: width
                    sourceSize.height: height
                  }
                }
              }

              Item { Layout.fillHeight: true }

              RowLayout {
                spacing: Style.spacing.md

                Rectangle {
                  Layout.preferredWidth: Style.space(160)
                  Layout.preferredHeight: Style.space(48)
                  radius: root.cornerRadius
                  color: (root.focusZone === "details" && root.detailButton === 0)
                         ? root.selectedBackground
                         : Qt.rgba(1, 1, 1, 0.08)
                  border.width: (root.focusZone === "details" && root.detailButton === 0) ? 2 : 1
                  border.color: (root.focusZone === "details" && root.detailButton === 0)
                                ? Commons.Color.accent
                                : Qt.rgba(1, 1, 1, 0.16)
                  Text {
                    anchors.centerIn: parent
                    text: "Play"
                    color: (root.focusZone === "details" && root.detailButton === 0)
                           ? root.selectedText
                           : root.foreground
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.title
                    font.bold: true
                  }
                  MouseArea {
                    anchors.fill: parent
                    hoverEnabled: true
                    onPositionChanged: function(mouse) {
                      if (!root.pointerMoved(mapToItem(null, mouse.x, mouse.y)))
                        return
                      root.focusZone = "details"
                      root.detailButton = 0
                    }
                    onClicked: root.activateSelected()
                  }
                }

                Rectangle {
                  Layout.preferredWidth: Style.space(160)
                  Layout.preferredHeight: Style.space(48)
                  radius: root.cornerRadius
                  color: (root.focusZone === "details" && root.detailButton === 1)
                         ? root.selectedBackground
                         : Qt.rgba(1, 1, 1, 0.08)
                  border.width: (root.focusZone === "details" && root.detailButton === 1) ? 2 : 1
                  border.color: (root.focusZone === "details" && root.detailButton === 1)
                                ? Commons.Color.accent
                                : Qt.rgba(1, 1, 1, 0.16)
                  Text {
                    anchors.centerIn: parent
                    text: "Options"
                    color: (root.focusZone === "details" && root.detailButton === 1)
                           ? root.selectedText
                           : root.foreground
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.title
                    font.bold: true
                  }
                  MouseArea {
                    anchors.fill: parent
                    hoverEnabled: true
                    onPositionChanged: function(mouse) {
                      if (!root.pointerMoved(mapToItem(null, mouse.x, mouse.y)))
                        return
                      root.focusZone = "details"
                      root.detailButton = 1
                    }
                    onClicked: root.openOptions()
                  }
                }
              }
            }
            }
          }
        }

        // Library tabs (LB/RB) and sort order (Select)
        RowLayout {
          Layout.fillWidth: true
          visible: root.screen === "library" && root.filterText.length === 0
          spacing: Style.spacing.sm

          Repeater {
            model: root.libraryTabs
            Rectangle {
              required property var modelData
              readonly property bool current: modelData.id === root.libraryTab
              Layout.preferredWidth: tabText.implicitWidth + Style.space(20)
              Layout.preferredHeight: tabText.implicitHeight + Style.space(10)
              radius: height / 2
              color: current ? root.selectedBackground : Qt.rgba(1, 1, 1, 0.06)
              border.width: current ? 2 : 1
              border.color: current ? Commons.Color.accent : Qt.rgba(1, 1, 1, 0.14)
              Text {
                id: tabText
                anchors.centerIn: parent
                text: modelData.label
                color: parent.current ? root.selectedText : root.foreground
                font.family: root.fontFamily
                font.pixelSize: Style.font.body
              }
              MouseArea {
                anchors.fill: parent
                onClicked: {
                  root.libraryTab = parent.modelData.id
                  root.selectedIndex = 0
                  root.refreshList()
                }
              }
            }
          }

          Item { Layout.fillWidth: true }

          Text {
            text: "Sort: " + Model.sortLabel(root.sortMode)
            color: root.foreground
            opacity: 0.7
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            MouseArea {
              anchors.fill: parent
              onClicked: root.cycleSort()
            }
          }
        }

        // Library / Search grid
        GridView {
          id: grid
          Layout.fillWidth: true
          Layout.fillHeight: true
          visible: root.screen === "library" || root.screen === "search"
          cellWidth: root.cardW + root.gridGap
          cellHeight: root.cardH + root.gridGap
          clip: true
          model: root.visibleGames
          boundsBehavior: Flickable.StopAtBounds

          delegate: Item {
            width: grid.cellWidth
            height: grid.cellHeight
            required property var modelData
            required property int index

            Rectangle {
              id: card
              width: root.cardW
              height: root.cardH
              anchors.centerIn: parent
              radius: root.cornerRadius
              clip: true
              color: index === root.selectedIndex ? root.selectedBackground : Qt.rgba(0, 0, 0, 0.25)
              border.width: index === root.selectedIndex ? Math.max(2, Style.space(2)) : 1
              border.color: index === root.selectedIndex ? Commons.Color.accent : Qt.rgba(1, 1, 1, 0.12)

              // Cover art or typographic card
              Image {
                id: cover
                anchors.fill: parent
                anchors.margins: 2
                clip: true
                source: Model.coverUrl(modelData, Model.lookupMeta(modelData, root.metaById))
                fillMode: Image.PreserveAspectCrop
                asynchronous: true
                visible: status === Image.Ready && !Model.isSmallArt(modelData, implicitWidth, implicitHeight, Model.lookupMeta(modelData, root.metaById))
              }

              Rectangle {
                anchors.fill: parent
                anchors.margins: 2
                visible: !cover.visible
                color: "transparent"
                Image {
                  id: librarySmallIcon
                  anchors.centerIn: parent
                  source: Model.coverUrl(modelData, Model.lookupMeta(modelData, root.metaById))
                  visible: Model.isSmallArt(modelData, implicitWidth, implicitHeight, Model.lookupMeta(modelData, root.metaById)) && status === Image.Ready
                  asynchronous: true
                  fillMode: Image.Pad
                  cache: true
                }
                Column {
                  anchors.centerIn: parent
                  visible: librarySmallIcon.status !== Image.Ready
                  spacing: Style.spacing.sm
                  width: parent.width - Style.spacing.panelPadding
                  Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: Model.initials(modelData.title)
                    color: Commons.Color.accent
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.displayLarge
                    font.bold: true
                  }
                  Text {
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.WordWrap
                    maximumLineCount: 3
                    elide: Text.ElideRight
                    text: modelData.title || ""
                    color: root.foreground
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.body
                  }
                }
              }

              // Source badge (or "Play on…" when the same title exists on multiple stores)
              Rectangle {
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.margins: Style.space(6)
                width: badgeLabel.implicitWidth + Style.space(10)
                height: badgeLabel.implicitHeight + Style.space(4)
                radius: height / 2
                color: Qt.rgba(0, 0, 0, 0.65)
                Text {
                  id: badgeLabel
                  anchors.centerIn: parent
                  text: Model.hasPlayOn(modelData)
                        ? "Play on…"
                        : Model.sourceLabel(modelData.source)
                  color: root.foreground
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                }
              }

              Rectangle {
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: Style.space(6)
                visible: !!modelData.favorite
                width: height
                height: libFavStar.implicitHeight + Style.space(4)
                radius: height / 2
                color: Qt.rgba(0, 0, 0, 0.65)
                Text {
                  id: libFavStar
                  anchors.centerIn: parent
                  text: "★"
                  color: Commons.Color.accent
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                }
              }

              MouseArea {
                anchors.fill: parent
                hoverEnabled: true
                onPositionChanged: function(mouse) {
                  if (root.pointerMoved(mapToItem(null, mouse.x, mouse.y)))
                    root.selectedIndex = index
                }
                onClicked: {
                  root.selectedIndex = index
                  root.activateSelected()
                }
              }
            }
          }
        }

        // Hint bar
        RowLayout {
          Layout.fillWidth: true
          spacing: Style.spacing.lg
          visible: root.screen !== "settings"

          Repeater {
            model: root.homeActive
                   ? (root.focusZone === "details" ? root.homeDetailsHints : root.homeShelfHints)
                   : root.defaultHints
            RowLayout {
              required property var modelData
              spacing: Style.spacing.xs
              Rectangle {
                width: keyText.implicitWidth + Style.space(10)
                height: keyText.implicitHeight + Style.space(4)
                radius: 4
                color: Qt.rgba(1, 1, 1, 0.08)
                border.color: Qt.rgba(1, 1, 1, 0.2)
                border.width: 1
                Text {
                  id: keyText
                  anchors.centerIn: parent
                  text: modelData.key
                  color: root.foreground
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                }
              }
              Text {
                text: modelData.label
                color: root.foreground
                opacity: 0.6
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
              }
            }
          }
          Item { Layout.fillWidth: true }
        }
      }

      // Keyboard catcher
      Item {
        id: keyCatcher
        anchors.fill: parent
        focus: true
        Keys.priority: Keys.BeforeItem
        Keys.onPressed: function(event) {
          if (root.playOnOpen) {
            if (event.key === Qt.Key_Escape || event.key === Qt.Key_Backspace) {
              root.playOnOpen = false; event.accepted = true
            } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
              root.launchPlayOnChoice(); event.accepted = true
            } else if (event.key === Qt.Key_Up || event.key === Qt.Key_K || event.key === Qt.Key_Left || event.key === Qt.Key_H) {
              var n = root.playOnChoices.length
              if (n) root.playOnIndex = (root.playOnIndex - 1 + n) % n
              event.accepted = true
            } else if (event.key === Qt.Key_Down || event.key === Qt.Key_J || event.key === Qt.Key_Right || event.key === Qt.Key_L) {
              var m = root.playOnChoices.length
              if (m) root.playOnIndex = (root.playOnIndex + 1) % m
              event.accepted = true
            }
            return
          }
          if (event.key === Qt.Key_Escape) {
            if (root.filterText) {
              root.filterText = ""
              searchInput.text = ""
              root.refreshList()
            } else if (root.homeActive && root.focusZone === "details") {
              root.focusZone = "shelf"
            } else if (root.screen !== "home" && root.screen !== "settings") {
              root.screen = "home"
              root.focusZone = "shelf"
              root.refreshList()
            } else if (root.screen === "settings") {
              root.screen = "home"
              root.refreshList()
            } else {
              root.dismiss()
            }
            event.accepted = true
          } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
            root.handleIntent("accept")
            event.accepted = true
          } else if (event.key === Qt.Key_X || event.key === Qt.Key_I) {
            root.openOptions(); event.accepted = true
          } else if (event.key === Qt.Key_Up || event.key === Qt.Key_K) {
            root.moveSelection(0, -1); event.accepted = true
          } else if (event.key === Qt.Key_Down || event.key === Qt.Key_J) {
            root.moveSelection(0, 1); event.accepted = true
          } else if (event.key === Qt.Key_Left || event.key === Qt.Key_H) {
            root.moveSelection(-1, 0); event.accepted = true
          } else if (event.key === Qt.Key_Right || event.key === Qt.Key_L) {
            root.moveSelection(1, 0); event.accepted = true
          } else if (event.key === Qt.Key_Tab) {
            root.handleIntent("tab_next"); event.accepted = true
          } else if (event.key === Qt.Key_Backtab) {
            root.handleIntent("tab_prev"); event.accepted = true
          } else if (event.key === Qt.Key_Slash || event.key === Qt.Key_Y) {
            root.screen = "search"
            searchInput.forceActiveFocus()
            event.accepted = true
          } else if (event.key === Qt.Key_M || event.key === Qt.Key_S && event.modifiers === Qt.NoModifier) {
            // Start-equivalent
            if (event.key === Qt.Key_M) {
              root.handleIntent("menu"); event.accepted = true
            }
          } else if (event.key === Qt.Key_F2) {
            root.handleIntent("sort"); event.accepted = true
          } else if (event.key === Qt.Key_F3) {
            root.handleIntent("favorite"); event.accepted = true
          } else if (event.key === Qt.Key_F5) {
            if (root.service) root.service.rescan()
            event.accepted = true
          } else if (event.text && event.text.length === 1 && event.text >= " " && root.screen !== "settings") {
            root.screen = "search"
            root.filterText += event.text
            searchInput.text = root.filterText
            root.refreshList()
            searchInput.forceActiveFocus()
            event.accepted = true
          }
        }
      }

      // Per-game Options sheet: Play on… choices, favorite, hide, refresh metadata
      Rectangle {
        anchors.fill: parent
        visible: root.playOnOpen
        color: Qt.rgba(0, 0, 0, 0.45)
        MouseArea {
          anchors.fill: parent
          onClicked: root.playOnOpen = false
        }

        Rectangle {
          anchors.centerIn: parent
          width: Math.min(parent.width - Style.space(80), Style.space(420))
          height: playOnColumn.implicitHeight + Style.spacing.panelPadding * 2
          radius: root.cornerRadius
          color: root.background
          border.color: Commons.Color.menu.border
          border.width: 1

          ColumnLayout {
            id: playOnColumn
            anchors.fill: parent
            anchors.margins: Style.spacing.panelPadding
            spacing: Style.spacing.sm

            Text {
              Layout.fillWidth: true
              text: root.optionsTitle || "Options"
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.heading
              font.bold: true
              elide: Text.ElideRight
            }
            Repeater {
              model: root.playOnChoices
              Rectangle {
                required property var modelData
                required property int index
                Layout.fillWidth: true
                Layout.preferredHeight: Style.space(44)
                radius: root.cornerRadius
                color: index === root.playOnIndex ? root.selectedBackground : "transparent"
                Text {
                  anchors.verticalCenter: parent.verticalCenter
                  anchors.left: parent.left
                  anchors.leftMargin: Style.spacing.controlPaddingX
                  text: modelData.label || Model.sourceLabel(modelData.source)
                  color: index === root.playOnIndex ? root.selectedText : root.foreground
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.title
                }
                MouseArea {
                  anchors.fill: parent
                  hoverEnabled: true
                  onPositionChanged: function(mouse) {
                    if (root.pointerMoved(mapToItem(null, mouse.x, mouse.y)))
                      root.playOnIndex = index
                  }
                  onClicked: {
                    root.playOnIndex = index
                    root.launchPlayOnChoice()
                  }
                }
              }
            }
            Text {
              text: "A / Enter  select   ·   B / Esc  back"
              color: root.foreground
              opacity: 0.5
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }
          }
        }
      }
    }
  }

  Timer {
    id: menuPersistTimer
    interval: 160
    repeat: true
    property int ticks: 0
    onTriggered: {
      if (!root.menuPinned || ticks >= 2) {
        console.warn("matt-dance.arcade: showQuickMenu persist stop pinned="
                     + root.menuPinned + " ticks=" + ticks)
        stop()
        ticks = 0
        return
      }
      ticks += 1
      console.warn("matt-dance.arcade: showQuickMenu persist tick=" + ticks
                   + " menu=" + (quickMenu && quickMenu.opened ? "open" : "closed"))
      Quickshell.execDetached([
        "omarchy-shell", "shell", "summon",
        Model.pluginId(root.manifest),
        '{"surface":"quickmenu","persist":true}'
      ])
    }
  }

  QuickMenu {
    id: quickMenu
    shell: root.shell
    manifest: root.manifest
    pluginRegistry: root.pluginRegistry
    service: root.service
    onDismissed: root.onQuickMenuDismissed()
  }

  FileView {
    id: libraryView
    path: root.libraryFile
    watchChanges: true
    onFileChanged: root.loadLibraryFromDisk()
    onLoaded: root.loadLibraryFromDisk()
  }

  FileView {
    id: stateView
    path: root.stateFile
    watchChanges: true
    onFileChanged: reload()
    onLoaded: root.loadStateFromDisk()
  }

  FileView {
    id: metaView
    path: root.metaFile
    watchChanges: true
    onFileChanged: root.loadMetaFromDisk()
    onLoaded: root.loadMetaFromDisk()
  }

  Process {
    id: cachedArtProcess
    stdout: StdioCollector {
      onStreamFinished: {
        if (!text || !String(text).length)
          return
        try {
          var data = JSON.parse(text)
          if (data && data.cachedArt)
            root.ingestCachedArt(data.cachedArt)
        } catch (e) {}
      }
    }
  }

  Process {
    id: metaProcess
    stdout: StdioCollector {
      onStreamFinished: {
        root.applyMetaStdout(text)
        root.loadMetaFromDisk()
      }
    }
    onExited: function(exitCode, exitStatus) {
      root.loadMetaFromDisk()
      if (exitCode !== 0)
        console.warn("matt-dance.arcade: overlay arcade-meta exited " + exitCode)
      if (!root.pendingMetaId)
        return
      var next = root.pendingMetaId
      var force = root.pendingMetaForce
      root.pendingMetaId = ""
      root.pendingMetaForce = false
      Qt.callLater(function() {
        if (force)
          root.startMeta(next, true)
        else if (root.focusedGame && root.focusedGame.id === next)
          root.ensureMeta(root.focusedGame)
      })
    }
  }

  Process {
    id: localScanProcess
    stdout: StdioCollector {
      onStreamFinished: {
        root.localScanPending = false
        if (libraryView && typeof libraryView.reload === "function")
          libraryView.reload()
        root.loadLibraryFromDisk()
      }
    }
    stderr: StdioCollector {
      onStreamFinished: {
        if (text && text.length)
          root.localScanError = text.trim()
      }
    }
    onExited: function(exitCode, exitStatus) {
      root.localScanPending = false
      if (exitCode !== 0)
        console.warn("matt-dance.arcade: overlay arcade-scan exited " + exitCode)
      root.loadLibraryFromDisk()
    }
  }

  onSelectedIndexChanged: root.updateFocused()
  onMetaFileChanged: {
    if (metaView && typeof metaView.reload === "function")
      metaView.reload()
    root.loadMetaFromDisk()
  }

  Component.onCompleted: {
    console.warn("matt-dance.arcade: overlay loaded; cache=" + root.libraryFile)
    root.loadLibraryFromDisk()
  }
}
