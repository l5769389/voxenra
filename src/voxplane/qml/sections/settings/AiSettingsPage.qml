pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts

ColumnLayout {
    id: root
    required property var settingsController
    spacing: 12
    LocalSegmentationSettings {
        settingsController: root.settingsController
        Layout.fillWidth: true
    }
}
