pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import "../../../components" as Components
import "../../../theme"

Item {
    id: servicePanel
    objectName: "servicePanel"

    required property var toolController
    property var viewportController: null
    property Item exportItem: null
    readonly property string selectedService: servicePanel.toolController
        ? servicePanel.toolController.activeService : ""

    signal actionTriggered(string action)
    signal manualRequested(string chapter)

    implicitHeight: content.implicitHeight

    // 内容始终从顶部排列；外层统一负责超出高度后的滚动。
    ColumnLayout {
        id: content
        anchors.top: parent.top
        width: parent.width
        spacing: 10

        Rectangle {
            objectName: "analysisServiceTabs"
            Layout.fillWidth: true
            implicitHeight: 40
            radius: 7
            color: Theme.panelBackgroundStrong
            RowLayout {
                anchors.fill: parent
                anchors.margins: 3
                spacing: 3
                Repeater {
                    model: servicePanel.toolController
                        ? servicePanel.toolController.serviceActions : []

                    delegate: Components.AppButton {
                        id: serviceEntry
                        required property var modelData
                        Layout.fillWidth: true
                        Layout.preferredWidth: 1
                        Layout.fillHeight: true
                        objectName: "serviceEntry-" + modelData.iconName
                        text: modelData.label
                        normalColor: "transparent"
                        disabledColor: "transparent"
                        textColor: checked ? Theme.iconActive : Theme.textSecondary
                        cornerRadius: 5
                        fontPixelSize: 13
                        fontWeight: Font.DemiBold
                        momentary: true
                        compact: true
                        Accessible.role: Accessible.RadioButton
                        Accessible.checkable: true
                        Accessible.checked: checked
                        hintText: qsTrId("analysis.hint." + modelData.iconName)
                        enabled: modelData.action !== "service:qa"
                            || !servicePanel.viewportController
                            || !!servicePanel.viewportController.qaController?.available
                        checked: servicePanel.selectedService === modelData.action
                        onClicked: servicePanel.actionTriggered(modelData.action)
                    }
                }
            }
        }

        MtfResults {
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            visible: servicePanel.selectedService === "service:mtf"
            controller: servicePanel.viewportController?.mtfController ?? null
        }

        FwhmResults {
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            visible: servicePanel.selectedService === "service:fwhm"
            controller: servicePanel.viewportController?.fwhmController ?? null
        }

        WaterQaResults {
            exportItem: servicePanel.exportItem
            onManualRequested: servicePanel.manualRequested("water-qa")
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            visible: servicePanel.selectedService === "service:qa"
            controller: servicePanel.viewportController?.qaController ?? null
        }
    }
}
