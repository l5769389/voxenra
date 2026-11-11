pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../../src/voxplane/qml/sections" as Sections
import "../../src/voxplane/qml/sections/center/viewportArea" as Views

Rectangle {
    id: root
    required property var workspace
    required property var tabController
    property int rightPanelWidth: 390
    property string lastManualChapter: ""
    color: "#101820"
    RowLayout {
        anchors.fill: parent
        anchors.margins: 12
        spacing: 12
        Views.ViewportLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            viewportController: root.workspace.activeViewport
            currentTabAllViewports: root.workspace.currentTabAllViewports
            tabType: "mpr"
            hasTabs: true
            onViewportActivated: viewportId => root.tabController.activateViewport(viewportId)
        }
        Sections.RightPanel {
            Layout.preferredWidth: root.rightPanelWidth
            Layout.fillHeight: true
            toolController: root.tabController.activeToolController
            viewportController: root.workspace.activeViewport
            tabController: root.tabController
            toolVisible: true
            onManualRequested: chapter => root.lastManualChapter = chapter
        }
    }
}
