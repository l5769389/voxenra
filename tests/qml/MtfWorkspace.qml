pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../../src/qt_dicom_viewer/qml/sections" as Sections
import "../../src/qt_dicom_viewer/qml/sections/center/viewportArea" as Viewports

Rectangle {
    id: root
    required property var viewportController
    required property var toolController
    color: "#060c12"
    RowLayout {
        anchors.fill: parent
        anchors.margins: 8
        spacing: 10
        Viewports.Viewport {
            id: viewport
            objectName: "testViewport"
            Layout.fillWidth: true
            Layout.fillHeight: true
            viewportController: root.viewportController
            hasTabs: true
        }
        Sections.RightPanel {
            exportItem: viewport
            Layout.preferredWidth: root.width < 900 ? 264 : 320
            Layout.fillHeight: true
            viewportController: root.viewportController
            toolController: root.toolController
            toolVisible: true
        }
    }
}
