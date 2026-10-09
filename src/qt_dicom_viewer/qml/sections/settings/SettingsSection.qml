import QtQuick
import QtQuick.Layouts
import "../../components" as Components
import "../../theme"
import "SectionState.js" as State

Rectangle {
    id: root
    default property alias contents: body.data
    property string title: ""
    property string description: ""
    property string sectionKey: title
    property var settingsController: null
    property bool sessionCollapsed: false
    readonly property bool collapsed: settingsController
        ? settingsController.values.layout.settingsCollapsedGroups.includes(sectionKey) : sessionCollapsed
    Component.onCompleted: sessionCollapsed = State.collapsed[sectionKey] === true
    implicitHeight: content.implicitHeight + 20
    color: Theme.panelBackground
    radius: 6
    ColumnLayout {
        id: content
        anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
        anchors.margins: 10
        spacing: 8
        Components.AppButton {
            objectName: "settingsGroup-" + root.sectionKey
            Layout.fillWidth: true; Layout.preferredHeight: 28
            normalColor: "transparent"; compact: true
            Accessible.name: I18n.format(qsTrId("settings.expand"), {name: root.title, action: root.collapsed ? qsTrId("common.expand") : qsTrId("common.collapse")})
            Accessible.description: root.description
            Components.AppToolTip {
                visible: (parent.hovered || parent.visualFocus) && root.description !== ""
                text: root.description
            }
            onClicked: {
                if (root.settingsController) {
                    const groups = root.settingsController.values.layout.settingsCollapsedGroups.filter(key => key !== root.sectionKey)
                    if (!root.collapsed) groups.push(root.sectionKey)
                    root.settingsController.setValue("layout", "settingsCollapsedGroups", groups)
                } else {
                    root.sessionCollapsed = !root.sessionCollapsed
                    State.collapsed[root.sectionKey] = root.sessionCollapsed
                }
            }
            contentItem: RowLayout {
                Text { Layout.fillWidth: true; text: root.title; color: Theme.textPrimary; font.pixelSize: 14; font.weight: Font.DemiBold }
                Components.AppIcon { iconName: "chevron-down"; iconSize: 14; rotation: root.collapsed ? -90 : 0 }
            }
        }
        ColumnLayout {
            id: body
            visible: !root.collapsed
            Layout.fillWidth: true; Layout.minimumWidth: 0
            spacing: 6
        }
    }
}
