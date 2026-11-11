pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic as Basic
import "../../../theme"
import "../../../components" as Components

Item {
    id: root
    objectName: "volumeDirectionPanel"
    required property var viewportController
    readonly property var controller: viewportController && viewportController.viewportType === "volume"
        ? viewportController : null
    implicitHeight: choices.implicitHeight

    GridLayout {
        id: choices
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        columns: 2
        columnSpacing: 8
        rowSpacing: 8

        Repeater {
            model: root.controller ? root.controller.directionOptions : []
            delegate: Components.AppButton {
                id: directionButton
                required property var modelData
                objectName: "volumeFace-" + modelData.face
                Layout.fillWidth: true
                Layout.preferredHeight: 46
                enabled: root.controller && root.controller.loadState === "ready"
                checked: root.controller && root.controller.currentFace === modelData.face
                Accessible.name: modelData.label
                onClicked: root.controller.setViewFace(modelData.face)
                contentItem: RowLayout {
                    spacing: 8
                    Rectangle {
                        Layout.leftMargin: 6
                        width: 7
                        height: 22
                        radius: 3
                        color: directionButton.modelData.color
                    }
                    Text {
                        Layout.fillWidth: true
                        text: directionButton.modelData.label
                        font.pixelSize: 14
                        color: directionButton.enabled ? Theme.textPrimary : Theme.textDisabled
                        horizontalAlignment: Text.AlignHCenter
                    }
                }
                baseBorderWidth: 1
                baseBorderColor: Theme.controlBorder
                activeBorderColor: modelData.color
            }
        }
    }
}
