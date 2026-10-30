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
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 2
                    spacing: 2
                    Item {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
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
                    Text {
                        objectName: "cprStatus-" + cell.modelData.viewportRole
                        Layout.fillWidth: true
                        Layout.leftMargin: 6
                        Layout.bottomMargin: 3
                        // Keep reference image bounds stable when modes change.
                        text: cell.modelData.historicalPlane ? cell.modelData.historicalDescription
                            : cell.index < 2 ? qsTrId(cell.modelData.cprDrawing ? "cpr.referenceDrawHint"
                            : cell.modelData.cprEditing ? "cpr.referenceEditHint"
                            : page.controller?.drawing ? "cpr.referencePausedHint" : "cpr.referenceViewHint")
                            : page.controller?.drawing ? qsTrId(cell.modelData.imageRows > 0 ? "cpr.previousResult" : "cpr.empty")
                            : page.controller?.busy ? qsTrId("cpr.computing")
                            : !page.controller?.ready ? qsTrId("cpr.empty")
                            : qsTrId("cpr.distance").arg((page.controller?.positionMm ?? 0).toFixed(1)).arg((page.controller?.totalLength ?? 0).toFixed(1))
                        color: Theme.overlayText
                        font.pixelSize: 11
                        elide: Text.ElideRight
                    }
                }
            }
        }
    }
}
