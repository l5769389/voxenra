pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../../../components" as Components
import "../../../theme"

ColumnLayout {
    id: panel
    objectName: "mprLayoutPanel"
    required property var controller
    spacing: 10

    Components.PanelHeading {
        objectName: "MprLayoutPanelHeading"
        title: qsTrId("mpr.layout.title")
        explanation: qsTrId("mpr.layout.rememberHint")
    }
    GridLayout {
        Layout.fillWidth: true
        columns: 2
        columnSpacing: 6; rowSpacing: 6
        Repeater {
            model: panel.controller?.options ?? []
            delegate: Components.AppButton {
                id: choice
                required property var modelData
                objectName: "mprLayout-" + modelData.value
                Layout.fillWidth: true
                Layout.preferredWidth: 90
                Layout.preferredHeight: 66
                checkable: true
                checked: panel.controller?.layout === modelData.value
                Accessible.name: modelData.label
                onClicked: panel.controller.setLayout(modelData.value)
                contentItem: Column {
                    spacing: 4
                    Components.AppIcon {
                        anchors.horizontalCenter: parent.horizontalCenter
                        iconName: choice.modelData.icon
                        iconSize: 28
                        iconColor: choice.checked ? Theme.primaryColor : Theme.textSecondary
                    }
                    Text {
                        width: parent.width
                        text: choice.modelData.label
                        color: Theme.textPrimary
                        font.pixelSize: 11
                        horizontalAlignment: Text.AlignHCenter
                        elide: Text.ElideRight
                    }
                }
            }
        }
    }
    Components.AppCheckBox {
        objectName: "mprRememberLayout"
        Layout.fillWidth: true
        text: qsTrId("mpr.layout.remember")
        checked: panel.controller?.rememberLayout ?? false
        onToggled: panel.controller?.setRememberLayout(checked)
    }

    Text {
        Layout.fillWidth: true
        visible: text.length > 0
        text: panel.controller?.preferenceError ?? ""
        color: Theme.warningColor
        font.pixelSize: 11
        wrapMode: Text.Wrap
    }

}
