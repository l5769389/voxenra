pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Window
import QtQuick.Controls.Basic as Basic
import QtQuick.Layouts
import "../theme"

Rectangle {
    id: bar
    objectName: "applicationTitleBar"
    required property var targetWindow
    readonly property bool maximized: targetWindow.visibility === Window.Maximized
        || targetWindow.visibility === Window.FullScreen
    implicitHeight: 32
    color: Theme.appBackground

    function toggleMaximized() {
        if (maximized) targetWindow.showNormal()
        else targetWindow.showMaximized()
    }
    MouseArea {
        objectName: "titleBarDragArea"
        anchors.fill: parent
        onPressed: mouse => { if (mouse.button === Qt.LeftButton) bar.targetWindow.startSystemMove() }
        onDoubleClicked: bar.toggleMaximized()
    }
    Row {
        objectName: "applicationBrand"
        anchors.centerIn: parent
        spacing: 8
        Image {
            objectName: "applicationBrandMark"
            source: "../assets/brand/voxplane-mark.svg"
            sourceSize.width: Math.ceil(width * Math.max(1, Screen.devicePixelRatio))
            sourceSize.height: Math.ceil(height * Math.max(1, Screen.devicePixelRatio))
            smooth: true
            mipmap: true
            width: 20; height: 20
            fillMode: Image.PreserveAspectFit
        }
        Text {
            text: "VoxPlane"
            color: Theme.textPrimary
            font.pixelSize: 13
            font.weight: Font.DemiBold
            height: 20
            verticalAlignment: Text.AlignVCenter
        }
    }
    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.borderSubtle }
}
