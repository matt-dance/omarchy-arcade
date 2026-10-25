import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Commons as Commons

// Controller on-screen keyboard for Arcade search.
// D-pad moves, A types the focused key, X backspace, Y space, B / Start close.
// Arcade.qml routes nav and intents here while `opened` is true.
Item {
  id: root

  property bool opened: false
  property int row: 1
  property int col: 0
  property string fontFamily: Style.font.menuFamily
  property color foreground: Commons.Color.menu.text

  signal typed(string text)
  signal backspace()
  signal cleared()
  signal done()

  readonly property var rows: [
    ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"],
    ["q", "w", "e", "r", "t", "y", "u", "i", "o", "p"],
    ["a", "s", "d", "f", "g", "h", "j", "k", "l", "'"],
    ["z", "x", "c", "v", "b", "n", "m", "-", ":", "."],
    ["Space", "Delete", "Clear", "Done"]
  ]

  implicitHeight: oskColumn.implicitHeight + Style.spacing.md * 2
  visible: root.opened

  function open() {
    root.row = 1
    root.col = 0
    root.opened = true
  }

  function close() {
    root.opened = false
  }

  function keyAt(r, c) {
    var line = root.rows[r] || []
    return line[Math.max(0, Math.min(line.length - 1, c))] || ""
  }

  function move(dir) {
    var n = root.rows.length
    if (dir === "up" || dir === "down") {
      var oldLen = root.rows[root.row].length
      root.row = (root.row + (dir === "down" ? 1 : -1) + n) % n
      var newLen = root.rows[root.row].length
      // Keep roughly the same horizontal position between the 10-key rows
      // and the 4 wide keys on the bottom row.
      root.col = Math.min(newLen - 1, Math.floor(root.col * newLen / oldLen))
    } else if (dir === "left" || dir === "right") {
      var len = root.rows[root.row].length
      root.col = (root.col + (dir === "right" ? 1 : -1) + len) % len
    }
  }

  function press(key) {
    if (key === "Space") root.typed(" ")
    else if (key === "Delete") root.backspace()
    else if (key === "Clear") root.cleared()
    else if (key === "Done") root.done()
    else if (key) root.typed(key)
  }

  function activate() {
    root.press(root.keyAt(root.row, root.col))
  }

  Rectangle {
    anchors.fill: parent
    radius: Style.cornerRadius
    color: Qt.rgba(0, 0, 0, 0.35)
    border.color: Commons.Color.menu.border
    border.width: 1
  }

  ColumnLayout {
    id: oskColumn
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.top: parent.top
    anchors.margins: Style.spacing.md
    spacing: Style.spacing.xs

    Repeater {
      model: root.rows
      RowLayout {
        id: keyRow
        required property var modelData
        required property int index
        Layout.fillWidth: true
        spacing: Style.spacing.xs

        Repeater {
          model: keyRow.modelData
          Rectangle {
            required property var modelData
            required property int index
            readonly property bool focused: root.row === keyRow.index && root.col === index
            Layout.fillWidth: true
            Layout.preferredHeight: Style.space(44)
            radius: Style.cornerRadius
            color: focused ? Commons.Color.menu.selectedBackground : Qt.rgba(1, 1, 1, 0.06)
            border.width: focused ? 2 : 1
            border.color: focused ? Commons.Color.accent : Qt.rgba(1, 1, 1, 0.14)

            Text {
              anchors.centerIn: parent
              text: modelData
              color: parent.focused ? Commons.Color.menu.selectedText : root.foreground
              font.family: root.fontFamily
              font.pixelSize: modelData.length > 1 ? Style.font.body : Style.font.title
              font.bold: parent.focused
            }

            MouseArea {
              anchors.fill: parent
              onClicked: {
                root.row = keyRow.index
                root.col = index
                root.activate()
              }
            }
          }
        }
      }
    }
  }
}
