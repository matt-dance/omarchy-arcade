import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Wayland
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "ArcadeModel.js" as Model

// In-game quick menu. Opened by Guide tap while a game is running.
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

  readonly property var actions: [
    { id: "resume", label: "Resume", hint: "A" },
    { id: "arcade", label: "Back to Arcade", hint: "Y" },
    { id: "volume_up", label: "Volume up", hint: "" },
    { id: "volume_down", label: "Volume down", hint: "" },
    { id: "screenshot", label: "Screenshot", hint: "" },
    { id: "record", label: "Toggle recording", hint: "" },
    { id: "close", label: "Close game", hint: "Hold B" },
    { id: "force", label: "Force quit", hint: "Hold Guide+Select+Start" }
  ]

  function open(payloadJson) {
    root.opened = true
    root.selectedIndex = 0
    Qt.callLater(function() { keyCatcher.forceActiveFocus() })
  }

  function close() {
    root.opened = false
  }

  function dismiss() {
    root.close()
  }

  function runAction(id) {
    if (id === "resume") {
      root.dismiss()
      if (root.service) root.service.focusGame()
    } else if (id === "arcade") {
      root.dismiss()
      if (root.service) root.service.toggleArcade()
    } else if (id === "volume_up") {
      Quickshell.execDetached(["omarchy-audio-output-volume", "raise"])
    } else if (id === "volume_down") {
      Quickshell.execDetached(["omarchy-audio-output-volume", "lower"])
    } else if (id === "screenshot") {
      Quickshell.execDetached(["omarchy-capture-screenshot"])
    } else if (id === "record") {
      Quickshell.execDetached(["omarchy-capture-screenrecording"])
    } else if (id === "close") {
      root.dismiss()
      if (root.service) root.service.closeGame(false)
    } else if (id === "force") {
      root.dismiss()
      if (root.service) root.service.closeGame(true)
    }
  }

  Connections {
    target: root.service
    function onQuickMenuRequested() {
      if (!root.opened) root.open("{}")
      else root.dismiss()
    }
    function onNav(dir, repeat) {
      if (!root.opened) return
      if (dir === "up")
        root.selectedIndex = (root.selectedIndex - 1 + root.actions.length) % root.actions.length
      else if (dir === "down")
        root.selectedIndex = (root.selectedIndex + 1) % root.actions.length
    }
    function onIntent(name) {
      if (!root.opened) return
      if (name === "accept") root.runAction(root.actions[root.selectedIndex].id)
      else if (name === "back") root.dismiss()
    }
  }

  PanelWindow {
    id: panel
    visible: root.opened
    anchors { top: true; bottom: true; right: true }
    implicitWidth: Style.space(360)
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
          text: "Quick Menu"
          color: Commons.Color.menu.text
          font.family: Style.font.menuFamily
          font.pixelSize: Style.font.heading
          font.bold: true
        }
        Text {
          text: (root.service && root.service.sessionGame)
                ? root.service.sessionGame.title
                : "No game running"
          color: Commons.Color.menu.text
          opacity: 0.65
          font.family: Style.font.menuFamily
          font.pixelSize: Style.font.body
          elide: Text.ElideRight
          Layout.fillWidth: true
        }

        Repeater {
          model: root.actions
          Rectangle {
            required property var modelData
            required property int index
            Layout.fillWidth: true
            Layout.preferredHeight: Style.space(44)
            radius: Style.cornerRadius
            color: index === root.selectedIndex
                   ? Commons.Color.menu.selectedBackground
                   : "transparent"

            RowLayout {
              anchors.fill: parent
              anchors.leftMargin: Style.spacing.controlPaddingX
              anchors.rightMargin: Style.spacing.controlPaddingX
              Text {
                text: modelData.label
                color: index === root.selectedIndex
                       ? Commons.Color.menu.selectedText
                       : Commons.Color.menu.text
                font.family: Style.font.menuFamily
                font.pixelSize: Style.font.title
                Layout.fillWidth: true
              }
              Text {
                text: modelData.hint
                color: Commons.Color.menu.text
                opacity: 0.45
                font.family: Style.font.menuFamily
                font.pixelSize: Style.font.caption
              }
            }

            MouseArea {
              anchors.fill: parent
              hoverEnabled: true
              onEntered: root.selectedIndex = index
              onClicked: root.runAction(modelData.id)
            }
          }
        }

        Item { Layout.fillHeight: true }

        Text {
          text: "B / Esc  close"
          color: Commons.Color.menu.text
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
            root.dismiss(); event.accepted = true
          } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
            root.runAction(root.actions[root.selectedIndex].id); event.accepted = true
          } else if (event.key === Qt.Key_Up || event.key === Qt.Key_K) {
            root.selectedIndex = (root.selectedIndex - 1 + root.actions.length) % root.actions.length
            event.accepted = true
          } else if (event.key === Qt.Key_Down || event.key === Qt.Key_J) {
            root.selectedIndex = (root.selectedIndex + 1) % root.actions.length
            event.accepted = true
          }
        }
      }
    }
  }
}
