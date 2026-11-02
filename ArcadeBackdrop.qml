import QtQuick
import qs.Commons
import qs.Commons as Commons

// Full-window backdrop: theme-colored transparent fill, optional game tint,
// vignette, and a static grain overlay. Hyprland blurs whatever shows through.
Item {
  id: root

  property color themeBackground: Commons.Color.menu.background
  property color accent: Commons.Color.accent
  property real fillOpacity: 0.4
  property bool dynamicTint: true
  property bool motionFull: true
  property bool motionOff: false
  property bool active: true
  property string artUrl: ""

  readonly property int fadeMs: {
    if (root.motionOff)
      return 0
    if (typeof Style !== "undefined" && typeof Style.duration === "function")
      return root.motionFull ? Style.duration(420) : Style.duration(160)
    return root.motionFull ? 420 : 160
  }

  function themeRgba(alpha) {
    var c = root.themeBackground
    return Qt.rgba(c.r, c.g, c.b, Math.max(0, Math.min(1, alpha)))
  }

  // Two low-res copies of the focused hero. Downscale is the blur — no
  // live shader. Only the pair is loaded, and only while Arcade is open.
  property string tintA: ""
  property string tintB: ""
  property bool frontIsA: true

  onArtUrlChanged: root.swapTint()
  onDynamicTintChanged: root.swapTint()
  Component.onCompleted: root.swapTint()
  onActiveChanged: {
    if (!root.active) {
      root.tintA = ""
      root.tintB = ""
      return
    }
    root.swapTint()
  }

  function swapTint() {
    if (!root.active || !root.dynamicTint) {
      if (root.frontIsA)
        root.tintA = ""
      else
        root.tintB = ""
      return
    }
    var url = root.artUrl || ""
    var current = root.frontIsA ? root.tintA : root.tintB
    if (url === current)
      return
    if (root.frontIsA) {
      root.tintB = url
      root.frontIsA = false
    } else {
      root.tintA = url
      root.frontIsA = true
    }
  }

  // Theme wash. Wallpaper / Hyprland blur show through at 1 - fillOpacity.
  Rectangle {
    anchors.fill: parent
    color: root.themeRgba(root.fillOpacity)
  }

  Item {
    anchors.fill: parent
    visible: root.active && root.dynamicTint
    clip: true

    Image {
      id: tintImageA
      anchors.fill: parent
      source: root.active ? root.tintA : ""
      fillMode: Image.PreserveAspectCrop
      asynchronous: true
      cache: true
      smooth: true
      sourceSize.width: 48
      sourceSize.height: 27
      scale: 1.35
      opacity: (root.frontIsA && status === Image.Ready && root.tintA.length) ? 0.28 : 0
      Behavior on opacity { NumberAnimation { duration: root.fadeMs; easing.type: Easing.InOutQuad } }
    }

    Image {
      id: tintImageB
      anchors.fill: parent
      source: root.active ? root.tintB : ""
      fillMode: Image.PreserveAspectCrop
      asynchronous: true
      cache: true
      smooth: true
      sourceSize.width: 48
      sourceSize.height: 27
      scale: 1.35
      opacity: (!root.frontIsA && status === Image.Ready && root.tintB.length) ? 0.28 : 0
      Behavior on opacity { NumberAnimation { duration: root.fadeMs; easing.type: Easing.InOutQuad } }
    }

    // Soft accent veil so the wash still reads as Omarchy when art is dark.
    Rectangle {
      anchors.fill: parent
      color: {
        var a = root.accent
        return Qt.rgba(a.r, a.g, a.b, (tintImageA.opacity + tintImageB.opacity) > 0 ? 0.04 : 0)
      }
    }
  }

  // Edge vignette — two cheap linear gradients, no shader.
  Rectangle {
    anchors.fill: parent
    gradient: Gradient {
      orientation: Gradient.Vertical
      GradientStop { position: 0.0; color: Qt.rgba(0, 0, 0, 0.38) }
      GradientStop { position: 0.18; color: Qt.rgba(0, 0, 0, 0) }
      GradientStop { position: 0.82; color: Qt.rgba(0, 0, 0, 0) }
      GradientStop { position: 1.0; color: Qt.rgba(0, 0, 0, 0.42) }
    }
  }

  Rectangle {
    anchors.fill: parent
    gradient: Gradient {
      orientation: Gradient.Horizontal
      GradientStop { position: 0.0; color: Qt.rgba(0, 0, 0, 0.22) }
      GradientStop { position: 0.12; color: Qt.rgba(0, 0, 0, 0) }
      GradientStop { position: 0.88; color: Qt.rgba(0, 0, 0, 0) }
      GradientStop { position: 1.0; color: Qt.rgba(0, 0, 0, 0.22) }
    }
  }

  Image {
    id: grain
    anchors.fill: parent
    source: Qt.resolvedUrl("assets/grain.png")
    fillMode: Image.Tile
    asynchronous: true
    cache: true
    visible: status === Image.Ready && !root.motionOff
    opacity: root.motionFull ? grainPulse.opacity : 0.045
    z: 8
  }

  SequentialAnimation {
    id: grainPulse
    property real opacity: 0.045
    running: root.active && root.motionFull && grain.status === Image.Ready
    loops: Animation.Infinite
    NumberAnimation { target: grainPulse; property: "opacity"; from: 0.03; to: 0.06; duration: 4200; easing.type: Easing.InOutSine }
    NumberAnimation { target: grainPulse; property: "opacity"; from: 0.06; to: 0.03; duration: 4200; easing.type: Easing.InOutSine }
  }
}
