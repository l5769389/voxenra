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
    GridLayout {
        Layout.fillWidth: true
        columns: 2
        Components.AppButton {
            objectName: "cprNewPath"
            Layout.fillWidth: true
            text: qsTrId("cpr.new")
            enabled: (panel.controller?.referencesReady ?? false) && !panel.controller.drawing
            onClicked: panel.controller.startPath()
        }
        Components.AppButton {
            objectName: "cprFinishPath"
            Layout.fillWidth: true
            text: qsTrId("cpr.finish")
            enabled: panel.controller?.drawing ?? false
            onClicked: panel.controller.finishPath()
        }
        Components.AppButton {
            objectName: "cprCancelPath"
            Layout.fillWidth: true
            text: qsTrId("cpr.cancel")
            enabled: panel.controller?.drawing ?? false
            onClicked: panel.controller.cancel_operation()
        }
        Components.AppButton {
            objectName: "cprDeletePath"
            Layout.fillWidth: true
            text: qsTrId("cpr.deletePath")
            enabled: (panel.controller?.selectedPathId ?? "") !== "" && !panel.controller.drawing
            onClicked: panel.controller.deletePath()
        }
    }
    Components.AppComboBox {
        objectName: "cprPathSelector"
        Layout.fillWidth: true
        model: panel.controller?.paths ?? []
        textRole: "name"
        currentIndex: model.findIndex(item => item.pathId === panel.controller?.selectedPathId)
        enabled: !panel.controller?.drawing
        onActivated: panel.controller.selectPath(model[currentIndex].pathId)
    }
    Components.AppTextField {
        id: nameField
        objectName: "cprPathName"
        Layout.fillWidth: true
        placeholderText: qsTrId("cpr.rename")
        enabled: (panel.controller?.selectedPathId ?? "") !== "" && !panel.controller.drawing
        maximumLength: 256
        readonly property string modelText: panel.controller?.paths.find(item => item.selected)?.name ?? ""
        function sync() {
            if (!activeFocus) text = modelText
        }
        Component.onCompleted: sync()
        onModelTextChanged: sync()
        onEditingFinished: {
            panel.controller?.renamePath(text)
            text = modelText
        }
    }
    ListView {
        id: pointList
        objectName: "cprPointList"
        Layout.fillWidth: true
        Layout.preferredHeight: Math.min(140, count*30)
        clip: true
        model: panel.controller?.controlPoints ?? []
        delegate: Components.AppButton {
            required property var modelData
            width: pointList.width
            height: 30
            compact: true
            checked: modelData.selected
            text: qsTrId("cpr.point").arg(modelData.index+1) + " · "
                + modelData.x.toFixed(1) + ", " + modelData.y.toFixed(1) + ", " + modelData.z.toFixed(1)
            onClicked: panel.controller.locatePoint(modelData.index)
        }
    }
    Components.AppButton {
        objectName: "cprDeletePoint"
        Layout.fillWidth: true
        text: qsTrId("cpr.deletePoint")
        enabled: (panel.controller?.controlPoints.length ?? 0) > 0
        onClicked: panel.controller.deleteSelectedPoint()
    }
    Text {
        Layout.fillWidth: true
        text: qsTrId("cpr.total").arg((panel.controller?.totalLength ?? 0).toFixed(1))
        color: Theme.textPrimary
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
    Components.AppComboBox {
        objectName: "cprProjection"
        Layout.fillWidth: true
        model: [qsTrId("cpr.thin"), qsTrId("cpr.mip"), qsTrId("cpr.mean")]
        currentIndex: ["thin", "mip", "mean"].indexOf(panel.controller?.parameters.projection ?? "thin")
        enabled: (panel.controller?.selectedPathId ?? "") !== "" && !panel.controller.drawing
        onActivated: panel.controller.setParameter("projection", ["thin", "mip", "mean"][currentIndex])
    }
    Repeater {
        model: ["angle", "width", "thickness", "crossWidth", "step", "rangeStart", "rangeEnd"]
        delegate: RowLayout {
            id: row
            required property string modelData
            visible: panel.advanced || !["width", "crossWidth", "step"].includes(modelData)
            Layout.fillWidth: true
            Text {
                Layout.fillWidth: true
                text: qsTrId("cpr." + row.modelData)
                font.pixelSize: 12
                color: Theme.textSecondary
            }
            Components.AppTextField {
                id: input
                objectName: "cprParameter-" + row.modelData
                Layout.preferredWidth: 82
                enabled: (panel.controller?.selectedPathId ?? "") !== "" && !panel.controller.drawing
                validator: DoubleValidator { locale: "C"; decimals: 2; bottom: row.modelData === "angle" ? -360 : 0; top: 10000 }
                readonly property string modelText: Number(panel.controller?.parameters[row.modelData] ?? 0).toFixed(row.modelData === "step" ? 2 : 1)
                function sync() {
                    if (!activeFocus) text = modelText
                }
                Component.onCompleted: sync()
                onModelTextChanged: sync()
                onEditingFinished: {
                    panel.controller?.setParameter(row.modelData, Number(text))
                    text = modelText
                }
            }
        }
    }
    Text {
        Layout.fillWidth: true
        text: qsTrId("cpr.interval").arg(((panel.controller?.parameters.rangeEnd ?? 0) - (panel.controller?.parameters.rangeStart ?? 0)).toFixed(1))
        color: Theme.textSecondary
        font.pixelSize: 12
    }
    Components.AppButton {
        Layout.fillWidth: true
        objectName: "cprAdvanced"
        checkable: true
        checked: panel.advanced
        text: qsTrId("cpr.advanced")
        onClicked: panel.advanced = !panel.advanced
    }
}
