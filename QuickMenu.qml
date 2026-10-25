import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "ArcadeModel.js" as Model

// Steam Deck-style system menu. Opened by Guide tap while a game is running.
// Hosted as a child of Arcade.qml (not a plugin `panel` kind — Omarchy's
// shell toggle prefers panel over overlay when both are declared).
Item {
  id: root

  property string omarchyPath: Quickshell.env("OMARCHY_PATH")
  property var shell: null
  property var manifest: null
  property var pluginRegistry: null
  property var service: null

  property bool opened: false
  property int selectedIndex: 0
  property var items: []
  property var status: ({})
  property string view: "menu"   // menu | picker | confirm
  property var pickerItem: null
  property int pickerIndex: 0
  property var confirmItem: null
  property string statusLine: ""
  property bool busy: false

  signal dismissed()
  signal keysRequested()

  readonly property string pluginDir: Model.pluginDirPath(Quickshell.env("HOME") || "", root.manifest)
  readonly property string sysBin: root.pluginDir + "/bin/arcade-sys"
  readonly property color foreground: Commons.Color.menu.text
  readonly property color selectedBackground: Commons.Color.menu.selectedBackground
  readonly property color selectedText: Commons.Color.menu.selectedText

  readonly property var fallbackItems: [
    { id: "sec-game", kind: "header", label: "Game", section: "Game" },
    { id: "resume", kind: "action", label: "Resume", section: "Game" },
    { id: "close", kind: "action", label: "Close game", section: "Game" },
    { id: "force", kind: "action", label: "Force quit", section: "Game" },
    { id: "arcade", kind: "action", label: "Back to Arcade", section: "Game" },
    { id: "sec-arcade", kind: "header", label: "Arcade", section: "Arcade" },
    { id: "arcade_keys", kind: "action", label: "Metadata keys", section: "Arcade" },
    { id: "sec-power", kind: "header", label: "Power", section: "Power" },
    { id: "lock", kind: "action", label: "Lock", section: "Power", confirm: true },
    { id: "suspend", kind: "action", label: "Suspend", section: "Power", confirm: true },
    { id: "reboot", kind: "action", label: "Restart", section: "Power", confirm: true },
    { id: "shutdown", kind: "action", label: "Shut down", section: "Power", confirm: true },
    { id: "logout", kind: "action", label: "Log out", section: "Power", confirm: true }
  ]

  function sessionTitle() {
    return (root.service && root.service.sessionGame && root.service.sessionGame.title)
           ? root.service.sessionGame.title
           : "No game running"
  }

  function focusableItems() {
    var out = []
    var list = root.items && root.items.length ? root.items : root.fallbackItems
    for (var i = 0; i < list.length; i++) {
      if (list[i] && list[i].kind !== "header")
        out.push({ item: list[i], index: i })
    }
    return out
  }

  function currentEntry() {
    var focusable = root.focusableItems()
    if (!focusable.length)
      return null
    var idx = Math.max(0, Math.min(focusable.length - 1, root.selectedIndex))
    return focusable[idx]
  }

  function currentItem() {
    var entry = root.currentEntry()
    return entry ? entry.item : null
  }

  function clampSelection() {
    var n = root.focusableItems().length
    if (n === 0)
      root.selectedIndex = 0
    else if (root.selectedIndex >= n)
      root.selectedIndex = n - 1
    else if (root.selectedIndex < 0)
      root.selectedIndex = 0
  }

  function moveSelection(dir) {
    var n = root.focusableItems().length
    if (!n) return
    root.selectedIndex = (root.selectedIndex + dir + n) % n
    root.ensureVisible()
  }

  function ensureVisible() {
    var entry = root.currentEntry()
    if (!entry || !menuFlick)
      return
    var kids = menuColumn.children
    if (entry.index < 0 || entry.index >= kids.length)
      return
    var item = kids[entry.index]
    if (!item)
      return
    var y = item.y
    var h = item.height
    if (y < menuFlick.contentY)
      menuFlick.contentY = Math.max(0, y - 8)
    else if (y + h > menuFlick.contentY + menuFlick.height)
      menuFlick.contentY = Math.max(0, y + h - menuFlick.height + 8)
  }

  function batteryLine() {
    var bat = (root.status && root.status.battery) ? root.status.battery : null
    if (!bat)
      return ""
    var parts = []
    if (bat.system && bat.system.percent !== undefined && bat.system.percent !== null)
      parts.push("System " + bat.system.percent + "%" + (bat.system.charging ? " ⚡" : ""))
    var pads = bat.controllers || []
    for (var i = 0; i < pads.length; i++) {
      var c = pads[i]
      if (c.percent === undefined || c.percent === null)
        continue
      parts.push((c.name || "Controller") + " " + c.percent + "%")
    }
    return parts.join("  ·  ")
  }

  function pythonCmd(extra) {
    var args = ["/usr/bin/python3", "-u", root.sysBin]
    for (var i = 0; i < extra.length; i++)
      args.push(extra[i])
    return args
  }

  function refreshMenu() {
    if (statusProcess.running)
      statusProcess.running = false
    statusProcess.command = root.pythonCmd(["items", "--session-title", root.sessionTitle()])
    statusProcess.running = true
  }

  function applyMenuPayload(text) {
    if (!text || !String(text).trim())
      return
    try {
      var data = JSON.parse(text)
      root.status = data.status || {}
      var next = data.items || []
      root.items = next.length ? next : root.fallbackItems
      root.clampSelection()
      if (!root.statusLine)
        root.statusLine = ""
      var tools = root.status.tools || {}
      var toolKeys = Object.keys(tools)
      var found = []
      for (var i = 0; i < toolKeys.length; i++) {
        if (tools[toolKeys[i]])
          found.push(toolKeys[i] + "=" + tools[toolKeys[i]])
      }
      console.warn("matt-dance.arcade: sysmenu payload items=" + root.items.length
                   + " tools=" + (found.length ? found.join(",") : "none"))
    } catch (e) {
      console.warn("matt-dance.arcade: sysmenu payload parse failed: " + e
                   + " text=" + String(text || "").slice(0, 180))
      if (!root.items.length)
        root.items = root.fallbackItems
    }
  }

  function runSys(action, extra) {
    extra = extra || {}
    var args = ["do", action, "--session-title", root.sessionTitle()]
    var keys = Object.keys(extra)
    for (var i = 0; i < keys.length; i++) {
      var k = keys[i]
      if (extra[k] === undefined || extra[k] === null)
        continue
      args.push("--" + k)
      args.push(String(extra[k]))
    }
    if (actionProcess.running)
      actionProcess.running = false
    root.busy = true
    if (action === "bluetooth_scan")
      root.statusLine = "Scanning for controllers and headsets…"
    actionProcess.command = root.pythonCmd(args)
    actionProcess.running = true
  }

  function tapMango() {
    if (root.service && typeof root.service.tapKeys === "function")
      root.service.tapKeys("SHIFT_R + F12")
  }

  function runGameAction(id) {
    if (id === "resume") {
      root.dismiss()
      if (root.service) root.service.focusGame()
    } else if (id === "arcade") {
      root.dismiss()
      if (root.service) root.service.toggleArcade()
    } else if (id === "close") {
      root.dismiss()
      if (root.service) root.service.closeGame(false)
    } else if (id === "force") {
      root.dismiss()
      if (root.service) root.service.closeGame(true)
    }
  }

  function runItem(item) {
    if (!item) return
    if (item.id === "resume" || item.id === "arcade" || item.id === "close" || item.id === "force") {
      root.runGameAction(item.id)
      return
    }
    if (item.id === "mangohud") {
      root.tapMango()
      return
    }
    if (item.id === "arcade_keys") {
      root.dismiss()
      root.keysRequested()
      return
    }
    var extra = item.arg || {}
    root.runSys(item.id, extra)
  }

  function activateCurrent() {
    if (root.view === "confirm") {
      var confirmed = root.confirmItem
      root.view = "menu"
      root.confirmItem = null
      if (confirmed)
        root.runItem(confirmed)
      return
    }
    if (root.view === "picker") {
      var options = (root.pickerItem && root.pickerItem.options) ? root.pickerItem.options : []
      if (!options.length) {
        root.view = "menu"
        return
      }
      var choice = options[root.pickerIndex]
      var picker = root.pickerItem
      root.view = "menu"
      root.pickerItem = null
      if (picker && choice) {
        var extra = { value: choice.id || choice.mac || choice.label }
        if (choice.id) extra.id = choice.id
        if (choice.mac) extra.mac = choice.mac
        if (picker.id === "wifi_connect") extra.ssid = choice.id || choice.label
        if (picker.id === "output") extra.sink = choice.id
        if (picker.id === "profile_set") extra.profile = choice.id || choice.label
        root.runSys(picker.id, extra)
      }
      return
    }
    var item = root.currentItem()
    if (!item) return
    if (item.confirm) {
      root.confirmItem = item
      root.view = "confirm"
      return
    }
    if (item.kind === "picker" && item.options && item.options.length) {
      root.pickerItem = item
      root.pickerIndex = 0
      for (var i = 0; i < item.options.length; i++) {
        if (item.options[i].current)
          root.pickerIndex = i
      }
      root.view = "picker"
      return
    }
    if (item.kind === "slider")
      return
    if (item.kind === "toggle") {
      root.runSys(item.id, item.arg || {})
      return
    }
    root.runItem(item)
  }

  function nudgeSlider(delta) {
    var item = root.currentItem()
    if (!item || item.kind !== "slider")
      return
    var step = item.step || 5
    if (item.id === "volume")
      root.runSys("volume_nudge", { delta: delta < 0 ? -step : step })
    else if (item.id === "brightness")
      root.runSys("brightness_nudge", { delta: delta < 0 ? -step : step })
    if (item.value !== undefined && item.value !== null) {
      var next = Math.max(item.min || 0, Math.min(item.max || 100, Number(item.value) + (delta < 0 ? -step : step)))
      item.value = next
      root.items = root.items.slice()
    }
  }

  function handleNav(dir) {
    if (!root.opened) return
    if (root.view === "confirm")
      return
    if (root.view === "picker") {
      var options = (root.pickerItem && root.pickerItem.options) ? root.pickerItem.options : []
      if (!options.length) return
      if (dir === "up" || dir === "left")
        root.pickerIndex = (root.pickerIndex - 1 + options.length) % options.length
      else if (dir === "down" || dir === "right")
        root.pickerIndex = (root.pickerIndex + 1) % options.length
      return
    }
    var item = root.currentItem()
    if (item && item.kind === "slider" && (dir === "left" || dir === "right")) {
      root.nudgeSlider(dir === "left" ? -1 : 1)
      return
    }
    if (dir === "up") root.moveSelection(-1)
    else if (dir === "down") root.moveSelection(1)
  }

  function handleBack() {
    if (root.view === "confirm") {
      root.view = "menu"
      root.confirmItem = null
      return
    }
    if (root.view === "picker") {
      root.view = "menu"
      root.pickerItem = null
      return
    }
    root.dismiss()
  }

  function open(payloadJson) {
    console.warn("matt-dance.arcade: QuickMenu.open already=" + root.opened
                 + " session=" + root.sessionTitle())
    root.opened = true
    root.selectedIndex = 0
    root.view = "menu"
    root.confirmItem = null
    root.pickerItem = null
    root.statusLine = ""
    if (!root.items.length)
      root.items = root.fallbackItems
    root.refreshMenu()
    Qt.callLater(function() { keyCatcher.forceActiveFocus() })
  }

  function close() {
    root.opened = false
    root.view = "menu"
  }

  function dismiss() {
    console.warn("matt-dance.arcade: QuickMenu.dismiss")
    root.close()
    root.dismissed()
  }

  Connections {
    target: root.service
    function onQuickMenuRequested() {
      console.warn("matt-dance.arcade: QuickMenu.quickMenuRequested opened=" + root.opened)
      if (!root.opened) root.open("{}")
      else root.dismiss()
    }
    function onNav(dir, repeat) {
      root.handleNav(dir)
    }
    function onIntent(name) {
      if (!root.opened) return
      if (name === "accept") root.activateCurrent()
      else if (name === "back") root.handleBack()
    }
  }

  PanelWindow {
    id: panel
    visible: root.opened
    anchors { top: true; bottom: true; right: true }
    implicitWidth: Style.space(440)
    color: "transparent"
    WlrLayershell.namespace: "matt-dance-arcade-quickmenu"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: root.opened ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None
    exclusionMode: ExclusionMode.Ignore

    Rectangle {
      anchors.fill: parent
      anchors.margins: Style.gapsOut
      color: Commons.Color.menu.background
      radius: Style.cornerRadius
      border.color: Commons.Color.menu.border
      border.width: 1

      ColumnLayout {
        anchors.fill: parent
        anchors.margins: Style.spacing.panelPadding
        spacing: Style.spacing.sm

        Text {
          text: "System"
          color: root.foreground
          font.family: Style.font.menuFamily
          font.pixelSize: Style.font.heading
          font.bold: true
        }
        Text {
          text: root.sessionTitle()
          color: root.foreground
          opacity: 0.65
          font.family: Style.font.menuFamily
          font.pixelSize: Style.font.body
          elide: Text.ElideRight
          Layout.fillWidth: true
        }
        Text {
          visible: root.batteryLine().length > 0
          text: root.batteryLine()
          color: root.foreground
          opacity: 0.7
          font.family: Style.font.menuFamily
          font.pixelSize: Style.font.caption
          elide: Text.ElideRight
          Layout.fillWidth: true
          wrapMode: Text.WordWrap
        }
        Text {
          visible: root.statusLine.length > 0
          text: root.statusLine
          color: Commons.Color.accent
          font.family: Style.font.menuFamily
          font.pixelSize: Style.font.caption
          elide: Text.ElideRight
          Layout.fillWidth: true
        }

        // Confirm
        ColumnLayout {
          Layout.fillWidth: true
          Layout.fillHeight: true
          visible: root.view === "confirm"
          spacing: Style.spacing.md

          Text {
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            text: root.confirmItem
                  ? ("Press A to confirm " + (root.confirmItem.label || "this") + ".")
                  : "Confirm?"
            color: root.foreground
            font.family: Style.font.menuFamily
            font.pixelSize: Style.font.title
          }
          Text {
            text: "A confirm   ·   B cancel"
            color: root.foreground
            opacity: 0.55
            font.family: Style.font.menuFamily
            font.pixelSize: Style.font.caption
          }
          Item { Layout.fillHeight: true }
        }

        // Picker
        Flickable {
          Layout.fillWidth: true
          Layout.fillHeight: true
          visible: root.view === "picker"
          clip: true
          contentWidth: width
          contentHeight: pickerColumn.implicitHeight
          boundsBehavior: Flickable.StopAtBounds

          Column {
            id: pickerColumn
            width: parent.width
            spacing: Style.spacing.xs

            Text {
              text: root.pickerItem ? root.pickerItem.label : "Choose"
              color: root.foreground
              font.family: Style.font.menuFamily
              font.pixelSize: Style.font.title
              font.bold: true
              width: parent.width
            }
            Repeater {
              model: (root.pickerItem && root.pickerItem.options) ? root.pickerItem.options : []
              Rectangle {
                required property var modelData
                required property int index
                width: pickerColumn.width
                height: Style.space(44)
                radius: Style.cornerRadius
                color: index === root.pickerIndex ? root.selectedBackground : "transparent"
                Text {
                  anchors.verticalCenter: parent.verticalCenter
                  anchors.left: parent.left
                  anchors.leftMargin: Style.spacing.controlPaddingX
                  text: modelData.label || modelData.name || modelData.id || ""
                  color: index === root.pickerIndex ? root.selectedText : root.foreground
                  font.family: Style.font.menuFamily
                  font.pixelSize: Style.font.title
                }
                MouseArea {
                  anchors.fill: parent
                  hoverEnabled: true
                  onEntered: root.pickerIndex = index
                  onClicked: {
                    root.pickerIndex = index
                    root.activateCurrent()
                  }
                }
              }
            }
          }
        }

        // Menu
        Flickable {
          id: menuFlick
          Layout.fillWidth: true
          Layout.fillHeight: true
          visible: root.view === "menu"
          clip: true
          contentWidth: width
          contentHeight: menuColumn.implicitHeight
          boundsBehavior: Flickable.StopAtBounds

          Column {
            id: menuColumn
            width: parent.width
            spacing: Style.spacing.xs

            Repeater {
              model: root.items && root.items.length ? root.items : root.fallbackItems
              Rectangle {
                required property var modelData
                required property int index
                width: menuColumn.width
                height: modelData.kind === "header" ? Style.space(28) : Style.space(modelData.kind === "slider" ? 56 : 44)
                radius: Style.cornerRadius
                color: {
                  var entry = root.currentEntry()
                  return (root.view === "menu" && entry && entry.index === index)
                         ? root.selectedBackground
                         : "transparent"
                }

                ColumnLayout {
                  anchors.fill: parent
                  anchors.leftMargin: Style.spacing.controlPaddingX
                  anchors.rightMargin: Style.spacing.controlPaddingX
                  spacing: 2

                  Text {
                    visible: modelData.kind === "header"
                    text: modelData.label
                    color: Commons.Color.accent
                    font.family: Style.font.menuFamily
                    font.pixelSize: Style.font.caption
                    font.bold: true
                    font.capitalization: Font.AllUppercase
                  }

                  RowLayout {
                    visible: modelData.kind !== "header"
                    Layout.fillWidth: true
                    Text {
                      text: modelData.label
                      color: {
                        var entry = root.currentEntry()
                        return (entry && entry.index === index) ? root.selectedText : root.foreground
                      }
                      font.family: Style.font.menuFamily
                      font.pixelSize: Style.font.title
                      Layout.fillWidth: true
                      elide: Text.ElideRight
                    }
                    Text {
                      visible: modelData.kind === "toggle"
                      text: modelData.value ? "On" : "Off"
                      color: root.foreground
                      opacity: 0.55
                      font.family: Style.font.menuFamily
                      font.pixelSize: Style.font.caption
                    }
                    Text {
                      visible: modelData.kind === "slider" && modelData.value !== undefined && modelData.value !== null
                      text: String(modelData.value) + "%"
                      color: root.foreground
                      opacity: 0.55
                      font.family: Style.font.menuFamily
                      font.pixelSize: Style.font.caption
                    }
                  }

                  Rectangle {
                    visible: modelData.kind === "slider"
                    Layout.fillWidth: true
                    Layout.preferredHeight: 4
                    radius: 2
                    color: Qt.rgba(1, 1, 1, 0.12)
                    Rectangle {
                      width: parent.width * Math.max(0, Math.min(1, (Number(modelData.value) || 0) / 100))
                      height: parent.height
                      radius: 2
                      color: Commons.Color.accent
                    }
                  }
                }

                MouseArea {
                  anchors.fill: parent
                  enabled: modelData.kind !== "header"
                  hoverEnabled: true
                  onEntered: {
                    var focusable = root.focusableItems()
                    for (var i = 0; i < focusable.length; i++) {
                      if (focusable[i].index === index)
                        root.selectedIndex = i
                    }
                  }
                  onClicked: {
                    var focusable = root.focusableItems()
                    for (var i = 0; i < focusable.length; i++) {
                      if (focusable[i].index === index)
                        root.selectedIndex = i
                    }
                    root.activateCurrent()
                  }
                }
              }
            }
          }
        }

        Text {
          text: root.view === "confirm"
                ? "A confirm   ·   B cancel"
                : (root.view === "picker"
                   ? "A select   ·   B back"
                   : "A select   ·   Left/Right sliders   ·   B close")
          color: root.foreground
          opacity: 0.45
          font.family: Style.font.menuFamily
          font.pixelSize: Style.font.caption
        }
      }

      Item {
        id: keyCatcher
        anchors.fill: parent
        focus: true
        Keys.onPressed: function(event) {
          if (event.key === Qt.Key_Escape || event.key === Qt.Key_Backspace) {
            root.handleBack(); event.accepted = true
          } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
            root.activateCurrent(); event.accepted = true
          } else if (event.key === Qt.Key_Up || event.key === Qt.Key_K) {
            root.handleNav("up"); event.accepted = true
          } else if (event.key === Qt.Key_Down || event.key === Qt.Key_J) {
            root.handleNav("down"); event.accepted = true
          } else if (event.key === Qt.Key_Left || event.key === Qt.Key_H) {
            root.handleNav("left"); event.accepted = true
          } else if (event.key === Qt.Key_Right || event.key === Qt.Key_L) {
            root.handleNav("right"); event.accepted = true
          }
        }
      }
    }
  }

  Process {
    id: statusProcess
    stdout: StdioCollector {
      onStreamFinished: root.applyMenuPayload(text)
    }
    stderr: StdioCollector {
      onStreamFinished: {
        if (text && text.length)
          console.warn("matt-dance.arcade: arcade-sys " + text.trim())
      }
    }
    onExited: function(exitCode, exitStatus) {
      console.warn("matt-dance.arcade: arcade-sys items exit=" + exitCode
                   + " items=" + (root.items ? root.items.length : 0))
      if (exitCode !== 0 && (!root.items || !root.items.length))
        root.items = root.fallbackItems
    }
  }

  Process {
    id: actionProcess
    stdout: StdioCollector {
      onStreamFinished: {
        root.busy = false
        if (!text || !String(text).trim())
          return
        try {
          var data = JSON.parse(text)
          if (data.discovered)
            root.statusLine = data.discovered.length
                              ? ("Found " + data.discovered.length + " device(s)")
                              : "No new devices"
          if (data.items) {
            root.items = data.items
            if (data.status)
              root.status = data.status
            root.clampSelection()
            return
          }
        } catch (e) {}
        root.refreshMenu()
      }
    }
    onExited: function(exitCode, exitStatus) {
      root.busy = false
    }
  }
}
