pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../../../components" as Components
import "../../../theme"

ColumnLayout {
    id: panel
    required property var controller
    spacing: 10
    Components.PanelHeading {
        objectName: "CompareMprPanelHeading"
        title: qsTrId("compare.mpr.layout")
        explanation: qsTrId("compare.mpr.layoutHint") + "\n\n" + qsTrId("compare.mpr.linkHint") + "\n\n" + qsTrId("compare.mpr.displaySyncHint")
    }
    GridLayout {
        Layout.fillWidth: true
        columns: 2
        rowSpacing: 6
        columnSpacing: 6
        Repeater {
            model: [{value:"", label:qsTrId("compare.mpr.six")},
                    {value:"axial", label:qsTrId("compare.mpr.axial")},
                    {value:"coronal", label:qsTrId("compare.mpr.coronal")},
                    {value:"sagittal", label:qsTrId("compare.mpr.sagittal")}]
            delegate: Components.AppButton {
                required property var modelData
                objectName: "compareMprLayout-" + (modelData.value || "six")
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                compact: true
                checkable: true
                text: modelData.label
                checked: panel.controller?.pairPlane === modelData.value
                onClicked: panel.controller.setPairPlane(modelData.value)
            }
        }
    }

    Rectangle { Layout.fillWidth: true; height: 1; color: Theme.dividerColor }
    Text { text: qsTrId("compare.mpr.linking"); color: Theme.textPrimary; font.bold: true }
    Components.AppCheckBox {
        objectName: "compareMprLink-position"
        Layout.fillWidth: true
        text: qsTrId("compare.mpr.position")
        checked: panel.controller?.positionLinked ?? false
        enabled: panel.controller?.ready ?? false
        onClicked: panel.controller.setLink("position", checked)
    }
    Components.AppCheckBox {
        objectName: "compareMprLink-rotation"
        Layout.fillWidth: true
        text: qsTrId("compare.mpr.rotation")
        checked: panel.controller?.rotationLinked ?? false
        enabled: panel.controller?.ready ?? false
        onClicked: panel.controller.setLink("rotation", checked)
    }

    Rectangle { Layout.fillWidth: true; height: 1; color: Theme.dividerColor }
    Text { text: qsTrId("compare.mpr.displaySync"); color: Theme.textPrimary; font.bold: true }
    Components.AppCheckBox {
        objectName: "compareMprLink-window"
        Layout.fillWidth: true
        text: qsTrId("compare.mpr.window")
        checked: panel.controller?.linkStates.window ?? false
        enabled: (panel.controller?.ready ?? false) && panel.controller.windowLinkAvailable
        onClicked: panel.controller.setLink("window", checked)
    }
    Components.AppCheckBox {
        objectName: "compareMprLink-zoom"
        Layout.fillWidth: true
        text: qsTrId("compare.mpr.zoom")
        checked: panel.controller?.linkStates.zoom ?? false
        enabled: panel.controller?.ready ?? false
        onClicked: panel.controller.setLink("zoom", checked)
    }

    Text {
        Layout.fillWidth: true
        visible: panel.controller?.zoomLimitReached ?? false
        text: qsTrId("compare.mpr.zoomLimit")
        color: Theme.warningColor; font.pixelSize: 11; wrapMode: Text.Wrap
    }
    Components.AppButton {
        objectName: "compareMprResetOrientation"
        Layout.fillWidth: true
        text: qsTrId("compare.mpr.resetOrientation")
        compact: true
        enabled: panel.controller?.ready ?? false
        onClicked: panel.controller.resetActiveOrientation()
    }

}
