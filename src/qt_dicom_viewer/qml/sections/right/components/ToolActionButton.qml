pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic as Basic
import "../../../components" as Components
import "../../../theme"

Components.AppButton {
    id: actionButton
    required property string iconName
    required property string label
    property bool placeholder: false
    property bool textOnly: false
    readonly property color foregroundColor: !enabled ? Theme.iconDisabled : down ? Theme.iconActive : hovered ? (checked ? Theme.primaryHover : Theme.iconHover) : checked ? Theme.iconActive : Theme.iconDefault
    readonly property var shortcutOwner: typeof appController !== "undefined" ? appController.shortcutController ?? null : null
    readonly property string shortcutHint: {
        const bindings = shortcutOwner?.bindings ?? []
        const match = bindings.find(item => qsTrId(item.labelId) === label)
        return match?.display ?? ""
    }
    property string tooltipText: label + (shortcutHint ? " (" + shortcutHint + ")" : "") + (placeholder ? qsTrId("text.0710") : "")
    iconSize: 24
    implicitHeight: Theme.toolbarButtonHeight
    minimumButtonWidth: 44
    compact: true
    momentary: true
    enabled: !placeholder
    Accessible.name: label
    Accessible.description: tooltipText
    baseBorderWidth: 1
    baseBorderColor: Theme.controlBorder
    disabledColor: Theme.controlBackground
    normalColor: Theme.controlBackground
    contentItem: Item {
        Components.AppIcon {
            visible: !actionButton.textOnly
            anchors.centerIn: parent
            iconName: actionButton.iconName
            iconSize: actionButton.iconSize
            iconColor: actionButton.foregroundColor
        }
        Text {
            objectName: "toolActionAbbreviation"
            anchors.fill: parent
            visible: actionButton.textOnly
            text: actionButton.label
            color: actionButton.foregroundColor
            font.pixelSize: 13
            font.weight: Font.DemiBold
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
    }
    Components.AppToolTip {
        visible: actionButton.hovered || actionButton.visualFocus
        delay: 400
        text: actionButton.tooltipText
    }
}
