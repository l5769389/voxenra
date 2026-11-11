pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Shapes
import QtQuick.Controls.Basic as Basic
import "../components" as Components
import "../theme"

Item {
    id: sidebar
    objectName: "sidebarContainer"
    required property var panelController
    property var pacsController: null
    property var workspaceController: null
    property var exportController: null
    property var documentController: null
    readonly property real minimumExpandedWidth: 200
    readonly property real maximumExpandedWidth: 350
    property real expandedWidth: 300
    property bool collapsed: false
    property bool compactRequired: false
    property real availableExpandedWidth: maximumExpandedWidth
    readonly property bool compact: collapsed || compactRequired
    property bool resizing: false
    implicitWidth: compact ? 52 : Math.min(expandedWidth, Math.max(minimumExpandedWidth, availableExpandedWidth))
    z: 10

    function resizeTo(candidate) {
        if (candidate < minimumExpandedWidth) {
            collapsed = true
        } else {
            expandedWidth = Math.min(maximumExpandedWidth, availableExpandedWidth, candidate)
            collapsed = false
        }
    }

    LeftPanel {
        id: panel
        anchors.fill: parent
        compact: sidebar.compact
        panelController: sidebar.panelController
        pacsController: sidebar.pacsController
        workspaceController: sidebar.workspaceController
        exportController: sidebar.exportController
        documentController: sidebar.documentController
    }

    Components.AppButton {
        id: toggle
        objectName: "sidebarToggle"
        anchors.bottom: parent.bottom
        anchors.bottomMargin: (panel.footerRowHeight - height) / 2
        x: sidebar.compact ? (parent.width - width) / 2 : parent.width - width - 8
        width: 28; height: 28
        minimumButtonWidth: 0
        compact: true
        momentary: true
        text: sidebar.compact ? "›" : "‹"
        enabled: !sidebar.compactRequired
        padding: 0
        contentItem: Item {
            Shape {
                objectName: "sidebarToggleChevron"
                anchors.centerIn: parent
                width: 18; height: 18
                antialiasing: true
                ShapePath {
                    strokeColor: Theme.textPrimary
                    strokeWidth: 1.8
                    fillColor: "transparent"
                    capStyle: ShapePath.RoundCap
                    joinStyle: ShapePath.RoundJoin
                    PathSvg { path: sidebar.compact ? "M6.5 4 L11.5 9 L6.5 14" : "M11.5 4 L6.5 9 L11.5 14" }
                }
            }
        }
        Accessible.name: sidebar.compactRequired ? qsTrId("layout.expandNeedsSpace")
            : sidebar.compact ? qsTrId("text.0677") : qsTrId("text.0678")
        normalColor: "transparent"
        onClicked: sidebar.collapsed = !sidebar.collapsed
        Components.AppToolTip {
            id: toggleTip
            requested: toggle.hovered
            delay: 600
            text: toggle.Accessible.name
        }
    }

    Rectangle {
        anchors.right: parent.right
        anchors.rightMargin: 2
        anchors.verticalCenter: parent.verticalCenter
        width: 1
        height: parent.height - 16
        visible: !sidebar.compact && (resizeArea.containsMouse || sidebar.resizing)
        color: Theme.borderStrong
    }

    MouseArea {
        id: resizeArea
        objectName: "sidebarResizeHandle"
        x: sidebar.width - width / 2
        width: 10
        height: parent.height
        visible: !sidebar.compact || sidebar.resizing
        hoverEnabled: true
        cursorShape: Qt.SizeHorCursor
        preventStealing: true
        property real pressX: 0
        property real pressWidth: 0
        onPressed: mouse => {
            pressX = mapToItem(null, mouse.x, mouse.y).x
            pressWidth = sidebar.width
            sidebar.resizing = true
        }
        onPositionChanged: mouse => {
            if (pressed)
                sidebar.resizeTo(pressWidth + mapToItem(null, mouse.x, mouse.y).x - pressX)
        }
        onReleased: sidebar.resizing = false
        onCanceled: sidebar.resizing = false
    }

}
