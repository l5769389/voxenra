pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic as Basic
import "../../../theme"
import "../../../components" as Components

Item {
    id: root
    objectName: "volumePresetPanel"
    required property var viewportController
    readonly property var controller: viewportController && viewportController.viewportType === "volume"
        ? viewportController : null
    readonly property var entries: controller ? controller.volumePresets : []
    implicitHeight: list.implicitHeight

    Column {
        id: list
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        spacing: 3

        Repeater {
            model: root.entries
            delegate: Column {
                id: entry
                required property var modelData
                required property int index
                width: list.width
                spacing: 3
                readonly property bool startsGroup: index === 0 || root.entries[index-1].group !== modelData.group

                Rectangle {
                    visible: entry.startsGroup && entry.index > 0
                    width: parent.width
                    height: 1
                    color: Theme.dividerColor
                }
                Text {
                    visible: entry.startsGroup
                    width: parent.width
                    height: 34
                    text: entry.modelData.group
                    color: Theme.textMuted
                    font.pixelSize: 13
                    verticalAlignment: Text.AlignVCenter
                }
                Components.AppButton {
                    id: presetButton
                    objectName: "volumePreset-" + entry.modelData.presetId
                    width: parent.width
                    height: 40
                    enabled: root.controller && root.controller.loadState === "ready" && entry.modelData.available
                    checked: root.controller && root.controller.currentPresetId === entry.modelData.presetId
                    Accessible.name: entry.modelData.label
                    onClicked: root.controller.applyVolumePreset(entry.modelData.presetId)
                    Components.AppToolTip {
                        visible: (parent?.hovered ?? false) && !entry.modelData.available
                        text: qsTrId("text.1087")
                    }
                    contentItem: Text {
                        text: (presetButton.checked ? "✓  " : "    ") + entry.modelData.label
                        leftPadding: 10
                        font.pixelSize: 14
                        color: presetButton.enabled ? Theme.textPrimary : Theme.textDisabled
                        verticalAlignment: Text.AlignVCenter
                    }
                    normalColor: "transparent"
                    cornerRadius: 5
                }
            }
        }
    }
}
