pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../../../components" as Components
import "../../../theme"
ColumnLayout {
    id: root
    required property var controller
    spacing: 10
    Components.PanelHeading {
        objectName: "TwoDLayoutPanelHeading"
        title: qsTrId("layout.title")
        explanation: qsTrId("layout.dragHint")
    }
    GridLayout {
        Layout.fillWidth: true
        columns: 4
        columnSpacing: 4; rowSpacing: 4
        Repeater {
            model: root.controller?.options ?? []
            delegate: Components.AppButton {
                id: preset
                required property var modelData
                objectName: "twoDLayout-" + modelData.id
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                Layout.preferredWidth: 40
                Layout.preferredHeight: 42
                minimumButtonWidth: 0
                checked: root.controller?.layout === modelData.id
                Accessible.name: modelData.id
                onClicked: root.controller.setLayout(modelData.id)
                contentItem: Item {
                    Repeater {
                        model: preset.modelData.cells
                        delegate: Rectangle {
                            required property var modelData
                            x: modelData.column / preset.modelData.columns * parent.width + 1
                            y: modelData.row / preset.modelData.rows * parent.height + 1
                            width: modelData.columnSpan / preset.modelData.columns * parent.width - 2
                            height: modelData.rowSpan / preset.modelData.rows * parent.height - 2
                            color: "transparent"
                            border.color: preset.checked ? Theme.primaryColor : Theme.iconDefault
                            border.width: 1
                            antialiasing: true
                        }
                    }
                }
            }
        }
    }
    Text { text: qsTrId("layout.custom"); color: Theme.textPrimary; font.pixelSize: 13 }
    Item {
        id: customGrid
        Layout.fillWidth: true
        Layout.preferredHeight: width
        property int rows: 0
        property int columns: 0
        Grid {
            anchors.fill: parent
            columns: 6
            spacing: 3
            Repeater {
                model: 36
                Rectangle {
                    required property int index
                    width: (customGrid.width - 15) / 6
                    height: width
                    radius: 2
                    color: Math.floor(index / 6) < customGrid.rows && index % 6 < customGrid.columns
                        ? Theme.selectionBackground : Theme.controlBackground
                    border.color: Theme.borderStrong
                }
            }
        }
        MouseArea {
            anchors.fill: parent
            hoverEnabled: true
            onPositionChanged: mouse => {
                customGrid.columns = Math.max(1, Math.min(6, Math.floor(mouse.x / (width / 6)) + 1))
                customGrid.rows = Math.max(1, Math.min(6, Math.floor(mouse.y / (height / 6)) + 1))
            }
            onExited: { customGrid.rows = 0; customGrid.columns = 0 }
            onClicked: root.controller.setCustomLayout(customGrid.rows, customGrid.columns)
        }
    }


}
