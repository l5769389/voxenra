import QtQuick
import QtQuick.Controls.Basic as Basic
import "../theme"

Basic.CheckBox {
    id: control
    // Match a pointer/keyboard activation: update state and emit the action.
    Accessible.onToggleAction: control.click()
    implicitHeight: Theme.controlHeight
    spacing: 8
    padding: 4
    hoverEnabled: true
    indicator: Rectangle {
        implicitWidth: 18
        implicitHeight: 18
        x: control.leftPadding
        y: (control.height - height) / 2
        radius: 4
        color: !control.enabled ? Theme.controlDisabled
            : control.checkState !== Qt.Unchecked ? Theme.selectionBackground : Theme.controlBackground
        border.color: !control.enabled ? Theme.controlBorder
            : control.checkState !== Qt.Unchecked ? Theme.selectionBorder : Theme.inputBorder
        AppIcon {
            anchors.centerIn: parent
            iconName: "check"
            iconSize: 14
            visible: control.checkState === Qt.Checked
            iconColor: control.enabled ? Theme.primaryColor : Theme.iconDisabled
        }
        Rectangle {
            anchors.centerIn: parent
            width: 9; height: 2; radius: 1
            visible: control.checkState === Qt.PartiallyChecked
            color: control.enabled ? Theme.primaryColor : Theme.iconDisabled
        }
    }
    contentItem: Text {
        text: control.text
        color: control.enabled ? Theme.textSecondary : Theme.textDisabled
        font.pixelSize: Theme.bodyFontSize
        verticalAlignment: Text.AlignVCenter
        leftPadding: control.indicator.width + control.spacing
        elide: Text.ElideRight
    }
    background: Rectangle {
        radius: Theme.controlRadius
        color: control.enabled && control.hovered ? Theme.controlHover : "transparent"
        border.width: control.activeFocus ? 2 : 0
        border.color: Theme.focusBorder
    }
}
