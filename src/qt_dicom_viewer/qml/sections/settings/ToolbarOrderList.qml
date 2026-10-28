pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic as Basic
import QtQuick.Layouts
import "../../components" as Components
import "../../theme"

Rectangle {
    id: listing
    required property var editor
    required property string group
    required property var entries
    property int dragDestination: -1
    color: Theme.panelBackground
    border.color: Theme.borderSubtle
    radius: Theme.controlRadius
    function move(source, destination) {
        if (group === "left") editor.moveLeftView(source, destination)
        else editor.moveTool(group, source, destination)
    }
    Flickable {
        id: scroll
        objectName: "toolbarList-" + listing.group
        anchors.fill: parent
        anchors.margins: 5
        clip: true
        contentWidth: width
        contentHeight: rows.height
        boundsBehavior: Flickable.StopAtBounds
        Basic.ScrollBar.vertical: Components.AppScrollBar {}
        Column {
            id: rows
            width: scroll.width - 8
            spacing: 4
            Repeater {
                model: listing.entries
                delegate: Rectangle {
                    id: row
                    required property int index
                    required property var modelData
                    objectName: "toolbarRow-" + listing.group + "-" + modelData.toolType
                    width: rows.width
                    height: 58
                    color: handle.pressed ? Theme.selectionBackground : Theme.controlBackground
                    radius: Theme.controlRadius
                    border.color: Theme.borderSubtle
                    Rectangle {
                        width: parent.width; height: 2
                        color: Theme.primaryColor
                        visible: listing.dragDestination === row.index
                    }
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 5
                        spacing: 2
                        Text {
                            Layout.fillWidth: true
                            text: row.modelData.label
                            textFormat: Text.PlainText
                            elide: Text.ElideRight
                            color: row.modelData.available === false ? Theme.textMuted : Theme.textPrimary
                            font.pixelSize: 12
                            Components.AppToolTip { text: row.modelData.label; visible: labelHover.hovered }
                            HoverHandler { id: labelHover }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 2
                            Item {
                                Layout.preferredWidth: 26; Layout.preferredHeight: 26
                                Text { anchors.centerIn: parent; text: "⠿"; font.pixelSize: 20; color: Theme.textMuted }
                                MouseArea {
                                    id: handle
                                    objectName: "toolbarDrag-" + listing.group + "-" + row.modelData.toolType
                                    anchors.fill: parent
                                    cursorShape: pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor
                                    preventStealing: true
                                    property real startY: 0
                                    property bool moved: false
                                    onPressed: mouse => { startY = mouse.y; moved = false }
                                    onPositionChanged: mouse => {
                                        if (!pressed) return
                                        if (Math.abs(mouse.y - startY) > 8) moved = true
                                        if (!moved) return
                                        const point = mapToItem(rows, mouse.x, mouse.y)
                                        listing.dragDestination = Math.max(0, Math.min(listing.entries.length - 1, Math.floor(point.y / 62)))
                                    }
                                    onReleased: {
                                        const destination = listing.dragDestination
                                        listing.dragDestination = -1
                                        if (moved && destination >= 0) listing.move(row.index, destination)
                                    }
                                    onCanceled: listing.dragDestination = -1
                                }
                                Components.AppToolTip { text: qsTrId("toolbar.drag"); visible: handle.containsMouse }
                            }
                            Components.AppButton {
                                objectName: "toolbarUp-" + listing.group + "-" + row.modelData.toolType
                                Layout.preferredWidth: 26; Layout.preferredHeight: 26
                                text: "↑"; compact: true; enabled: row.index > 0
                                Accessible.name: qsTrId("toolbar.up") + " · " + row.modelData.label
                                onClicked: listing.move(row.index, row.index - 1)
                            }
                            Components.AppButton {
                                objectName: "toolbarDown-" + listing.group + "-" + row.modelData.toolType
                                Layout.preferredWidth: 26; Layout.preferredHeight: 26
                                text: "↓"; compact: true; enabled: row.index < listing.entries.length - 1
                                Accessible.name: qsTrId("toolbar.down") + " · " + row.modelData.label
                                onClicked: listing.move(row.index, row.index + 1)
                            }
                            Item { Layout.fillWidth: true }
                            Components.AppButton {
                                objectName: "toolbarGroup-" + listing.group + "-" + row.modelData.toolType
                                visible: listing.group !== "left"
                                Layout.preferredWidth: 26; Layout.preferredHeight: 26
                                text: listing.group === "common" ? "−" : "+"; compact: true
                                Accessible.name: (listing.group === "common" ? qsTrId("toolbar.toMore") : qsTrId("toolbar.toCommon")) + " · " + row.modelData.label
                                onClicked: listing.editor.moveToGroup(row.modelData.toolType, listing.group === "common" ? "more" : "common")
                                Components.AppToolTip { text: parent.Accessible.name; visible: parent.hovered }
                            }
                        }
                    }
                }
            }
            Text {
                visible: listing.entries.length === 0
                width: rows.width
                text: qsTrId("toolbar.empty"); color: Theme.textMuted; wrapMode: Text.Wrap
            }
        }
    }
}
