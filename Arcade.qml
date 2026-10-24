import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Wayland
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "ArcadeModel.js" as Model

// Fullscreen Arcade library overlay.
// Summon: omarchy-shell shell toggle matt-dance.arcade '{}'
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
  readonly property int gridGap: Style.space(Math.round(16 * uiScale))

  function open(payloadJson) {
    root.opened = true
    root.screen = "home"
    root.filterText = ""
    root.selectedIndex = 0
    root.refreshList()
    if (root.service) {
      if (typeof root.service.setUiMode === "function")
        root.service.setUiMode(true)
      if (!root.service.games || root.service.games.length === 0)
        root.service.rescan()
    }
    Qt.callLater(function() { keyCatcher.forceActiveFocus() })
  }

  function close() {
    root.opened = false
    if (root.service && typeof root.service.setUiMode === "function")
      root.service.setUiMode(false)
  }

  function dismiss() {
    root.close()
    if (root.shell && typeof root.shell.hide === "function")
      root.shell.hide(Model.pluginId(root.manifest))
  }

  function refreshList() {
    var games = (root.service && root.service.games) ? root.service.games : []
    if (root.screen === "home" && !root.filterText)
      root.visibleGames = Model.recentGames(games, 24)
    else
      root.visibleGames = Model.filterGames(games, root.filterText)
    if (root.selectedIndex >= root.visibleGames.length)
      root.selectedIndex = Math.max(0, root.visibleGames.length - 1)
    var n = games.length
    if (root.service && root.service.lastAction === "scan:pending")
      root.statusText = "Scanning library…"
    else if (n === 0)
      root.statusText = "No games found — install Steam, Heroic, or add .desktop games"
    else if (root.screen === "home")
      root.statusText = "Recently played · " + n + " games total"
    else
      root.statusText = root.visibleGames.length + " of " + n + " games"
  }

  function moveSelection(dx, dy) {
    var cols = Math.max(1, Math.floor((grid.width + gridGap) / (cardW + gridGap)))
    var count = root.visibleGames.length
    if (count === 0) return
    var idx = root.selectedIndex
    if (dx !== 0)
      idx = Math.max(0, Math.min(count - 1, idx + dx))
    if (dy !== 0)
      idx = Math.max(0, Math.min(count - 1, idx + dy * cols))
    root.selectedIndex = idx
    grid.positionViewAtIndex(idx, GridView.Contain)
  }

  function activateSelected() {
    if (root.selectedIndex < 0 || root.selectedIndex >= root.visibleGames.length)
      return
    var game = root.visibleGames[root.selectedIndex]
    if (root.service && typeof root.service.launchGame === "function")
      root.service.launchGame(game)
  }

  function handleIntent(name) {
    if (!root.opened) return
    if (name === "accept") root.activateSelected()
    else if (name === "back") {
      if (root.filterText) root.filterText = ""
      else if (root.screen !== "home") root.screen = "home"
      else root.dismiss()
      root.refreshList()
    } else if (name === "search") {
      root.screen = "search"
      root.refreshList()
    } else if (name === "menu" || name === "options") {
      root.screen = root.screen === "settings" ? "home" : "settings"
      root.refreshList()
    } else if (name === "tab_next") {
      root.screen = root.screen === "home" ? "library" : "home"
      root.selectedIndex = 0
      root.refreshList()
    } else if (name === "tab_prev") {
      root.screen = root.screen === "library" ? "home" : "library"
      root.selectedIndex = 0
      root.refreshList()
    } else if (name === "page_down") root.moveSelection(0, 2)
    else if (name === "page_up") root.moveSelection(0, -2)
  }

  Connections {
    target: root.service
    function onLibraryChanged() { root.refreshList() }
    function onNav(dir, repeat) {
      if (!root.opened) return
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
            text: "Config: ~/.config/omarchy/arcade/arcade.toml\nBindings reload live. SteamGridDB key (optional): ~/.config/omarchy/arcade/steamgriddb.key\n\nControllers connected: " + ((root.service && root.service.pads) ? root.service.pads.length : 0) + "\nDaemon: " + ((root.service && root.service.daemonReady) ? "ready" : "starting") + "\n\nHARDWARE TEST NEEDED: controller navigation, Guide chords, game launch/return, idle inhibit."
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

        // Game grid
        GridView {
          id: grid
          Layout.fillWidth: true
          Layout.fillHeight: true
          visible: root.screen !== "settings"
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
              color: index === root.selectedIndex ? root.selectedBackground : Qt.rgba(0, 0, 0, 0.25)
              border.width: index === root.selectedIndex ? Math.max(2, Style.space(2)) : 1
              border.color: index === root.selectedIndex ? Commons.Color.accent : Qt.rgba(1, 1, 1, 0.12)

              // Cover art or typographic card
              Image {
                id: cover
                anchors.fill: parent
                anchors.margins: 2
                source: (modelData.art && modelData.art.cover) ? modelData.art.cover : ""
                fillMode: Image.PreserveAspectCrop
                asynchronous: true
                visible: status === Image.Ready
                sourceSize.width: root.cardW
                sourceSize.height: root.cardH
              }

              Rectangle {
                anchors.fill: parent
                anchors.margins: 2
                visible: !cover.visible
                color: "transparent"
                Column {
                  anchors.centerIn: parent
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

              // Source badge
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
                  text: Model.sourceLabel(modelData.source)
                  color: root.foreground
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                }
              }

              MouseArea {
                anchors.fill: parent
                hoverEnabled: true
                onEntered: root.selectedIndex = index
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
            model: [
              { key: "A", label: "Play" },
              { key: "B", label: "Back" },
              { key: "Y", label: "Search" },
              { key: "LB/RB", label: "Home/Library" },
              { key: "Start", label: "Settings" },
              { key: "Esc", label: "Close" }
            ]
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
          if (event.key === Qt.Key_Escape) {
            if (root.filterText) {
              root.filterText = ""
              searchInput.text = ""
              root.refreshList()
            } else {
              root.dismiss()
            }
            event.accepted = true
          } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
            if (root.screen === "settings") {
              root.screen = "home"
              root.refreshList()
            } else {
              root.activateSelected()
            }
            event.accepted = true
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
    }
  }
}
