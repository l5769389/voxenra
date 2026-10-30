pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic as Basic
import "../../../components" as Components
import "../../../theme"

Rectangle {
    id: root
    objectName: "mprReferenceViewport"
    required property var controller
    readonly property var volume: controller?.volumeViewport ?? null
    color: Theme.canvasBackground
    Components.DelayedActivity {
        id: feedback
        active: root.visible && root.volume?.loadState !== "ready" && root.volume?.loadState !== "error"
        activityKey: root.volume
    }
    TapHandler {
        onTapped: root.controller?.activate()
        onDoubleTapped: root.controller?.toggleMaximized()
    }

    Loader {
        // The corner title is rendered inside the native VTK viewport.
        anchors.fill: parent
        active: root.visible && root.volume?.loadState === "ready"
        sourceComponent: VolumeViewport {
            viewportController: root.volume
            activeViewport: root.controller?.active ?? false
        }
    }
    Column {
        anchors.centerIn: parent
        width: Math.max(0, parent.width - 32)
        spacing: 10
        visible: root.volume?.loadState === "error" || feedback.showing
        Basic.BusyIndicator {
            anchors.horizontalCenter: parent.horizontalCenter
            running: root.visible && root.volume?.loadState !== "error"
            visible: running
        }
        Text {
            width: parent.width
            text: root.volume?.loadState === "error" ? root.volume.errorMessage : qsTrId("mpr.reference.loading")
            color: Theme.textSecondary
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap
            font.pixelSize: 12
        }
        Components.AppButton {
            anchors.horizontalCenter: parent.horizontalCenter
            visible: root.volume?.loadState === "error"
            text: qsTrId("text.0897")
            onClicked: root.volume.closeTab()
        }
    }
}
