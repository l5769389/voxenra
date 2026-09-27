pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic as Basic
import "../theme"

Basic.ComboBox {
    id: control
    property real minimumPopupWidth: 0
    Layout.minimumWidth: 0
    implicitHeight: Theme.controlHeight
    leftPadding: 10
    rightPadding: 30
    font.pixelSize: Theme.bodyFontSize
    hoverEnabled: true
    contentItem: Text {
        text: control.displayText
        color: control.enabled ? Theme.textPrimary : Theme.textDisabled
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
        font: control.font
    }
    indicator: AppIcon {
        x: control.width - width - 10
        y: (control.height - height) / 2
        iconName: "chevron-down"
        iconSize: 14
        iconColor: control.enabled ? Theme.iconDefault : Theme.iconDisabled
        rotation: control.popup.visible ? 180 : 0
    }
    background: Rectangle {
        color: control.enabled ? (control.hovered ? Theme.controlHover : Theme.controlBackground) : Theme.controlDisabled
        border.width: control.activeFocus ? 2 : 1
        border.color: !control.enabled ? Theme.controlBorder : control.activeFocus ? Theme.focusBorder
            : control.hovered ? Theme.controlHoverBorder : Theme.inputBorder
        radius: Theme.controlRadius
    }
    delegate: Basic.ItemDelegate {
        id: option
        required property int index
        required property var modelData
        width: control.popup.availableWidth
        implicitHeight: 34
        leftPadding: 10
        rightPadding: 30
        text: control.textRole ? modelData[control.textRole] : modelData
        highlighted: control.highlightedIndex === index
        contentItem: Text {
            text: option.text
            color: Theme.textPrimary
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
            font.pixelSize: Theme.bodyFontSize
        }
        AppIcon {
            anchors.right: parent.right
            anchors.rightMargin: 8
            anchors.verticalCenter: parent.verticalCenter
            iconName: "check"
            iconSize: 14
            iconColor: Theme.primaryColor
            visible: control.currentIndex === option.index
        }
        background: Rectangle {
            radius: 4
            color: option.highlighted ? Theme.selectionBackground : Theme.cardBackground
        }
    }
    popup: Basic.Popup {
        y: control.height + 4
        width: Math.max(control.width, control.minimumPopupWidth)
        implicitHeight: Math.min(contentItem.implicitHeight + 8, 320)
        padding: 4
        contentItem: ListView {
            clip: true
            implicitHeight: contentHeight
            model: control.popup.visible ? control.delegateModel : null
            currentIndex: control.highlightedIndex
            boundsBehavior: Flickable.StopAtBounds
            Basic.ScrollBar.vertical: AppScrollBar {}
        }
        background: Rectangle {
            color: Theme.cardBackground
            border.color: Theme.borderStrong
            radius: Theme.controlRadius
        }
    }
}
