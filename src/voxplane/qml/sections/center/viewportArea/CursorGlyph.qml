pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Window

// Exact same pointer + tool artwork and hotspot as the native VTK cursor.
Image {
    id: glyph
    required property string iconName
    readonly property url sharedSource: iconName && iconName !== "default"
        ? Qt.resolvedUrl("../../../assets/cursors/" + iconName + ".svg") : ""
    source: sharedSource
    sourceSize.width: width * Screen.devicePixelRatio
    sourceSize.height: height * Screen.devicePixelRatio
    asynchronous: false
    smooth: true
}
