pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../theme"

Item {
    id: footer
    default property alias actions: actionsRow.data
    property alias leading: leadingRow.data
    property bool separatorVisible: true
    readonly property real preferredContentWidth: leadingRow.implicitWidth + actionsRow.implicitWidth
        + 2 * footerRow.spacing + 2 * footerRow.anchors.margins
    implicitHeight: Theme.controlHeight + 32
    Rectangle {
        visible: footer.separatorVisible
        anchors.top: parent.top
        width: parent.width
        height: 1
        color: Theme.dividerColor
    }
    RowLayout {
        id: footerRow
        anchors.fill: parent
        anchors.margins: 16
        spacing: 12
        RowLayout {
            id: leadingRow
            Layout.minimumWidth: 0
            Layout.maximumWidth: Math.max(0, footer.width - 56 - actionsRow.implicitWidth)
            Layout.preferredHeight: Theme.controlHeight
            spacing: 8
        }
        Item { Layout.fillWidth: true; Layout.minimumWidth: 0 }
        RowLayout {
            id: actionsRow
            Layout.preferredHeight: Theme.controlHeight
            spacing: 8
        }
    }
}
