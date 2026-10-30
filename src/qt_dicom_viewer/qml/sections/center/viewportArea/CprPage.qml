pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../../../theme"

Item {
    id: page
    objectName: "cprPage"
    required property var controller
    property bool anonymousExport: false
    function activeExportItem() {
        if (!controller) return null
        if (controller.exportScope === "combined") return page
        for (let i = 0; i < cells.count; i++) {
            const cell = cells.itemAt(i)
            if (cell.modelData.viewportRole === controller.exportScope) return cell.imageItem
        }
        return null
    }
    GridLayout {
        anchors.fill: parent
        rowSpacing: 4
        columnSpacing: 4
        uniformCellWidths: true
        uniformCellHeights: true
        Repeater {
            id: cells
            model: page.controller?.cprViews ?? []
            delegate: Rectangle {
                id: cell
                required property int index
                required property var modelData
                property alias imageItem: viewport
                readonly property bool focused: (page.controller?.focusedViewportId ?? "") !== ""
                visible: !focused || page.controller?.focusedViewportId === modelData.viewportId
                Layout.row: focused ? 0 : Math.floor(index / 2)
                Layout.column: focused ? 0 : index % 2
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumWidth: 0
                Layout.minimumHeight: 100
                color: Theme.canvasBackground
                border.color: page.controller?.activeViewport === modelData ? Theme.primaryColor : Theme.controlBorder
                border.width: 1
                Item {
                    anchors.fill: parent
                    anchors.margins: 2
                    Item {
                        anchors.fill: parent
                        Viewport {
                            id: viewport
                            objectName: "cprViewport-" + cell.modelData.viewportRole
                            anchors.fill: parent
                            viewportController: cell.modelData
                            twoDViewMode: cell.index < 2 && !cell.modelData.historicalPlane
                                ? page.controller?.referencePlanes[cell.index] ?? "axial" : ""
                            hasTabs: true
                            anonymousExport: page.anonymousExport
                            multiViewport: !cell.focused
                            overlayStatusText: cell.modelData.historicalPlane ? "HISTORICAL PLANE"
                                : cell.index < 2 ? ""
                                : page.controller?.drawing && cell.modelData.imageRows > 0 ? "PREVIOUS RESULT"
                                : page.controller?.busy ? "UPDATING"
                                : !page.controller?.ready ? "NO RESULT" : ""
                            TapHandler {
                                onPressedChanged: if (pressed) page.controller?.activateViewport(cell.modelData.viewportId)
                            }
                        }
                        // Reuse the 2D plane selector outside the exported image.
                        // Neither reference plane has a primary/secondary role.
                        TwoDViewSelector {
                            objectName: "cprPlane-" + cell.index
                            readonly property var overlay: viewport.cornerOverlay
                            x: 10; y: 10; z: 40
                            visible: cell.index < 2 && !cell.modelData.historicalPlane && !page.anonymousExport
                            width: Math.min(overlay?.selectorWidth ?? 70, Math.max(0, parent.width - x - 4))
                            height: overlay?.selectorHeight ?? 24
                            font.pixelSize: overlay?.textPixelSize ?? 12
                            mode: viewport.twoDViewMode
                            model: [
                                {value: "axial", label: qsTrId("layout.axialReconstruction"), group: ""},
                                {value: "coronal", label: qsTrId("layout.coronalReconstruction"), group: ""},
                                {value: "sagittal", label: qsTrId("layout.sagittalReconstruction"), group: ""}
                            ]
                            onActivationRequested: page.controller?.activateViewport(cell.modelData.viewportId)
                            onModeSelected: mode => page.controller?.setReferencePlane(cell.index, mode)
                        }
                    }
                }
            }
        }
    }
}
