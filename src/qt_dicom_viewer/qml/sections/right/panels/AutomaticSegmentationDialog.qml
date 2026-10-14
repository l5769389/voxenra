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
    readonly property var filteredOrgans: (controller?.organs ?? []).filter(
        o => (o.name + " " + o.id).toLowerCase().includes(search.text.toLowerCase()))
    onFilteredOrgansChanged: syncOrgans()
    Component.onCompleted: syncOrgans()
    function syncOrgans() {
        // Selection/status notifications must update existing delegates so a
        // click or Space does not discard the scroll position or active focus.
        const rows = filteredOrgans
        let sameOrder = organModel.count === rows.length
        for (let i = 0; sameOrder && i < rows.length; ++i)
            sameOrder = organModel.get(i).organId === rows[i].id
        if (!sameOrder) {
            organModel.clear()
            for (const row of rows)
                organModel.append({organId: row.id, label: row.name, isSelected: row.selected})
        } else {
            for (let i = 0; i < rows.length; ++i) {
                organModel.setProperty(i, "label", rows[i].name)
                organModel.setProperty(i, "isSelected", rows[i].selected)
            }
        }
    }
    ListModel { id: organModel }
    onOpened: { if (controller && controller.hasTarget && !controller.ready && !controller.busy) controller.checkEnvironment() }
    onClosed: details.close()
    Connections {
        target: dialog.controller
        function onChanged() {
            // "done" means validated masks have been imported into the target.
            if (dialog.visible && dialog.controller.state === "done")
                dialog.accept()
        }
    }
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
            model: organModel
            Basic.ScrollBar.vertical: Basic.ScrollBar { }
            delegate: Components.AppCheckBox {
                required property string organId
                required property string label
                required property bool isSelected
                width: organs.width - 14
                text: label
                checked: isSelected
                enabled: !(dialog.controller?.busy ?? false)
                onClicked: dialog.controller.selectOrgan(organId, checked)
            }
        }
        Basic.ProgressBar {
            Layout.fillWidth: true
            visible: dialog.controller?.busy ?? false
            indeterminate: true
        }
        Text {
            objectName: "automaticSegmentationMessage"
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
        objectName: "automaticSegmentationLogDialog"
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
