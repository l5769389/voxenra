pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic as Basic
import QtQuick.Layouts
import "../../../components" as Components
import "../../../components/ShortcutCaption.js" as KeysText
import "../../../theme"

Components.AppButton {
    id: actionButton
    required property string iconName
    required property string label
    property bool placeholder: false
    property bool textOnly: false
    property bool centerLabel: false
    property string shortLabel: label
    property bool showLabel: !textOnly && width >= 60
        && (typeof appController !== "undefined" ? appController.settingsController?.values.appearance.toolLabels ?? false : false)
    readonly property color foregroundColor: !enabled ? Theme.iconDisabled : actionRole === "primary" ? Theme.textOnPrimary
        : down ? Theme.iconActive : hovered ? (checked ? Theme.primaryHover : Theme.iconHover) : checked ? Theme.iconActive : Theme.iconDefault
    readonly property var shortcutOwner: typeof appController !== "undefined" ? appController.shortcutController ?? null : null
    property string shortcutAction: ""
    property string shortcutHint: KeysText.hint(shortcutAction, shortcutOwner?.bindings ?? [])
    property string tooltipText: label + (shortcutHint ? " (" + shortcutHint + ")" : "") + (placeholder ? qsTrId("text.0710") : "")
    readonly property real labeledWidth: leftPadding + iconSize + 5 + caption.preferredWidth + rightPadding
    fontPixelSize: 11
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
        RowLayout {
            anchors.centerIn: parent
            width: !actionButton.showLabel ? actionButton.iconSize : actionButton.centerLabel
                ? Math.min(parent.width, actionButton.iconSize + spacing + caption.preferredWidth) : parent.width
            spacing: 5
            visible: !actionButton.textOnly
            Components.AppIcon {
                Layout.alignment: Qt.AlignVCenter
                iconName: actionButton.iconName
                iconSize: actionButton.iconSize
                iconColor: actionButton.foregroundColor
            }
            Components.ShortcutLabel {
                id: caption
                objectName: "toolActionLabel"
                visible: actionButton.showLabel
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                Layout.preferredWidth: 0
                title: actionButton.shortLabel
                // The row has not assigned the label width during Loader transitions.
                captionWidth: Math.max(0, actionButton.availableWidth - actionButton.iconSize - 5)
                keyHint: actionButton.shortcutHint
                color: actionButton.foregroundColor
                font.pixelSize: actionButton.fontPixelSize
                verticalAlignment: Text.AlignVCenter
            }
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
        displayedCaption: actionButton.textOnly ? actionButton.label : caption.visible && !caption.truncated ? caption.text : ""
        requested: actionButton.hovered || actionButton.visualFocus
        delay: 400
        text: actionButton.tooltipText
    }
}
