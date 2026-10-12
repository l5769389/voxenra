pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic as Basic
import QtQuick.Layouts
import "../../components" as Components
import "../../theme"

SettingsSection {
    id: root
    property var controller: typeof appController !== "undefined" ? (appController.localSegmentationController ?? null) : null
    sectionKey: "services-segmentation"
    title: qsTrId("autoSeg.settings")
    description: ""
    property bool advanced: false
    Text {
        objectName: "autoSegEnvironmentStatus"
        Layout.fillWidth: true
        text: root.controller?.environmentMessage ?? qsTrId("autoSeg.idle")
        textFormat: Text.PlainText
        color: root.controller?.environmentState === "error" ? Theme.dangerColor : Theme.textPrimary
        wrapMode: Text.Wrap
        font.pixelSize: 13
    }
    Text {
        Layout.fillWidth: true
        visible: !!root.controller?.environment.version
        text: "TotalSegmentator " + (root.controller?.environment.version ?? "")
            + " · " + qsTrId(root.controller?.ready ? "autoSeg.modelReady" : "autoSeg.missingModel")
        color: Theme.textSecondary
        wrapMode: Text.Wrap
        font.pixelSize: 12
    }
    Text {
        Layout.fillWidth: true
        visible: text.length > 0
        text: root.controller?.compatibilityMessage ?? ""
        color: Theme.textMuted
        wrapMode: Text.Wrap
        font.pixelSize: 12
    }
    RowLayout {
        Layout.fillWidth: true
        Text { text: qsTrId("autoSeg.device"); color: Theme.textSecondary; font.pixelSize: 12 }
        Components.AppComboBox {
            objectName: "autoSegDevice"
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            Accessible.name: qsTrId("autoSeg.device")
            readonly property var keys: root.controller?.devices ?? ["auto"]
            readonly property var available: root.controller?.environment.devices ?? []
            readonly property string selectedDevice: root.settingsController.values.services.segmentationDevice
            function syncSelection() { currentIndex = keys.indexOf(selectedDevice) }
            function deviceName(key) { return key === "gpu" ? "CUDA" : key.toUpperCase() }
            model: keys.map(k => k === "auto"
                ? qsTrId("autoSeg.auto") + (available.length ? " (" + deviceName(available[0]) + ")" : "")
                : deviceName(k) + (available.includes(k) ? "" : " · " + qsTrId(root.controller?.environment.version ? "autoSeg.unavailable" : "autoSeg.unchecked")))
            // ComboBox resets its index when a probe replaces the model. Reapply
            // the saved choice after that reset, without writing a new setting.
            onModelChanged: Qt.callLater(syncSelection)
            onSelectedDeviceChanged: syncSelection()
            Component.onCompleted: syncSelection()
            enabled: !!root.controller && !root.controller.busy
            onActivated: index => root.settingsController.setValue("services", "segmentationDevice", keys[index])
        }
    }
    RowLayout {
        Layout.fillWidth: true
        Components.AppButton {
            objectName: "autoSegDetect"
            Layout.fillWidth: true
            text: qsTrId("autoSeg.detect")
            enabled: !!root.controller && !root.controller.busy
            onClicked: root.controller.checkEnvironment()
            Components.AppToolTip { visible: parent.hovered; text: qsTrId("autoSeg.detectHelp") }
        }
        Components.AppButton {
            objectName: "autoSegAdvanced"
            Layout.fillWidth: true
            text: qsTrId("autoSeg.advanced")
            onClicked: root.advanced = !root.advanced
        }
        Components.AppButton {
            iconName: "manual"
            compact: true
            Accessible.name: qsTrId("autoSeg.help")
            onClicked: appController.workspaceController.openManual("segmentation")
            Components.AppToolTip { visible: parent.hovered; text: qsTrId("autoSeg.help") }
        }
    }
    ColumnLayout {
        visible: root.advanced
        Layout.fillWidth: true
        Components.AppButton {
            objectName: "autoSegChoosePython"
            Layout.fillWidth: true
            text: qsTrId("autoSeg.python")
            enabled: !!root.controller && !root.controller.busy
            onClicked: root.controller.choosePython()
            Components.AppToolTip {
                visible: parent.hovered
                text: qsTrId("autoSeg.pythonHint") + (root.controller?.pythonPath ? "\n" + root.controller.pythonPath : "")
            }
        }
        Components.AppButton {
            objectName: "autoSegChooseWeights"
            Layout.fillWidth: true
            text: qsTrId("autoSeg.weights")
            enabled: !!root.controller && !root.controller.busy
            onClicked: root.controller.chooseWeights()
            Components.AppToolTip { visible: parent.hovered; text: qsTrId("autoSeg.weightsHint") + "\n" + (root.controller?.weightsPath ?? "") }
        }
        Components.AppButton {
            Layout.fillWidth: true
            text: qsTrId("autoSeg.resetEnvironment")
            enabled: !!root.controller && !root.controller.busy
            onClicked: root.controller.resetEnvironment()
        }
    }
    Components.AppButton {
        visible: (root.controller?.logs ?? "").length > 0
        text: qsTrId("autoSeg.details")
        compact: true
        onClicked: diagnostics.open()
    }
    Components.AppDialog {
        id: diagnostics
        parent: Basic.Overlay.overlay
        width: Math.min(680, (parent?.width ?? 720) - 32)
        height: Math.min(500, (parent?.height ?? 540) - 32)
        x: ((parent?.width ?? width) - width)/2
        y: ((parent?.height ?? height) - height)/2
        title: qsTrId("autoSeg.log")
        contentItem: Basic.ScrollView {
            clip: true
            Basic.TextArea {
                text: root.controller?.logs ?? ""
                readOnly: true
                selectByMouse: true
                wrapMode: TextEdit.Wrap
                textFormat: TextEdit.PlainText
                color: Theme.textPrimary
                font.pixelSize: 11
            }
        }
    }
}
