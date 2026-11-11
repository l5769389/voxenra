pragma ComponentBehavior: Bound
import QtQuick
import "../theme"
Rectangle {
    id: badge
    property string modality: ""
    property bool compact: false
    readonly property string label: modality === "PT" ? "PET" : (modality || "—")
    implicitWidth: labelItem.implicitWidth + (compact ? 8 : 12)
    implicitHeight: compact ? 13 : 20
    radius: 4
    color: Theme.selectionBackground
    border.color: Theme.selectionBorder
    Text {
        id: labelItem
        anchors.centerIn: parent
        text: badge.label
        textFormat: Text.PlainText
        font.pixelSize: badge.compact ? 9 : 11
        font.weight: Font.Bold
        color: Theme.primaryColor
    }
}
