pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic as Basic
import "../../../components" as Widgets
import "../../../theme"

ColumnLayout {
    id: root
    property var controller: null
    property bool expanded: true
    spacing: 6
    Widgets.AppButton {
        objectName: "measurementResultsToggle"
        Layout.fillWidth: true
        Layout.preferredWidth: 1
        text: qsTrId("results.list") + " (" + (root.controller?.items.length ?? 0) + ")  " + (root.expanded ? "▾" : "▸")
        onClicked: root.expanded = !root.expanded
    }
    Text {
        Layout.fillWidth: true
        visible: root.expanded && !root.controller?.items.length
        text: qsTrId("results.empty")
        color: Theme.textMuted
        wrapMode: Text.Wrap
        font.pixelSize: 12
    }
    Repeater {
        model: root.expanded ? (root.controller?.items ?? []) : []
        delegate: ColumnLayout {
            id: row
            required property var modelData
            required property int index
            Layout.fillWidth: true
            spacing: 4
            Text {
                Layout.fillWidth: true
                visible: row.index === 0 || root.controller.items[row.index-1].group !== row.modelData.group
                text: row.modelData.group
                color: Theme.textMuted
                font.pixelSize: 11
                wrapMode: Text.Wrap
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: 4
                Basic.TextField {
                    objectName: "measurementName-" + row.index
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    Layout.preferredWidth: 1
                    text: row.modelData.name
                    color: Theme.textPrimary
                    font.pixelSize: 12
                    Accessible.name: qsTrId("results.rename")
                    selectByMouse: true
                    background: Rectangle { color: "transparent"; border.color: Theme.borderDefault; radius: 4 }
                    onEditingFinished: {
                        if (text !== row.modelData.name) root.controller.rename(row.modelData.key, text)
                    }
                }
                Widgets.AppButton {
                    id: visibilityButton
                    objectName: "measurementVisible-" + row.index
                    Layout.preferredWidth: 28
                    minimumButtonWidth: 28
                    compact: true
                    checkable: true
                    checked: !row.modelData.hidden
                    iconName: checked ? "visible" : "hidden"
                    Accessible.name: qsTrId("results.visible")
                    onClicked: root.controller.setHidden(row.modelData.key, !checked)
                    Widgets.AppToolTip { visible: visibilityButton.hovered; text: qsTrId("results.visible") }
                }
                Widgets.AppButton {
                    id: lockButton
                    objectName: "measurementLock-" + row.index
                    Layout.preferredWidth: 28
                    minimumButtonWidth: 28
                    compact: true
                    checkable: true
                    checked: row.modelData.locked
                    iconName: checked ? "locked" : "unlocked"
                    Accessible.name: qsTrId("results.lock")
                    onClicked: root.controller.setLocked(row.modelData.key, checked)
                    Widgets.AppToolTip { visible: lockButton.hovered; text: qsTrId("results.lock") }
                }
                Widgets.AppButton {
                    id: deleteButton
                    objectName: "deleteMeasurement-" + row.index
                    iconName: "delete"
                    Accessible.name: qsTrId("results.delete")
                    minimumButtonWidth: 28
                    Layout.preferredWidth: 28
                    compact: true
                    onClicked: root.controller.remove(row.modelData.key)
                    Widgets.AppToolTip { visible: deleteButton.hovered; text: qsTrId("results.delete") }
                }
            }
            Widgets.AppButton {
                objectName: "locateMeasurement-" + row.index
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                text: (row.modelData.value ? row.modelData.value + " · " : "") + row.modelData.location
                checked: row.modelData.selected
                onClicked: root.controller.locate(row.modelData.key)
            }
            Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: Theme.borderDefault }
        }
    }
    Text {
        Layout.fillWidth: true
        visible: text !== ""
        text: root.controller?.message ?? ""
        color: Theme.textMuted
        font.pixelSize: 12
        wrapMode: Text.Wrap
    }
}
