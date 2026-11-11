pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic as Basic
import "../../../components" as Widgets
import "../../../theme"

ColumnLayout {
    id: root
    property var controller: null
    property var dicomResults: null
    property bool maskConversionAvailable: false
    property Item fixedHeaderParent: null
    readonly property real headerHeight: header.implicitHeight + spacing
    property bool expanded: true
    spacing: 4

    component RowAction: Widgets.AppButton {
        Layout.preferredWidth: 28
        Layout.preferredHeight: 28
        minimumButtonWidth: 28
        compact: true
        iconSize: 16
        normalColor: "transparent"
        activeColor: "transparent"
        activeBorderColor: "transparent"
        activeHoverColor: Theme.controlHover
        textColor: Theme.textSecondary
        hintText: Accessible.name
    }

    Item {
        id: inlineHeader
        Layout.fillWidth: true
        implicitHeight: header.implicitHeight
        visible: !root.fixedHeaderParent
    }
    ColumnLayout {
        id: header
        parent: root.fixedHeaderParent ?? inlineHeader
        width: root.width
        height: implicitHeight
        spacing: root.spacing
        Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: Theme.dividerColor }
        RowLayout {
            Layout.fillWidth: true
            spacing: 2
            Widgets.AppButton {
                objectName: "measurementResultsToggle"
                Layout.fillWidth: true
                compact: true
                normalColor: "transparent"
                text: qsTrId("results.list") + " (" + (root.controller?.items.length ?? 0) + ")"
                Accessible.name: text
                Accessible.checkable: true
                Accessible.checked: root.expanded
                onClicked: root.expanded = !root.expanded
                contentItem: RowLayout {
                    Text {
                        Layout.fillWidth: true
                        text: qsTrId("results.list")
                        font.pixelSize: 14
                        font.weight: Font.DemiBold
                        color: Theme.textPrimary
                        elide: Text.ElideRight
                    }
                    Text {
                        text: root.controller?.items.length ?? 0
                        color: Theme.textSecondary
                        font.pixelSize: 12
                    }
                    Widgets.AppIcon {
                        iconName: root.expanded ? "chevron-down" : "chevron-right"
                        iconSize: 14
                        iconColor: Theme.iconDefault
                    }
                }
            }
            RowAction {
                id: moreButton
                objectName: "measurementResultsMore"
                iconName: "more"
                Accessible.name: qsTrId("results.more")
                onClicked: {
                    resultMenu.targetId = root.controller?.clearableViewportId ?? ""
                    resultMenu.open()
                }
                Basic.Menu {
                    id: resultMenu
                    property string targetId: ""
                    parent: moreButton
                    x: moreButton.width - width
                    y: moreButton.height
                    popupType: Basic.Popup.Item
                    margins: 6
                    width: Math.min(300, (moreButton.Window.window?.width ?? 300) - margins * 2,
                                    Math.ceil(clearItem.implicitContentWidth) + 32)
                    padding: 4
                    focus: true
                    background: Rectangle {
                        color: Theme.elevatedBackground
                        border.color: Theme.borderStrong
                        radius: Theme.controlRadius
                    }
                    Basic.MenuItem {
                        id: clearItem
                        objectName: "clearViewportMeasurements"
                        enabled: resultMenu.targetId !== "" && resultMenu.targetId === root.controller?.clearableViewportId
                        text: qsTrId("results.clearViewport")
                        onTriggered: root.controller.clearViewportMeasurements(resultMenu.targetId)
                        contentItem: Text {
                            text: clearItem.text
                            font.pixelSize: 13
                            color: clearItem.enabled ? Theme.dangerColor : Theme.textDisabled
                            wrapMode: Text.Wrap
                            verticalAlignment: Text.AlignVCenter
                        }
                        background: Rectangle {
                            radius: Theme.controlRadius
                            color: clearItem.highlighted ? Theme.controlHover : "transparent"
                        }
                    }
                }
            }
        }
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
            Layout.minimumWidth: 0
            spacing: 4

            Text {
                Layout.fillWidth: true
                Layout.topMargin: row.index === 0 ? 0 : 4
                Layout.leftMargin: 3
                visible: row.index === 0 || root.controller.items[row.index - 1].group !== row.modelData.group
                text: row.modelData.group
                textFormat: Text.PlainText
                color: Theme.textSecondary
                font.pixelSize: 12
                font.weight: Font.DemiBold
                wrapMode: Text.Wrap
            }
            Basic.Control {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                Layout.leftMargin: 3
                leftPadding: 7
                rightPadding: 4
                topPadding: 2
                bottomPadding: 2
                background: Rectangle {
                    radius: Theme.controlRadius
                    color: row.modelData.selected ? Theme.selectionBackground : Theme.controlBackground
                    border.color: Theme.borderSubtle
                    border.width: row.modelData.selected ? 0 : 1
                    Rectangle {
                        visible: row.modelData.selected
                        anchors.left: parent.left
                        anchors.verticalCenter: parent.verticalCenter
                        width: 3
                        height: parent.height - 12
                        radius: 1.5
                        color: Theme.activeIndicator
                    }
                }
                contentItem: ColumnLayout {
                    spacing: 0
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 1
                        Basic.TextField {
                            id: nameField
                            objectName: "measurementName-" + row.index
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            Layout.preferredWidth: 1
                            leftPadding: 4
                            rightPadding: 4
                            text: row.modelData.name
                            color: Theme.textPrimary
                            font.pixelSize: 12
                            Accessible.name: qsTrId("results.rename")
                            Accessible.description: row.modelData.name
                            selectByMouse: true
                            hoverEnabled: true
                            background: Rectangle {
                                radius: 3
                                color: nameField.activeFocus ? Theme.controlBackground : "transparent"
                                border.width: nameField.activeFocus || nameField.hovered ? 1 : 0
                                border.color: nameField.activeFocus ? Theme.focusBorder : Theme.controlHoverBorder
                            }
                            onEditingFinished: {
                                if (text !== row.modelData.name) root.controller.rename(row.modelData.key, text)
                            }
                        }
                        RowAction {
                            objectName: "measurementVisible-" + row.index
                            checkable: true
                            checked: !row.modelData.hidden
                            iconName: checked ? "visible" : "hidden"
                            Accessible.name: qsTrId(checked ? "action.hideMeasurement" : "action.showMeasurement")
                            onClicked: root.controller.setHidden(row.modelData.key, !checked)
                        }
                        RowAction {
                            objectName: "measurementLock-" + row.index
                            checkable: true
                            checked: row.modelData.locked
                            iconName: checked ? "locked" : "unlocked"
                            Accessible.name: qsTrId(checked ? "action.unlockMeasurement" : "action.lockMeasurement")
                            onClicked: root.controller.setLocked(row.modelData.key, checked)
                        }
                        RowAction {
                            objectName: "deleteMeasurement-" + row.index
                            iconName: "delete"
                            Accessible.name: qsTrId("results.delete")
                            hoverColor: Theme.dangerSurface
                            textColor: hovered ? Theme.dangerColor : Theme.textSecondary
                            onClicked: root.controller.remove(row.modelData.key)
                        }
                    }
                    Widgets.AppButton {
                        objectName: "locateMeasurement-" + row.index
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        Layout.preferredWidth: 1
                        implicitHeight: Math.max(26, contentItem.implicitHeight + 4)
                        leftPadding: 4
                        rightPadding: 4
                        topPadding: 2
                        bottomPadding: 2
                        normalColor: "transparent"
                        activeColor: "transparent"
                        activeBorderColor: "transparent"
                        checked: row.modelData.selected
                        text: (row.modelData.value ? row.modelData.value + " · " : "") + row.modelData.location
                        hintText: qsTrId("results.locate") + " · " + row.modelData.name + " · " + text
                        Accessible.name: hintText
                        Accessible.selected: checked
                        onClicked: root.controller.locate(row.modelData.key)
                        contentItem: RowLayout {
                            spacing: 6
                            Text {
                                visible: text.length > 0
                                text: row.modelData.value
                                color: Theme.textPrimary
                                font.pixelSize: 14
                                font.weight: Font.DemiBold
                            }
                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: row.modelData.location
                                textFormat: Text.PlainText
                                color: Theme.textSecondary
                                font.pixelSize: 11
                                wrapMode: Text.Wrap
                                horizontalAlignment: row.modelData.value ? Text.AlignRight : Text.AlignLeft
                            }
                        }
                    }
                    Widgets.AppButton {
                        objectName: "freehandToSegmentation"
                        readonly property string resultKey: row.modelData.key
                        Layout.fillWidth: true
                        Layout.preferredWidth: 1
                        compact: true
                        visible: root.maskConversionAvailable && row.modelData.convertibleRoi
                        enabled: !!root.dicomResults && !root.dicomResults.busy
                        text: qsTrId("results.convertRoi")
                        hintText: qsTrId("seg.convertRoi") + " · " + row.modelData.name
                        onClicked: root.dicomResults.convertSelectedRoi(resultKey)
                    }
                }
            }
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
