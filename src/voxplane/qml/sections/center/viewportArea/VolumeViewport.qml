pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../../../components" as Components
import "../../../theme"

Item {
    id: root
    objectName: "volumeViewport"
    required property var viewportController
    property bool activeViewport: true
    property var attachedController: null
    property bool presentationReported: false
    signal presentationReady(bool success)

    function attach() {
        const next = viewportController && viewportController.viewportType === "volume"
            && viewportController.loadState === "ready" ? viewportController : null
        if (next !== attachedController) {
            presentationReported = false
            mountCheck.attempts = 0
            if (attachedController)
                attachedController.releaseNativeView(root)
            // Detach the old QWindow while its Python owner is still alive.
            attachedController = null
            if (next) {
                next.acquireNativeView(root)
                attachedController = next
            }
        }
        visibilityCheck.restart()
    }

    function syncVisibility() {
        if (attachedController) {
            attachedController.setOwnedNativeVisible(root, root.visible)
        }
    }

    // Owned timers are cancelled when the Loader destroys this page. A queued
    // Qt.callLater(attach) can otherwise outlive its QML execution context.
    Timer {
        id: attachCheck
        interval: 0
        onTriggered: root.attach()
    }

    Timer {
        id: visibilityCheck
        interval: 0
        onTriggered: root.syncVisibility()
    }

    Timer {
        id: mountCheck
        property int attempts: 0
        interval: 100
        repeat: true
        running: root.visible && !!root.attachedController && !root.presentationReported
        onTriggered: {
            // WindowContainer reparents during scene polish, after Loader.Ready.
            root.syncVisibility()
            const attached = root.attachedController.nativeViewAttached(root)
            if (attached || ++attempts >= 150) {
                root.presentationReported = true
                if (!attached)
                    root.attachedController.nativePresentationFailed(root)
                root.presentationReady(attached)
            }
        }
    }

    Connections {
        target: root.viewportController
        ignoreUnknownSignals: true
        function onLoadStateChanged() { attachCheck.restart() }
    }
    onViewportControllerChanged: attachCheck.restart()
    onVisibleChanged: syncVisibility()
    Component.onCompleted: attachCheck.restart()
    Component.onDestruction: {
        attachCheck.stop()
        visibilityCheck.stop()
        if (attachedController)
            attachedController.releaseNativeView(root)
        attachedController = null
    }

    RowLayout {
        id: fusionHeader
        visible: root.viewportController?.isFusionVolume === true
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        height: visible ? 38 : 0
        spacing: 6
        Text {
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            text: fusionHeader.visible ? root.viewportController.sceneLabel : ""
            color: Theme.textPrimary; font.pixelSize: 12; elide: Text.ElideRight
        }
        Repeater {
            model: fusionHeader.visible ? [{label:"CT 3D",value:"ct"},{label:"PET 3D",value:"pet"},{label:qsTrId("text.1001"),value:"fusion"}] : []
            delegate: Components.AppButton {
                required property var modelData
                objectName: "volumeMode-" + modelData.value
                text: modelData.label
                compact: true; checkable: true
                checked: root.viewportController?.volumeMode === modelData.value
                onClicked: root.viewportController?.setVolumeMode(modelData.value)
            }
        }
    }

    WindowContainer {
        objectName: "volumeWindowContainer"
        anchors.fill: parent
        anchors.margins: selectionFrame.contentInset
        anchors.topMargin: (fusionHeader.visible ? fusionHeader.height : 0) + selectionFrame.contentInset
        window: root.attachedController ? root.attachedController.nativeWindow : null
    }

    ViewportFrame {
        id: selectionFrame
        objectName: "volumeViewportFrame"
        anchors.fill: parent
        anchors.topMargin: fusionHeader.visible ? fusionHeader.height : 0
        active: root.activeViewport
        // Draw outside the native child window; QML cannot cover its contents.
        z: 30
    }
}
