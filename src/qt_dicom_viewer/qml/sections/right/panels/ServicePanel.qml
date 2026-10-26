pragma ComponentBehavior: Bound

import QtQuick
import "../../../components" as Components
import QtQuick.Controls.Basic as Basic
import QtQuick.Layouts
import "../components" as Controls

Item {
    id: servicePanel
    objectName: "servicePanel"

    required property var toolController
    property var viewportController: null
    property var historyController: null
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

        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            Repeater {
                model: servicePanel.toolController
                    ? servicePanel.toolController.serviceActions : []

                delegate: Item {
                    id: serviceEntry
                    required property var modelData
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
                    implicitHeight: 44
                    Controls.ToolActionButton {
                        id: serviceButton
                        anchors.fill: parent
                        objectName: "serviceEntry-" + serviceEntry.modelData.iconName
                        iconSize: 24
                        iconName: serviceEntry.modelData.iconName
                        label: serviceEntry.modelData.label
                        shortLabel: serviceEntry.modelData.action === "service:qa" ? "QA" : label
                        textOnly: serviceEntry.modelData.action === "service:mtf"
                            || serviceEntry.modelData.action === "service:fwhm"
                        enabled: serviceEntry.modelData.action !== "service:qa"
                            || !servicePanel.viewportController
                            || !!servicePanel.viewportController.qaController?.available
                        checked: servicePanel.selectedService === serviceEntry.modelData.action
                        onClicked: servicePanel.actionTriggered(serviceEntry.modelData.action)
                    }
                    HoverHandler { id: serviceHover }
                    Components.AppToolTip {
                        visible: serviceHover.hovered && !serviceButton.enabled
                        delay: 400
                        text: serviceEntry.modelData.label
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
            historyController: servicePanel.historyController
            onManualRequested: servicePanel.manualRequested("water-qa")
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            visible: servicePanel.selectedService === "service:qa"
            controller: servicePanel.viewportController?.qaController ?? null
        }
    }
}
