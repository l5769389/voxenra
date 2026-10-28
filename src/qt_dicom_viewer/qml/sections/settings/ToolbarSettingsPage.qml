pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../../components" as Components
import "../../theme"

Item {
    id: page
    objectName: "toolbarSettingsPage"
    required property var settingsController
    readonly property var editor: settingsController.createToolbarEditor(page)
    Component.onCompleted: editor.beginEdit()
    Component.onDestruction: editor.cancel()
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 10
        Text { text: qsTrId("toolbar.title"); color: Theme.textPrimary; font.pixelSize: 18; font.bold: true }
        RowLayout {
            Layout.fillWidth: true
            Components.AppButton {
                objectName: "toolbarScopeLeft"; text: qsTrId("toolbar.left")
                checked: page.editor.scope === "left"; checkable: true
                onClicked: page.editor.selectScope("left")
            }
            Components.AppButton {
                objectName: "toolbarScopeRight"; text: qsTrId("toolbar.right")
                checked: page.editor.scope === "right"; checkable: true
                onClicked: page.editor.selectScope("right")
            }
        }
        Components.AppComboBox {
            objectName: "toolbarProfile"
            visible: page.editor.scope === "right"
            Layout.fillWidth: true
            model: page.editor.profiles
            textRole: "label"; valueRole: "key"
            currentIndex: page.editor.profiles.findIndex(p => p.key === page.editor.selectedProfile)
            Accessible.name: qsTrId("toolbar.profile")
            onActivated: index => page.editor.selectProfile(page.editor.profiles[index].key)
        }
        Text {
            Layout.fillWidth: true
            text: page.editor.scope === "left" ? qsTrId("toolbar.fixed") : qsTrId("toolbar.hint")
            color: Theme.textSecondary; font.pixelSize: 12; wrapMode: Text.Wrap
        }
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 150
            spacing: 10
            ColumnLayout {
                Layout.fillWidth: true; Layout.fillHeight: true; Layout.preferredWidth: 1
                Text {
                    text: page.editor.scope === "left" ? qsTrId("toolbar.left")
                        : qsTrId("toolbar.common") + " · " + page.editor.commonTools.length + "/7"
                    color: Theme.textPrimary; font.pixelSize: 13
                }
                ToolbarOrderList {
                    Layout.fillWidth: true; Layout.fillHeight: true
                    editor: page.editor
                    group: page.editor.scope === "left" ? "left" : "common"
                    entries: page.editor.scope === "left" ? page.editor.leftViews : page.editor.commonTools
                }
            }
            ColumnLayout {
                visible: page.editor.scope === "right"
                Layout.fillWidth: true; Layout.fillHeight: true; Layout.preferredWidth: 1
                Text { text: qsTrId("toolbar.more"); color: Theme.textPrimary; font.pixelSize: 13 }
                ToolbarOrderList {
                    Layout.fillWidth: true; Layout.fillHeight: true
                    editor: page.editor; group: "more"; entries: page.editor.moreTools
                }
            }
        }
        Text { text: qsTrId("toolbar.preview"); color: Theme.textSecondary; font.pixelSize: 12 }
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: preview.implicitHeight + 12
            color: Theme.panelBackground; radius: Theme.controlRadius
            GridLayout {
                id: preview
                anchors.left: parent.left; anchors.right: parent.right; anchors.margins: 6; y: 6
                columns: 4; rowSpacing: 3; columnSpacing: 3
                Repeater {
                    model: page.editor.scope === "left" ? page.editor.leftViews : page.editor.commonTools
                    delegate: Rectangle {
                        required property var modelData
                        objectName: "toolbarPreview-" + modelData.toolType
                        Layout.fillWidth: true; Layout.minimumWidth: 0; Layout.preferredWidth: 1
                        Layout.horizontalStretchFactor: 1
                        implicitHeight: 28; color: Theme.controlBackground; radius: 3
                        RowLayout {
                            anchors.fill: parent; anchors.margins: 4; spacing: 5
                            Components.AppIcon { iconName: modelData.iconName; iconSize: 16; Layout.preferredWidth: 16; Layout.preferredHeight: 16 }
                            Text { Layout.fillWidth: true; text: modelData.shortLabel ?? modelData.label; elide: Text.ElideRight; color: Theme.textPrimary; font.pixelSize: 11 }
                        }
                    }
                }
                Text {
                    visible: page.editor.scope === "right"
                    Layout.fillWidth: true; Layout.minimumWidth: 0; Layout.preferredWidth: 1
                    Layout.horizontalStretchFactor: 1
                    text: qsTrId("toolbar.more") + " ⋯"; color: Theme.textSecondary; font.pixelSize: 11
                    elide: Text.ElideRight
                }
            }
        }
        Text {
            Layout.fillWidth: true
            visible: text.length > 0
            text: page.editor.message || page.settingsController.message
            wrapMode: Text.Wrap; color: Theme.dangerColor; font.pixelSize: 12
        }
        RowLayout {
            Layout.fillWidth: true
            Components.AppButton { objectName: "toolbarRestore"; text: qsTrId("toolbar.restore"); onClicked: page.editor.restoreCurrentDefault() }
            Item { Layout.fillWidth: true }
            Components.AppButton { objectName: "toolbarCancel"; text: qsTrId("toolbar.cancel"); enabled: page.editor.dirty; onClicked: page.editor.cancel() }
            Components.AppButton { objectName: "toolbarSave"; text: qsTrId("toolbar.save"); actionRole: "primary"; enabled: page.editor.dirty; onClicked: page.editor.save() }
        }
    }
}
