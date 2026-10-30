pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../../../components" as Components
import "../../../theme"

ColumnLayout {
    id: panel
    objectName: "cprPanel"
    required property var controller
    property bool advanced: false
    property bool details: false
    property bool interval: false
    readonly property bool drawing: controller?.drawing ?? false
    readonly property bool editing: !drawing && (controller?.pathEditing ?? false)
    readonly property bool hasPath: (controller?.selectedPathId ?? "") !== ""
    readonly property int pointCount: controller?.controlPoints.length ?? 0
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
        visible: !panel.drawing
        Components.AppButton {
            objectName: "cprNewPath"
            Layout.fillWidth: true
            text: qsTrId("cpr.new")
            iconName: "add"
            compact: true
            actionRole: panel.hasPath ? "neutral" : "primary"
            enabled: panel.controller?.referencesReady ?? false
            onClicked: panel.controller.startPath()
        }
        Components.AppButton {
            objectName: "cprEditPath"
            Layout.fillWidth: true
            visible: panel.hasPath
            text: qsTrId(panel.editing ? "cpr.doneEditing" : "cpr.edit")
            iconName: panel.editing ? "check" : "cpr-path"
            compact: true
            checked: panel.editing
            onClicked: panel.controller.setPathEditing(!panel.editing)
        }
    }
    Text {
        objectName: "cprPathStatus"
        Accessible.role: Accessible.StaticText
        Accessible.name: text
        Layout.fillWidth: true
        text: panel.drawing ? qsTrId("cpr.draftCount").arg(panel.pointCount)
            : qsTrId("cpr.pathSummary").arg(panel.pointCount)
        color: panel.drawing ? Theme.textPrimary : Theme.textSecondary
        wrapMode: Text.Wrap
        font.pixelSize: 12
    }
    RowLayout {
        Layout.fillWidth: true
        visible: panel.drawing
        Components.AppButton {
            objectName: "cprFinishPath"
            Layout.fillWidth: true
            text: qsTrId("cpr.finish")
            iconName: "check"
            actionRole: "primary"
            enabled: panel.controller?.canFinishPath ?? false
            onClicked: panel.controller.finishPath()
        }
        Components.AppButton {
            objectName: "cprCancelPath"
            Layout.fillWidth: true
            text: qsTrId("cpr.cancel")
            iconName: "close"
            onClicked: panel.controller.cancel_operation()
        }
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
        text: qsTrId(panel.drawing ? "cpr.undoPoint" : "cpr.deletePoint")
        iconName: panel.drawing ? "undo" : "delete"
        enabled: panel.controller?.canDeletePoint ?? false
        onClicked: panel.controller.deleteSelectedPoint()
    }
    Components.AppButton {
        objectName: "cprDetails"
        Layout.fillWidth: true
        visible: panel.hasPath || panel.drawing
        compact: true
        text: qsTrId("cpr.pathDetails")
        iconName: panel.details ? "chevron-up" : "chevron-down"
        checkable: true
        checked: panel.details
        onClicked: panel.details = !panel.details
    }
    ColumnLayout {
        Layout.fillWidth: true
        visible: panel.details && (panel.hasPath || panel.drawing)
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
            model: panel.controller?.controlPoints ?? []
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
        Text {
            Layout.fillWidth: true
            Layout.topMargin: 6
            text: qsTrId("cpr.sectionPosition")
            font.weight: Font.DemiBold
            color: Theme.textPrimary
            font.pixelSize: 12
        }
        Text {
            Layout.fillWidth: true
            text: qsTrId("cpr.distance").arg((panel.controller?.positionMm ?? 0).toFixed(1))
                .arg((panel.controller?.totalLength ?? 0).toFixed(1))
            color: Theme.textSecondary
            font.pixelSize: 12
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
        Text {
            Layout.fillWidth: true
            text: qsTrId("cpr.reconstruction")
            font.weight: Font.DemiBold
            color: Theme.textPrimary
            font.pixelSize: 12
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
            onClicked: panel.advanced = !panel.advanced
        }
        Repeater {
            model: ["width", "crossWidth", "step"]
            delegate: CprParameterField {
                required property string modelData
                visible: panel.advanced
                controller: panel.controller
                parameter: modelData
            }
        }
        Components.AppButton {
            Layout.fillWidth: true
            objectName: "cprInterval"
            compact: true
            checkable: true
            checked: panel.interval
            iconName: panel.interval ? "chevron-up" : "chevron-down"
            text: qsTrId("cpr.intervalSection")
            onClicked: panel.interval = !panel.interval
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
            text: qsTrId("cpr.interval").arg(((panel.controller?.parameters.rangeEnd ?? 0) - (panel.controller?.parameters.rangeStart ?? 0)).toFixed(1))
            color: Theme.textSecondary
            font.pixelSize: 12
            wrapMode: Text.Wrap
        }
    }
}
