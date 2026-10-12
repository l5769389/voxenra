pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic as Basic
import QtQuick.Layouts
import "../../../components" as Components
import "../../../theme"

Components.AppDialog {
    id: dialog
    objectName: "automaticSegmentationDialog"
    property var controller: null
    property var settingsController: null
    parent: Basic.Overlay.overlay
    width: Math.min(620, (parent?.width ?? 660) - 32)
    height: Math.min(720, (parent?.height ?? 760) - 32)
    x: ((parent?.width ?? width) - width) / 2
    y: ((parent?.height ?? height) - height) / 2
    title: qsTrId("autoSeg.title")
    titleIcon: "auto-segmentation"
    subtitle: (controller?.targetTitle ?? "") + " · " + qsTrId("autoSeg.fast")
    onOpened: { if (controller && controller.hasTarget && !controller.ready && !controller.busy) controller.checkEnvironment() }
    contentItem: ColumnLayout {
        spacing: 10
        RowLayout {
            Layout.fillWidth: true
            Components.AppTextField {
                id: search
                objectName: "automaticSegmentationSearch"
                Layout.fillWidth: true
                placeholderText: qsTrId("autoSeg.search")
                enabled: !(dialog.controller?.busy ?? false)
            }
            Components.AppButton {
                text: qsTrId("autoSeg.all")
                compact: true
                enabled: !(dialog.controller?.busy ?? false)
                onClicked: dialog.controller?.selectAll(true)
            }
            Components.AppButton {
                text: qsTrId("autoSeg.none")
                compact: true
                enabled: !(dialog.controller?.busy ?? false)
                onClicked: dialog.controller?.selectAll(false)
            }
        }
        ListView {
            id: organs
            objectName: "automaticSegmentationOrgans"
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 100
            clip: true
            model: (dialog.controller?.organs ?? []).filter(o => (o.name + " " + o.id).toLowerCase().includes(search.text.toLowerCase()))
            Basic.ScrollBar.vertical: Basic.ScrollBar { }
            delegate: Components.AppCheckBox {
                required property var modelData
                width: organs.width - 14
                text: modelData.name
                checked: modelData.selected
                enabled: !(dialog.controller?.busy ?? false)
                onClicked: dialog.controller.selectOrgan(modelData.id, checked)
            }
        }
        Basic.ProgressBar {
            Layout.fillWidth: true
            visible: dialog.controller?.busy ?? false
            indeterminate: true
        }
        Text {
            Layout.fillWidth: true
            text: dialog.controller?.message ?? ""
            textFormat: Text.PlainText
            color: dialog.controller?.state === "error" ? Theme.dangerColor : Theme.textSecondary
            wrapMode: Text.Wrap
            font.pixelSize: 12
        }
        Components.AppButton {
            objectName: "automaticSegmentationDetails"
            visible: (dialog.controller?.logs ?? "").length > 0
            text: qsTrId("autoSeg.details")
            compact: true
            onClicked: details.open()
        }
        RowLayout {
            Layout.fillWidth: true
            Components.AppButton {
                text: qsTrId("autoSeg.detect")
                enabled: !(dialog.controller?.busy ?? false)
                onClicked: dialog.controller?.checkEnvironment()
            }
            Item { Layout.fillWidth: true }
            Components.AppButton {
                objectName: "automaticSegmentationStart"
                text: dialog.controller?.busy ? qsTrId("autoSeg.cancel") : qsTrId("autoSeg.start")
                enabled: !!dialog.controller && (dialog.controller.busy || (dialog.controller.ready && dialog.controller.hasTarget))
                onClicked: { if (dialog.controller.busy) dialog.controller.cancel(); else dialog.controller.start() }
            }
        }
    }
    Components.AppDialog {
        id: details
        parent: Basic.Overlay.overlay
        width: Math.min(680, (parent?.width ?? 720) - 32)
        height: Math.min(500, (parent?.height ?? 540) - 32)
        x: ((parent?.width ?? width) - width)/2
        y: ((parent?.height ?? height) - height)/2
        title: qsTrId("autoSeg.log")
        contentItem: Basic.ScrollView {
            clip: true
            Basic.TextArea {
                text: dialog.controller?.logs ?? ""
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
