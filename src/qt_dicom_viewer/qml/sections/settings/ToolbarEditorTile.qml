pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../../components" as Components
import "../../theme"

Rectangle {
    id: tile
    required property var entry
    property bool selected: false
    property bool hovered: false
    property bool fixed: false
    color: selected ? Theme.selectionBackground : hovered ? Theme.controlHover : Theme.controlBackground
    border.color: selected ? Theme.selectionBorder : Theme.borderSubtle
    border.width: selected ? 2 : 1
    radius: Theme.controlRadius
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 7
        spacing: 5
        Components.AppIcon {
            Layout.alignment: Qt.AlignHCenter
            iconName: tile.entry.iconName
            iconSize: 24
            iconColor: tile.entry.available === false || tile.fixed ? Theme.textMuted : Theme.iconDefault
        }
        Text {
            Layout.fillWidth: true
            text: tile.entry.shortLabel ?? tile.entry.label
            textFormat: Text.PlainText
            color: tile.entry.available === false || tile.fixed ? Theme.textMuted : Theme.textPrimary
            horizontalAlignment: Text.AlignHCenter
            font.pixelSize: 11
            maximumLineCount: 2
            wrapMode: Text.Wrap
            elide: Text.ElideRight
        }
    }
}
