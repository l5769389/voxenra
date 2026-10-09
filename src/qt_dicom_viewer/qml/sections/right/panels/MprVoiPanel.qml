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
    property var historyController: null
    signal manualRequested(string chapter)
    readonly property var selected: controller?.selected ?? ({})
    readonly property bool hasSelection: !!selected.id
    readonly property bool relativeBrush: controller?.brushRelative ?? false
    readonly property bool brushTool: ["paint", "erase"].includes(controller?.editMode)
    readonly property bool erasing: controller?.editMode === "erase"
    readonly property string diameterLabel: erasing
        ? (relativeBrush ? qsTrId("seg.eraserDiameterPercent") : qsTrId("seg.eraserDiameter"))
        : (relativeBrush ? qsTrId("seg.brushDiameterPercent") : qsTrId("seg.brushDiameter"))
    readonly property string diameterHelp: relativeBrush ? qsTrId("seg.brushRelativeHelp") : qsTrId("seg.brushRangeHelp")
    readonly property real diameterValue: relativeBrush ? (controller?.brushPercent ?? 3) : (controller?.brushDiameter ?? 5)
    function setDiameter(value) {
        if (!controller) return
        if (relativeBrush) controller.setBrushPercent(value)
        else controller.setBrushDiameter(value)
    }
    spacing: 8

    component EditorCombo: Components.AppComboBox {
        id: combo
        leftPadding: 8
        rightPadding: 24
        readonly property real singleLineWidth: Math.ceil(captionMetrics.advanceWidth) + leftPadding + rightPadding + 2
        TextMetrics { id: captionMetrics; font: combo.font; text: combo.displayText }
        implicitHeight: Math.max(Theme.controlHeight, caption.implicitHeight + 12)
        contentItem: Text {
            id: caption
            text: combo.displayText
            color: combo.enabled ? Theme.textPrimary : Theme.textDisabled
            verticalAlignment: Text.AlignVCenter
            wrapMode: Text.WordWrap
            font: combo.font
        }
    }

    GridLayout {
        visible: panel.mode === "segmentation"
        Layout.fillWidth: true
        columns: 2
        GridLayout {
            id: selectors
            Layout.fillWidth: true
            Layout.columnSpan: 2
            // Keep short labels together; wrap only when the translated captions need it.
            columns: !scope.visible || width >= editMode.singleLineWidth + scope.singleLineWidth + 28 + columnSpacing * 2 ? 3 : 2
            columnSpacing: 6
            rowSpacing: 6
            EditorCombo {
                id: editMode
                objectName: "segmentationEditMode"
                Layout.columnSpan: selectors.columns === 2 && scope.visible ? 2 : 1
                minimumPopupWidth: 220
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                Layout.preferredWidth: singleLineWidth
                readonly property var keys: panel.controller?.canDraw === false ? ["paint", "erase", "keep", "remove"] : ["threshold", "paint", "erase", "keep", "remove"]
                model: panel.controller?.canDraw === false
                    ? [qsTrId("seg.paint"), qsTrId("seg.erase"), qsTrId("seg.keepIsland"), qsTrId("seg.removeIsland")]
                    : [qsTrId("seg.thresholdTool"), qsTrId("seg.paint"), qsTrId("seg.erase"), qsTrId("seg.keepIsland"), qsTrId("seg.removeIsland")]
                currentIndex: keys.indexOf(panel.controller?.editMode ?? "threshold")
                onModelChanged: Qt.callLater(function() {
                    currentIndex = Qt.binding(() => keys.indexOf(panel.controller?.editMode ?? "threshold"))
                })
                onActivated: index => panel.controller.setEditMode(keys[index])
            }
            EditorCombo {
                id: scope
                objectName: "segmentationBrushScope"
                minimumPopupWidth: 160
                visible: panel.brushTool
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                Layout.preferredWidth: singleLineWidth
                model: [qsTrId("seg.sliceBrush"), qsTrId("seg.sphereBrush")]
                currentIndex: panel.controller?.brushSphere ? 1 : 0
                onModelChanged: Qt.callLater(function() {
                    currentIndex = Qt.binding(() => panel.controller?.brushSphere ? 1 : 0)
                })
                onActivated: index => panel.controller.setBrushSphere(index === 1)
            }
            Controls.ToolActionButton {
                objectName: "segmentationManualButton"
                Layout.preferredWidth: 28
                Layout.preferredHeight: 28
                minimumButtonWidth: 28
                iconName: "manual"
                iconSize: 18
                label: qsTrId("text.0495")
                onClicked: panel.manualRequested(panel.mode)
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Layout.columnSpan: 2
            visible: panel.brushTool
            Text {
                objectName: "segmentationBrushDiameterLabel"
                Layout.fillWidth: true
                text: panel.diameterLabel
                wrapMode: Text.WordWrap
                Layout.minimumWidth: 0
                color: Theme.textSecondary
                font.pixelSize: 12
            }
            EditorCombo {
                objectName: "segmentationBrushUnits"
                Layout.minimumWidth: singleLineWidth
                Layout.preferredWidth: singleLineWidth
                Layout.maximumWidth: singleLineWidth
                minimumPopupWidth: 160
                model: [qsTrId("seg.brushMillimeters"), qsTrId("seg.brushRelative")]
                currentIndex: panel.relativeBrush ? 1 : 0
                onModelChanged: Qt.callLater(function() {
                    currentIndex = Qt.binding(() => panel.relativeBrush ? 1 : 0)
                })
                onActivated: index => panel.controller.setBrushRelative(index === 1)
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Layout.columnSpan: 2
            spacing: 6
            visible: panel.brushTool
            Components.AppSlider {
                objectName: "segmentationBrushSlider"
                Layout.fillWidth: true
                from: 1
                to: panel.relativeBrush ? 25 : 50
                stepSize: panel.relativeBrush ? 1 : 0.5
                value: Math.max(from, Math.min(to, panel.diameterValue))
                Accessible.name: panel.diameterLabel
                Accessible.description: panel.diameterHelp
                // Publish user movement only: clamping the slider must never
                // overwrite a precise value entered outside its common range.
                onMoved: panel.setDiameter(value)
                Components.AppToolTip {
                    visible: parent.hovered
                    text: panel.diameterHelp
                }
            }
            Components.AppNumberField {
                objectName: "segmentationBrushDiameter"
                Layout.minimumWidth: 60
                Layout.maximumWidth: 60
                Layout.preferredWidth: 60
                compact: true
                numberValue: panel.diameterValue
                minimum: panel.relativeBrush ? 1 : 0.1
                maximum: panel.relativeBrush ? 25 : 100
                decimals: 1
                Accessible.name: panel.diameterLabel
                onEdited: value => panel.setDiameter(value)
            }
        }
    }

    SegmentationDisplaySettings {
        visible: panel.mode === "segmentation"
        Layout.fillWidth: true
        controller: panel.controller
    }

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
            Layout.minimumWidth: 0
            wrapMode: Text.WordWrap
            color: Theme.textPrimary
            font.pixelSize: 14
            font.weight: Font.DemiBold
        }
        Controls.ToolActionButton {
            objectName: "voiManualButton"
            visible: panel.mode !== "segmentation"
            Layout.preferredWidth: 28
            Layout.preferredHeight: 28
            iconName: "manual"
            iconSize: 18
            label: qsTrId("text.0495")
            onClicked: panel.manualRequested(panel.mode)
        }
        Controls.ToolActionButton {
            objectName: "newPaintSegment"
            visible: panel.mode === "segmentation"
            Layout.preferredWidth: 28
            Layout.preferredHeight: 28
            minimumButtonWidth: 28
            iconName: "add"
            iconSize: 18
            label: qsTrId("seg.new")
            Accessible.name: qsTrId("seg.new")
            tooltipText: qsTrId("seg.new")
            onClicked: panel.controller.newSegment()
        }
        Components.AppCheckBox {
            objectName: "voiEnabled"
            text: qsTrId("text.0755")
            checked: panel.controller?.enabled ?? false
            onClicked: panel.controller?.setEnabled(checked)
        }
    }
    RowLayout {
        Layout.fillWidth: true
        Text {
            Layout.fillWidth: true
            text: I18n.format(qsTrId("voi.count"), {count: panel.controller?.items.length ?? 0})
            color: Theme.textMuted
            font.pixelSize: 12
        }
        Controls.ToolActionButton {
            objectName: "segmentationUndo"
            visible: panel.mode === "segmentation"
            Layout.preferredWidth: 28
            Layout.preferredHeight: 28
            minimumButtonWidth: 28
            iconName: "undo"
            iconSize: 18
            label: qsTrId("seg.undo")
            Accessible.name: qsTrId("seg.undo")
            tooltipText: qsTrId("seg.undo") + " (" + (panel.historyController?.undoShortcutText ?? "Ctrl+Z") + ")"
            enabled: panel.historyController?.canUndo ?? false
            onClicked: panel.historyController.undo()
        }
        Controls.ToolActionButton {
            objectName: "segmentationRedo"
            visible: panel.mode === "segmentation"
            Layout.preferredWidth: 28
            Layout.preferredHeight: 28
            minimumButtonWidth: 28
            iconName: "redo"
            iconSize: 18
            label: qsTrId("seg.redo")
            Accessible.name: qsTrId("seg.redo")
            tooltipText: qsTrId("seg.redo") + " (" + (panel.historyController?.redoShortcutText ?? "Ctrl+Shift+Z") + ")"
            enabled: panel.historyController?.canRedo ?? false
            onClicked: panel.historyController.redo()
        }
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
                iconName: entry.modelData.visible ? "visible" : "hidden"
                iconSize: 16
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
                iconName: "delete"
                iconSize: 16
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
                    minimum: panel.relativeBrush ? 1 : 0.1
                    maximum: panel.selected.depthMax ?? 1000
                    decimals: 2
                    onEdited: value => panel.controller.setDiameter(value)
                }
                Text { text: "mm"; color: Theme.textMuted; font.pixelSize: 11 }
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
                    minimum: panel.relativeBrush ? 1 : 0.1
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
