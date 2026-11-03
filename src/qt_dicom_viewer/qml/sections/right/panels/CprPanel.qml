pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../../../components/ShortcutCaption.js" as KeysText
import "../../../components" as Components
import "../../../theme"

ColumnLayout {
    id: panel
    objectName: "cprPanel"
    required property var controller
    readonly property var shortcuts: typeof appController !== "undefined" ? appController.shortcutController?.bindings ?? [] : []

    property bool advanced: controller?.panelSections.includes("cpr-advanced") ?? false
    property bool details: controller?.panelSections.includes("cpr-details") ?? false
    property bool interval: controller?.panelSections.includes("cpr-interval") ?? false
    readonly property bool drawing: controller?.drawing ?? false
    readonly property bool editing: !drawing && ((controller?.pathEditing ?? false) || (controller?.finishing ?? false))
    readonly property bool hasPath: (controller?.selectedPathId ?? "") !== ""
    readonly property int pointCount: controller?.pointCount ?? 0
    readonly property bool results: controller?.resultView ?? false
    readonly property bool historical: controller?.activeViewport?.historicalPlane ?? false
    spacing: 8

    Components.PanelHeading { title: qsTrId("cpr.title"); explanation: panel.controller?.message ?? "" }
    Text {
        objectName: "cprErrorMessage"
        Layout.fillWidth: true
        visible: panel.controller?.hasError ?? false
        text: panel.controller?.message ?? ""
        color: Theme.warningColor
        wrapMode: Text.Wrap
        font.pixelSize: Theme.bodyFontSize
    }
    Text {
        objectName: "cprHistoricalSource"
        Layout.fillWidth: true
        visible: panel.historical
        text: panel.controller?.activeViewport?.historicalDescription ?? ""
        textFormat: Text.PlainText
        Accessible.name: text
        color: Theme.textPrimary
        wrapMode: Text.Wrap
        font.pixelSize: 12
    }
    Components.AppButton {
        objectName: "cprReturnCurrent"
        Layout.fillWidth: true
        visible: panel.historical
        enabled: !panel.editing && !panel.drawing
        text: qsTrId("cpr.returnCurrent")
        compact: true
        onClicked: panel.controller.returnToCurrentResult()
    }
    Components.AppComboBox {
        objectName: "cprPathSelector"
        Layout.fillWidth: true
        visible: !panel.drawing && panel.hasPath
        model: panel.controller?.paths ?? []
        textRole: "name"
        Accessible.name: qsTrId("cpr.selectedPath")
        Accessible.description: currentText
        currentIndex: model.findIndex(item => item.pathId === panel.controller?.selectedPathId)
        onActivated: panel.controller.selectPath(model[currentIndex].pathId)
    }
    RowLayout {
        Layout.fillWidth: true
        visible: panel.hasPath && !panel.results && !panel.drawing && !panel.editing
        enabled: !!panel.controller?.referencesReady && !panel.controller?.sourceMismatch
        Components.AppButton {
            objectName: "cprAdditionalPath"
            Layout.fillWidth: true
            shortcutTitle: qsTrId("cpr.new")
            captionKey: KeysText.hint("cpr-new", panel.shortcuts)
            onClicked: panel.controller.startPath()
        }
        Components.AppButton {
            objectName: "cprEditPath"
            Layout.fillWidth: true
            shortcutTitle: qsTrId("cpr.edit")
            captionKey: KeysText.hint("cpr-edit", panel.shortcuts)
            onClicked: panel.controller.setPathEditing(true)
        }
    }
    Text {
        objectName: "cprPathStatus"
        visible: !panel.results
        Accessible.role: Accessible.StaticText
        Accessible.name: text
        Layout.fillWidth: true
        text: panel.drawing ? qsTrId("cpr.draftCount").arg(panel.pointCount)
            : panel.hasPath && !panel.editing ? qsTrId("cpr.referenceBrowse")
            : qsTrId("cpr.pathSummary").arg(panel.pointCount)
        color: panel.drawing ? Theme.textPrimary : Theme.textSecondary
        wrapMode: Text.Wrap
        font.pixelSize: 12
    }
    Text {
        objectName: "cprInteractionHint"
        Accessible.role: Accessible.StaticText
        Accessible.name: text
        Layout.fillWidth: true
        visible: panel.drawing || panel.editing || !panel.hasPath
        text: qsTrId(panel.drawing ? "cpr.drawHint" : panel.editing ? "cpr.editHint" : "cpr.startHint")
        color: Theme.textSecondary
        wrapMode: Text.Wrap
        font.pixelSize: 12
    }
    Components.AppButton {
        objectName: "cprDeletePoint"
        Layout.fillWidth: true
        visible: panel.drawing || panel.editing
        compact: true
        shortcutTitle: qsTrId(panel.drawing ? "cpr.undoPoint" : "cpr.deletePoint")
        captionKey: panel.drawing ? "Backspace" : "Delete"
        iconName: panel.drawing ? "undo" : "delete"
        enabled: panel.controller?.canDeletePoint ?? false
        onClicked: panel.controller.deleteSelectedPoint()
    }
    Components.AppButton {
        objectName: "cprDetails"
        Layout.fillWidth: true
        visible: !panel.results && (panel.hasPath || panel.drawing)
        compact: true
        text: qsTrId("cpr.pathDetails")
        iconName: panel.details ? "chevron-up" : "chevron-down"
        checkable: true
        checked: panel.details
        onClicked: panel.controller.togglePanelSection("cpr-details")
    }
    ColumnLayout {
        Layout.fillWidth: true
        visible: !panel.results && panel.details && (panel.hasPath || panel.drawing)
        spacing: 6
        Components.AppTextField {
            id: nameField
            objectName: "cprPathName"
            Layout.fillWidth: true
            visible: !panel.drawing
            placeholderText: qsTrId("cpr.rename")
            Accessible.name: qsTrId("cpr.rename")
            maximumLength: 256
            readonly property string modelText: panel.controller?.paths.find(item => item.selected)?.name ?? ""
            function sync() { if (!activeFocus) text = modelText }
            Component.onCompleted: sync()
            onModelTextChanged: sync()
            onEditingFinished: {
                panel.controller?.renamePath(text)
                text = modelText
            }
        }
        Text {
            text: qsTrId("cpr.coordinates")
            color: Theme.textSecondary
            font.pixelSize: 11
        }
        ListView {
            id: pointList
            objectName: "cprPointList"
            Layout.fillWidth: true
            Layout.preferredHeight: Math.min(120, count * 30)
            clip: true
            model: panel.details && !panel.results ? panel.controller?.controlPoints ?? [] : []
            delegate: Components.AppButton {
                required property var modelData
                width: pointList.width
                height: 30
                compact: true
                checked: modelData.selected
                text: qsTrId("cpr.point").arg(modelData.index + 1) + " · "
                    + modelData.x.toFixed(1) + ", " + modelData.y.toFixed(1) + ", " + modelData.z.toFixed(1)
                onClicked: panel.controller.locatePoint(modelData.index)
            }
        }
        Components.AppButton {
            objectName: "cprDeletePath"
            Layout.fillWidth: true
            visible: !panel.drawing
            text: qsTrId("cpr.deletePath")
            iconName: "delete"
            actionRole: "danger"
            compact: true
            onClicked: panel.controller.deletePath()
        }
    }
    ColumnLayout {
        Layout.fillWidth: true
        visible: panel.hasPath && !panel.drawing
        spacing: 6
        Components.PanelHeading {
            title: qsTrId("cpr.navigate")
            explanation: qsTrId("cpr.navigationHelp")
        }
        RowLayout {
            Layout.fillWidth: true
            Components.AppNumberField {
                objectName: "cprPositionInput"
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                numberValue: panel.controller?.positionMm ?? 0
                minimum: 0
                maximum: panel.controller?.totalLength ?? 0
                decimals: 6
                editContext: panel.controller?.selectedPathId ?? ""
                Accessible.name: qsTrId("cpr.positionInput")
                Accessible.description: qsTrId("cpr.positionSamplingHint").arg((panel.controller?.totalLength ?? 0).toFixed(3))
                onEdited: value => panel.controller.setPositionMm(value)
            }
            Text { text: "mm"; color: Theme.textSecondary; font.pixelSize: 12 }
        }
        RowLayout {
            Layout.fillWidth: true
            Components.AppButton {
                objectName: "cprPreviousSample"
                Layout.fillWidth: true
                compact: true
                shortcutTitle: qsTrId("cpr.previousSample")
                captionKey: KeysText.hint("cpr-prev", panel.shortcuts)
                enabled: (panel.controller?.positionMm ?? 0) > 0
                onClicked: panel.controller.stepPosition(-1)
            }
            Components.AppButton {
                objectName: "cprNextSample"
                Layout.fillWidth: true
                compact: true
                shortcutTitle: qsTrId("cpr.nextSample")
                captionKey: KeysText.hint("cpr-next", panel.shortcuts)
                enabled: (panel.controller?.positionMm ?? 0) < (panel.controller?.totalLength ?? 0)
                onClicked: panel.controller.stepPosition(1)
            }
        }
        Text {
            Layout.fillWidth: true
            text: "0–" + (panel.controller?.totalLength ?? 0).toFixed(3) + " mm"
            color: Theme.textSecondary
            wrapMode: Text.Wrap
            font.pixelSize: 11
        }
        Components.AppSlider {
            objectName: "cprPosition"
            Layout.fillWidth: true
            from: 0
            to: Math.max(.01, panel.controller?.totalLength ?? 0)
            value: panel.controller?.positionMm ?? 0
            enabled: (panel.controller?.totalLength ?? 0) > 0
            Accessible.name: qsTrId("cpr.position")
            onMoved: panel.controller.setPositionMm(value)
        }
        Components.PanelHeading {
            objectName: "cprCurrentParameters"
            title: qsTrId("cpr.currentParameters")
            explanation: qsTrId("cpr.projectionHelp")
        }
        Components.AppComboBox {
            objectName: "cprProjection"
            Layout.fillWidth: true
            Accessible.name: qsTrId("cpr.projection")
            Accessible.description: currentText
            model: [qsTrId("cpr.thin"), qsTrId("cpr.mip"), qsTrId("cpr.mean")]
            currentIndex: ["thin", "mip", "mean"].indexOf(panel.controller?.parameters.projection ?? "thin")
            onActivated: panel.controller.setParameter("projection", ["thin", "mip", "mean"][currentIndex])
        }
        Repeater {
            model: ["angle", "thickness"]
            delegate: CprParameterField {
                required property string modelData
                controller: panel.controller
                parameter: modelData
                enabled: modelData !== "thickness" || panel.controller?.parameters.projection !== "thin"
            }
        }
        Components.AppButton {
            Layout.fillWidth: true
            objectName: "cprAdvanced"
            compact: true
            checkable: true
            checked: panel.advanced
            iconName: panel.advanced ? "chevron-up" : "chevron-down"
            text: qsTrId("cpr.advanced")
            onClicked: panel.controller.togglePanelSection("cpr-advanced")
        }
        Text {
            visible: panel.advanced
            Layout.fillWidth: true
            text: qsTrId("cpr.samplingHelp")
            color: Theme.textSecondary
            wrapMode: Text.Wrap
            font.pixelSize: 11
        }
        Repeater {
            model: ["width", "step", "crossWidth"]
            delegate: CprParameterField {
                required property string modelData
                visible: panel.advanced
                controller: panel.controller
                parameter: modelData
            }
        }
        Components.AppButton {
            Layout.fillWidth: true
            objectName: "cprSamplingGuides"
            compact: true
            checkable: true
            checked: panel.controller?.showSamplingGuides ?? false
            iconName: checked ? "visible" : "hidden"
            text: qsTrId("cpr.showGuides")
            onClicked: panel.controller.setShowSamplingGuides(!panel.controller.showSamplingGuides)
            Components.AppToolTip { requested: parent.hovered; text: qsTrId("cpr.guidesHelp") }
        }
        Components.AppButton {
            Layout.fillWidth: true
            objectName: "cprInterval"
            compact: true
            checkable: true
            checked: panel.interval
            iconName: panel.interval ? "chevron-up" : "chevron-down"
            text: qsTrId("cpr.intervalSection")
            onClicked: panel.controller.togglePanelSection("cpr-interval")
        }
        Text {
            visible: panel.interval
            Layout.fillWidth: true
            text: qsTrId(panel.historical ? "cpr.intervalHistoryHelp" : "cpr.intervalHelp")
            color: Theme.textSecondary
            wrapMode: Text.Wrap
            font.pixelSize: 11
        }
        RowLayout {
            visible: panel.interval
            Layout.fillWidth: true
            enabled: (panel.controller?.intervalPositionReady ?? false) && !panel.historical
            Components.AppButton {
                objectName: "cprMarkStart"
                Layout.fillWidth: true
                compact: true
                shortcutTitle: qsTrId("cpr.markStart")
                captionKey: KeysText.hint("cpr-start", panel.shortcuts)
                onClicked: panel.controller.setParameter("rangeStart", panel.controller.positionMm)
            }
            Components.AppButton {
                objectName: "cprMarkEnd"
                Layout.fillWidth: true
                compact: true
                shortcutTitle: qsTrId("cpr.markEnd")
                captionKey: KeysText.hint("cpr-end", panel.shortcuts)
                onClicked: panel.controller.setParameter("rangeEnd", panel.controller.positionMm)
            }
        }
        Repeater {
            model: ["rangeStart", "rangeEnd"]
            delegate: CprParameterField {
                required property string modelData
                visible: panel.interval
                controller: panel.controller
                parameter: modelData
            }
        }
        Text {
            Layout.fillWidth: true
            visible: panel.interval
            text: qsTrId("cpr.interval").arg(((panel.controller?.parameters.rangeEnd ?? 0) - (panel.controller?.parameters.rangeStart ?? 0)).toFixed(2))
            color: Theme.textSecondary
            font.pixelSize: 12
            wrapMode: Text.Wrap
        }
        Components.AppLinkButton {
            visible: panel.interval && (panel.controller?.hasInterval ?? false)
            text: qsTrId("cpr.clearInterval")
            onClicked: panel.controller.clearInterval()
        }
    }
}
