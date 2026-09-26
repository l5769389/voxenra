pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic as Basic
import QtQuick.Layouts
import "../../../components" as Components
import "../../../theme"
import "../components" as Controls

ColumnLayout {
    id: panel
    objectName: "mprVoiPanel"
    required property var controller
    required property string mode
    signal manualRequested(string chapter)
    readonly property var selected: controller?.selected ?? ({})
    readonly property bool hasSelection: !!selected.id
    spacing: 8

    Text {
        objectName: "voiPhaseScope"
        Layout.fillWidth: true
        visible: (panel.controller?.phaseIndex ?? -1) >= 0
        text: I18n.format(qsTrId("voi.phaseScope"), {phase: (panel.controller?.phaseIndex ?? -1) + 1})
        color: Theme.textMuted
        font.pixelSize: 11
        wrapMode: Text.Wrap
    }
    RowLayout {
        Layout.fillWidth: true
        Text {
            Layout.fillWidth: true
            text: panel.mode === "segmentation" ? qsTrId("seg.manage") : qsTrId("text.1151")
            color: Theme.textPrimary
            font.pixelSize: 14
            font.weight: Font.DemiBold
        }
        Controls.ToolActionButton {
            objectName: "voiManualButton"
            Layout.preferredWidth: 28
            Layout.preferredHeight: 28
            iconName: "manual"
            iconSize: 18
            label: qsTrId("text.0495")
            onClicked: panel.manualRequested(panel.mode)
        }
        Components.AppCheckBox {
            objectName: "voiEnabled"
            text: qsTrId("text.0755")
            checked: panel.controller?.enabled ?? false
            onClicked: panel.controller?.setEnabled(checked)
        }
    }
    Text {
        text: I18n.format(qsTrId("voi.count"), {count: panel.controller?.items.length ?? 0})
        color: Theme.textMuted
        font.pixelSize: 11
    }
    ListView {
        id: regionList
        objectName: "voiRegionList"
        Layout.fillWidth: true
        Layout.preferredHeight: Math.min(count, 4) * 34
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        model: panel.controller?.items ?? []
        Basic.ScrollBar.vertical: Components.AppScrollBar {}
        delegate: RowLayout {
            id: entry
            required property var modelData
            property bool editing: false
            width: regionList.width - 10
            height: 32
            spacing: 4
            Components.AppButton {
                objectName: "voiVisibility-" + entry.modelData.id
                compact: true
                minimumButtonWidth: 28
                text: entry.modelData.visible ? "◉" : "○"
                textColor: entry.modelData.color
                Accessible.name: qsTrId("text.1153")
                onClicked: panel.controller.toggleVisible(entry.modelData.id)
            }
            Item {
                Layout.fillWidth: true
                Layout.preferredHeight: 30
                Components.AppButton {
                    objectName: "voiSelect-" + entry.modelData.id
                    anchors.fill: parent
                    visible: !entry.editing
                    compact: true
                    checked: panel.controller.selectedId === entry.modelData.id
                    text: entry.modelData.name
                    textColor: entry.modelData.color
                    contentItem: Text {
                        text: entry.modelData.name
                        color: entry.modelData.color
                        elide: Text.ElideRight
                        font.pixelSize: 12
                        verticalAlignment: Text.AlignVCenter
                    }
                    onClicked: panel.controller.select(entry.modelData.id)
                    onDoubleClicked: {
                        entry.editing = true
                        nameInput.forceActiveFocus()
                        nameInput.selectAll()
                    }
                }
                Components.AppTextField {
                    id: nameInput
                    objectName: "voiName-" + entry.modelData.id
                    anchors.fill: parent
                    visible: entry.editing
                    compact: true
                    text: entry.modelData.name
                    onEditingFinished: {
                        if (!entry.editing) return
                        entry.editing = false
                        panel.controller.renameItem(entry.modelData.id, text)
                    }
                    Keys.onEscapePressed: {
                        entry.editing = false
                        text = entry.modelData.name
                    }
                }
            }
            Components.AppButton {
                objectName: "voiColor-" + entry.modelData.id
                compact: true
                minimumButtonWidth: 26
                text: "●"
                textColor: entry.modelData.color
                Accessible.name: qsTrId("seg.color")
                onClicked: {
                    const colors = Theme.segmentationSwatches
                    panel.controller.setColor(entry.modelData.id,
                        colors[(colors.indexOf(entry.modelData.color) + 1) % colors.length])
                }
            }
            Components.AppButton {
                objectName: "voiDelete-" + entry.modelData.id
                compact: true
                minimumButtonWidth: 28
                text: "×"
                Accessible.name: qsTrId("text.1154")
                onClicked: panel.controller.remove(entry.modelData.id)
            }
        }
    }
    Text {
        Layout.fillWidth: true
        visible: !panel.hasSelection
        text: panel.controller?.canDraw === false ? qsTrId("seg.empty")
            : panel.mode === "voi" ? qsTrId("text.1155") : qsTrId("text.1156")
        color: Theme.textMuted
        font.pixelSize: 12
        wrapMode: Text.Wrap
    }
    Rectangle {
        Layout.fillWidth: true
        implicitHeight: detail.implicitHeight + 20
        visible: panel.hasSelection
        color: Theme.selectionBackground
        border.color: panel.selected.color ?? Theme.borderDefault
        radius: 6
        ColumnLayout {
            id: detail
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 10
            spacing: 6
            RowLayout {
                Layout.fillWidth: true
                Text {
                    Layout.fillWidth: true
                    text: qsTrId("text.1157") + (panel.selected.unit ?? "")
                    color: Theme.textSecondary
                    font.pixelSize: 12
                }
                Text {
                    text: panel.controller?.busy ? qsTrId("text.1158") : ""
                    color: Theme.textMuted
                    font.pixelSize: 11
                }
            }
            GridLayout {
                columns: 2
                Layout.fillWidth: true
                columnSpacing: 6
                rowSpacing: 6
                Repeater {
                    model: panel.selected.metrics ?? []
                    delegate: Rectangle {
                        id: metric
                        required property var modelData
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        implicitHeight: 43
                        color: Theme.panelBackgroundStrong
                        radius: 4
                        Column {
                            anchors.fill: parent
                            anchors.margins: 6
                            spacing: 2
                            Text {
                                width: parent.width
                                text: metric.modelData.label
                                color: Theme.textMuted
                                font.pixelSize: 9
                                elide: Text.ElideRight
                            }
                            Text {
                                width: parent.width
                                text: metric.modelData.value
                                color: Theme.textPrimary
                                font.pixelSize: 13
                                elide: Text.ElideRight
                            }
                        }
                    }
                }
            }
            Text {
                Layout.fillWidth: true
                visible: panel.selected.kind === "segmentation" && !panel.selected.fixedMask
                text: I18n.format(qsTrId("voi.retained"), {rule: panel.selected.rule ?? "", fraction: panel.selected.fraction ?? "--"})
                color: Theme.textSecondary
                font.pixelSize: 11
                elide: Text.ElideRight
            }
            Components.AppComboBox {
                objectName: "voiUnit"
                Layout.fillWidth: true
                implicitHeight: 30
                visible: (panel.selected.unitOptions?.length ?? 0) > 1
                model: panel.selected.unitOptions ?? []
                textRole: "label"
                currentIndex: model.findIndex(o => o.id === panel.selected.unitId)
                onActivated: index => panel.controller.setUnit(model[index].id)
                Accessible.name: qsTrId("text.1160")
            }
            RowLayout {
                objectName: "voiThresholdModeRow"
                visible: panel.selected.kind === "segmentation" && !panel.selected.fixedMask
                Layout.fillWidth: true
                spacing: 4
                Text {
                    objectName: "voiThresholdLabel"
                    Layout.fillWidth: true
                    Layout.minimumWidth: implicitWidth
                    text: qsTrId("text.0941")
                    color: Theme.textSecondary
                    font.pixelSize: 12
                }
                Components.AppButton {
                    objectName: "voiThresholdAbsolute"
                    Layout.minimumWidth: implicitWidth
                    compact: true
                    text: qsTrId("text.1161")
                    checked: !panel.selected.percent
                    onClicked: panel.controller.setPercent(false)
                }
                Components.AppButton {
                    objectName: "voiThresholdPercent"
                    Layout.minimumWidth: implicitWidth
                    compact: true
                    text: "%"
                    checked: panel.selected.percent ?? false
                    onClicked: panel.controller.setPercent(true)
                }
            }
            Components.AppNumberField {
                    objectName: "voiThreshold"
                    Layout.fillWidth: true
                    visible: panel.selected.kind === "segmentation" && !panel.selected.fixedMask
                    compact: true
                    numberValue: panel.selected.threshold ?? 0
                    minimum: panel.selected.percent ? 0 : -1e12
                    maximum: panel.selected.percent ? 100 : 1e12
                    decimals: 3
                    onEdited: value => panel.controller.setThreshold(value)
            }
            Components.AppSlider {
                objectName: "voiThresholdSlider"
                Layout.fillWidth: true
                implicitHeight: 24
                visible: panel.selected.kind === "segmentation" && !panel.selected.fixedMask
                from: panel.selected.percent ? 0 : panel.selected.thresholdMin ?? 0
                to: panel.selected.percent ? 100 : panel.selected.thresholdMax ?? 1000
                value: panel.selected.threshold ?? 0
                onMoved: panel.controller.setThreshold(value)
            }
            RowLayout {
                visible: panel.selected.kind === "voi"
                Layout.fillWidth: true
                Text {
                    Layout.fillWidth: true
                    Layout.minimumWidth: implicitWidth
                    text: qsTrId("text.1162")
                    color: Theme.textSecondary
                    font.pixelSize: 12
                }
                Components.AppNumberField {
                    objectName: "voiDiameter"
                    Layout.fillWidth: true
                    Layout.preferredWidth: 96
                    compact: true
                    numberValue: panel.selected.diameter ?? 1
                    minimum: 0.1
                    maximum: panel.selected.depthMax ?? 1000
                    decimals: 2
                    onEdited: value => panel.controller.setDiameter(value)
                }
                Text { text: "mm"; color: Theme.textMuted; font.pixelSize: 11 }
            }
            Text {
                Layout.fillWidth: true
                visible: panel.selected.fixedMask ?? false
                text: qsTrId("seg.fixedMaskHelp")
                color: Theme.textMuted
                font.pixelSize: 11
                wrapMode: Text.Wrap
            }
            RowLayout {
                visible: !panel.selected.fixedMask
                objectName: "voiDepthModeRow"
                Layout.fillWidth: true
                Text {
                    Layout.fillWidth: true
                    Layout.minimumWidth: implicitWidth
                    text: qsTrId("text.1163")
                    color: Theme.textSecondary
                    font.pixelSize: 12
                }
                Components.AppButton {
                    objectName: "voiAutoDepth"
                    compact: true
                    text: panel.selected.depthAuto ? qsTrId("text.1164") : qsTrId("text.1165")
                    checked: panel.selected.depthAuto ?? true
                    onClicked: panel.controller.setAutoDepth(!panel.selected.depthAuto)
                }
            }
            RowLayout {
                visible: !panel.selected.fixedMask
                Layout.fillWidth: true
                Components.AppNumberField {
                    objectName: "voiDepth"
                    Layout.fillWidth: true
                    compact: true
                    numberValue: panel.selected.depth ?? 1
                    minimum: 0.1
                    maximum: panel.selected.depthMax ?? 1000
                    decimals: 2
                    onEdited: value => panel.controller.setDepth(value)
                }
                Text { text: "mm"; color: Theme.textMuted; font.pixelSize: 11 }
            }
            Components.AppSlider {
                objectName: "voiDepthSlider"
                visible: !panel.selected.fixedMask
                Layout.fillWidth: true
                implicitHeight: 24
                from: 0.1
                to: panel.selected.depthMax ?? 1000
                value: panel.selected.depth ?? 1
                onMoved: panel.controller.setDepth(value)
            }
        }
    }
    Text {
        Layout.fillWidth: true
        visible: (panel.controller?.error ?? "") !== ""
        text: panel.controller?.error ?? ""
        color: Theme.warningColor
        wrapMode: Text.Wrap
        font.pixelSize: 12
    }
}
