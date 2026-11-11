pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic as Basic
import "../../../components" as Components
import "../../../theme"

Basic.ComboBox {
    id: control
    required property string mode
    property string seriesLabel: ""
    readonly property string modeHint: mode === "stack" ? qsTrId("layout.originalHint") : qsTrId("layout.reconstructionHint")
    readonly property bool emphasized: hovered || activeFocus || popup.visible
    signal activationRequested()
    signal modeSelected(string mode)
    hoverEnabled: true
    topPadding: 0
    bottomPadding: 0
    leftPadding: 6
    rightPadding: 24
    font.weight: Font.DemiBold
    textRole: "label"
    model: [
        {value: "stack", label: qsTrId("layout.originalSlices"), group: qsTrId("layout.acquiredImages")},
        {value: "axial", label: qsTrId("layout.axialReconstruction"), group: qsTrId("layout.reconstructedPlanes")},
        {value: "coronal", label: qsTrId("layout.coronalReconstruction"), group: ""},
        {value: "sagittal", label: qsTrId("layout.sagittalReconstruction"), group: ""}
    ]
    currentIndex: model.findIndex(option => option.value === mode)
    displayText: model[currentIndex]?.label ?? ""
    Accessible.name: qsTrId("layout.switchView") + ": " + currentText
    Accessible.description: modeHint
    onPressedChanged: if (pressed) activationRequested()
    onActivated: modeSelected(model[currentIndex].value)
    onVisibleChanged: if (!visible) popup.close()
    contentItem: Text {
        text: control.displayText
        font: control.font
        color: Theme.textPrimary
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
        wrapMode: Text.Wrap
        maximumLineCount: 4
    }
    indicator: Components.AppIcon {
        x: control.width - width - 4
        anchors.verticalCenter: parent.verticalCenter
        iconName: "chevron-down"
        iconSize: 14
        iconColor: Theme.iconActive
        rotation: control.popup.visible ? 180 : 0
    }
    background: Rectangle {
        color: control.emphasized ? Theme.primarySoftHover : Theme.primarySoft
        radius: 4
    }
    Components.AppToolTip {
        requested: control.hovered && !control.popup.visible && !control.pressed
        text: control.currentText + "\n" + control.modeHint + (control.seriesLabel ? "\n" + control.seriesLabel : "")
        placement: "right"
    }
    delegate: Basic.ItemDelegate {
        id: option
        required property int index
        required property var modelData
        objectName: "twoDModeOption-" + modelData.value
        width: control.popup.availableWidth
        implicitHeight: modelData.group ? 62 : 34
        topPadding: modelData.group ? 28 : 0
        bottomPadding: 0
        leftPadding: 10; rightPadding: 30
        text: modelData.label
        highlighted: control.highlightedIndex === index
        Text {
            x: 10; y: 4; height: 20
            text: option.modelData.group
            visible: text !== ""
            color: Theme.textMuted
            font.pixelSize: 11
            verticalAlignment: Text.AlignVCenter
        }
        contentItem: Text {
            text: option.modelData.label
            color: Theme.textPrimary
            font.pixelSize: 13
            verticalAlignment: Text.AlignVCenter
        }
        Components.AppIcon {
            anchors.right: parent.right; anchors.rightMargin: 8
            y: option.topPadding + (34 - height) / 2
            iconName: "check"; iconSize: 14; iconColor: Theme.primaryColor
            visible: control.currentIndex === option.index
        }
        background: Item {
            Rectangle {
                y: option.topPadding
                width: parent.width; height: 34
                radius: 4
                color: option.highlighted ? Theme.selectionBackground : Theme.cardBackground
            }
        }
    }
    popup: Basic.Popup {
        id: options
        readonly property Components.PopupScope shortcutScope: Components.PopupScope { popup: options }
        y: control.height + 4
        width: 220
        padding: 4
        margins: 8
        implicitHeight: Math.min(contentItem.implicitHeight + 8, 320)
        popupType: Basic.Popup.Item
        contentItem: ListView {
            clip: true
            implicitHeight: contentHeight
            model: control.popup.visible ? control.delegateModel : null
            currentIndex: control.highlightedIndex
            boundsBehavior: Flickable.StopAtBounds
            Basic.ScrollBar.vertical: Components.AppScrollBar {}
        }
        background: Rectangle {
            color: Theme.cardBackground
            radius: Theme.controlRadius
            border.color: Theme.borderStrong
        }
    }
}
