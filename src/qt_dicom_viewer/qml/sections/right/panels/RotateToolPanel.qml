pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import "../components" as Components

ColumnLayout {
    id: rotatePanel

    required property var toolController
    signal actionTriggered(string action)
    spacing: 8

    GridLayout {
        Layout.fillWidth: true
        columns: 2
        columnSpacing: 6
        rowSpacing: 6
        uniformCellWidths: true
        Repeater {
            model: rotatePanel.toolController ? rotatePanel.toolController.rotateActions : []

            delegate: Components.ToolActionButton {
                required property var modelData
                objectName: "rotateAction-" + modelData.action

                Layout.fillWidth: true
                Layout.preferredWidth: 1
                iconName: modelData.iconName
                label: modelData.label
                shortLabel: modelData.shortLabel

                onClicked: {
                    rotatePanel.actionTriggered(modelData.action);
                }
            }
        }
    }

    Item {
        Layout.fillHeight: true
    }
}
