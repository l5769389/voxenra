pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic as Basic
import QtQuick.Layouts
import "../../components" as Components
import "../../theme"

RowLayout {
    id: root
    required property string title
    required property string value
    property string settingName: ""
    signal edited(string color)
    spacing: 8
    Text { Layout.fillWidth: true; Layout.minimumWidth: 40; text: root.title; color: root.enabled ? Theme.textSecondary : Theme.textDisabled; font.pixelSize: 12; wrapMode: Text.Wrap }
    Components.AppButton {
        id: picker
        objectName: "colorPicker-" + root.settingName
        Layout.preferredWidth: 30
        leftPadding: 6; rightPadding: 6
        topPadding: 6; bottomPadding: 6
        minimumButtonWidth: 30
        Layout.preferredHeight: 30
        Accessible.name: I18n.format(qsTrId("settings.selectColor"), {name: root.title})
        onClicked: palette.open()
        background: Rectangle {
            radius: 5
            color: picker.hovered ? Theme.controlHover : Theme.controlBackground
            border.color: picker.visualFocus ? Theme.focusBorder : Theme.inputBorder
        }
        contentItem: Rectangle { implicitWidth: 16; implicitHeight: 16; radius: 2; color: root.value; opacity: root.enabled ? 1 : 0.45 }
        Basic.Popup {
            id: palette
            objectName: "colorPickerPopup-" + root.settingName
            x: Math.min(0, picker.width - width)
            y: picker.height + 4
            width: 208
            padding: 10
            modal: false
            focus: true
            closePolicy: Basic.Popup.CloseOnEscape | Basic.Popup.CloseOnPressOutside
            background: Rectangle { color: Theme.elevatedBackground; border.color: Theme.borderStrong; radius: 6 }
            contentItem: ColumnLayout {
                spacing: 8
                RowLayout {
                    Layout.fillWidth: true
                    Text { Layout.fillWidth: true; text: root.title; color: Theme.textSecondary; font.pixelSize: 12; elide: Text.ElideRight }
                    Components.AppButton {
                        objectName: "colorPickerClose-" + root.settingName
                        iconName: "close"; iconSize: 14
                        Layout.preferredWidth: 24; Layout.preferredHeight: 24
                        minimumButtonWidth: 24; compact: true
                        normalColor: "transparent"; Accessible.name: qsTrId("text.0621")
                        onClicked: palette.close()
                    }
                }
                GridLayout {
                    columns: 4; rowSpacing: 6; columnSpacing: 6
                    Repeater {
                        model: Theme.overlaySwatches
                        delegate: Components.AppButton {
                            id: swatch
                            required property string modelData
                            objectName: "colorChoice-" + root.settingName + "-" + modelData.slice(1)
                            Layout.preferredWidth: 40; Layout.preferredHeight: 30
                            Accessible.name: root.title + " " + modelData
                            onClicked: { root.edited(modelData); palette.close() }
                            background: Rectangle {
                                radius: 3; color: swatch.modelData
                                border.width: swatch.visualFocus || root.value === swatch.modelData ? 2 : 1
                                border.color: swatch.visualFocus || root.value === swatch.modelData ? Theme.focusBorder : Theme.borderStrong
                            }
                        }
                    }
                }
            }
        }
    }
    Components.AppTextField {
        objectName: "setting-" + root.settingName
        Layout.preferredWidth: 92
        text: root.value; font.pixelSize: 12; maximumLength: 7
        placeholderText: "#RRGGBB"; Accessible.name: root.title
        onEditingFinished: { root.edited(text); text = Qt.binding(() => root.value) }
    }
}
