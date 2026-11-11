pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../../src/voxplane/qml/sections" as Sections
import "../../src/voxplane/qml/sections/center/viewportArea" as Views

Rectangle {
    id: root
    required property var workspace
    required property var panel
    color: "#101820"
    RowLayout {
        anchors.fill: parent
        Sections.LeftPanel { Layout.preferredWidth: 270; Layout.fillHeight: true; panelController: root.panel }
        Views.ViewportLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            viewportController: root.workspace.activeViewport
            currentTabAllViewports: root.workspace.currentTabAllViewports
            tabType: root.workspace.activeViewport.reconstructionController.isFusion ? "petctfusion" : "mpr"
            hasTabs: true
        }
        Sections.RightPanel {
            Layout.preferredWidth: 360
            Layout.fillHeight: true
            toolController: root.workspace.activeViewport.reconstructionController.toolController
            viewportController: root.workspace.activeViewport
            toolVisible: true
        }
    }
}
