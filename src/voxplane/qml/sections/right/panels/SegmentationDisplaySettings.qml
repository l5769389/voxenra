pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../../../components" as Components
import "../../../theme"

ColumnLayout {
    id: root
    required property var controller
    property bool expanded: false
    spacing: 6

    Components.AppButton {
        objectName: "segmentationDisplayToggle"
        Layout.fillWidth: true
        compact: true
        text: qsTrId("seg.display") + (root.expanded ? "  ▾" : "  ▸")
        Accessible.description: qsTrId("seg.displayHelp")
        onClicked: root.expanded = !root.expanded
    }
    ColumnLayout {
        visible: root.expanded
        Layout.fillWidth: true
        spacing: 6
        Components.AppComboBox {
            objectName: "segmentationDisplayMode"
            Layout.fillWidth: true
            minimumPopupWidth: 180
            readonly property var keys: ["fill", "outline", "fill-outline"]
            model: [qsTrId("seg.displayFill"), qsTrId("seg.displayOutline"), qsTrId("seg.displayBoth")]
            currentIndex: keys.indexOf(root.controller?.displayMode ?? "fill-outline")
            // Replacing translated labels resets ComboBox's current index.
            // Restore the binding after its model has settled.
            onModelChanged: Qt.callLater(function() {
                currentIndex = Qt.binding(() => keys.indexOf(root.controller?.displayMode ?? "fill-outline"))
            })
            Accessible.name: qsTrId("seg.displayMode")
            onActivated: index => root.controller.setDisplayMode(keys[index])
        }
        RowLayout {
            Layout.fillWidth: true
            enabled: root.controller?.displayMode !== "outline"
            spacing: 6
            Text {
                text: qsTrId("seg.fillOpacity")
                color: parent.enabled ? Theme.textSecondary : Theme.textMuted
                font.pixelSize: 12
            }
            Components.AppSlider {
                objectName: "segmentationFillOpacity"
                Layout.fillWidth: true
                Layout.minimumWidth: 40
                from: 0
                to: 100
                stepSize: 1
                value: root.controller?.fillOpacity ?? 30
                Accessible.name: qsTrId("seg.fillOpacity")
                onMoved: root.controller.setFillOpacity(Math.round(value))
            }
            Text {
                Layout.preferredWidth: 34
                horizontalAlignment: Text.AlignRight
                text: (root.controller?.fillOpacity ?? 30) + "%"
                color: parent.enabled ? Theme.textPrimary : Theme.textMuted
                font.pixelSize: 12
            }
        }
    }
}
