pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../../../components" as Components
import "../../../theme"
Item {
    id: root
    required property var tabController
    readonly property var controller: tabController?.twoDLayout ?? null
    readonly property string focusedId: tabController?.focusedViewportId ?? ""
    function activeExportItem() {
        for (let i = 0; i < cells.count; ++i) {
            const cell = cells.itemAt(i)
            if (cell?.modelData.viewport === tabController?.activeViewport) return cell.exportItem
        }
        return null
    }
    GridLayout {
        anchors.fill: parent
        columns: root.controller?.columns ?? 1
        rows: root.controller?.rows ?? 1
        uniformCellWidths: true; uniformCellHeights: true
        columnSpacing: 3; rowSpacing: 3
        Repeater {
            id: cells
            model: root.controller?.cells ?? []
            delegate: Item {
                id: cell
                required property var modelData
                readonly property var view: modelData.viewport ?? null
                readonly property bool active: root.controller?.activeCell === modelData.index
                readonly property var exportItem: imageLoader.item
                objectName: "twoDCell-" + modelData.index
                visible: root.focusedId === "" || root.focusedId === view?.viewportId
                Layout.fillWidth: true; Layout.fillHeight: true
                Layout.minimumWidth: 0; Layout.minimumHeight: 0
                Layout.row: root.focusedId ? 0 : modelData.row
                Layout.column: root.focusedId ? 0 : modelData.column
                Layout.rowSpan: root.focusedId ? root.controller.rows : modelData.rowSpan
                Layout.columnSpan: root.focusedId ? root.controller.columns : modelData.columnSpan
                clip: true
                Rectangle {
                    id: surface
                    anchors.top: parent.top; anchors.bottom: parent.bottom
                    anchors.left: parent.left; anchors.right: slider.visible ? slider.left : parent.right
                    color: Theme.canvasBackground
                    Loader {
                        id: imageLoader
                        anchors.fill: parent; anchors.margins: frame.contentInset
                        active: !!cell.view
                        sourceComponent: Component {
                            Viewport {
                                objectName: "imageViewport-" + cell.view.viewportId
                                viewportController: cell.view
                                twoDViewMode: cell.modelData.mode
                                hasTabs: true
                                multiViewport: cells.count > 1 && !root.focusedId
                            }
                        }
                    }
                    // Keep interactive controls outside the image's export subtree.
                    TwoDViewSelector {
                        id: plane
                        objectName: "twoDPlane-" + cell.modelData.index
                        readonly property var overlay: imageLoader.item?.cornerOverlay ?? null
                        x: imageLoader.x + 10
                        y: imageLoader.y + 10
                        z: 40
                        visible: !!cell.view
                        width: Math.min(overlay?.selectorWidth ?? 70, Math.max(0, surface.width - x - 4))
                        height: overlay?.selectorHeight ?? 24
                        font.pixelSize: overlay?.textPixelSize ?? 12
                        mode: cell.modelData.mode
                        seriesLabel: cell.view?.hideSensitiveInfo ? "" : cell.modelData.label
                        onActivationRequested: root.controller.activateCell(cell.modelData.index)
                        onModeSelected: mode => root.controller.setMode(cell.modelData.index, mode)
                    }
                    Item {
                        // Hover help is outside the exported image and does not intercept image gestures.
                        objectName: "twoDPositionHelp-" + cell.modelData.index
                        readonly property var overlay: plane.overlay
                        x: imageLoader.x + (overlay?.x ?? 0) + (overlay?.positionRect.x ?? 0)
                        y: imageLoader.y + (overlay?.y ?? 0) + (overlay?.positionRect.y ?? 0)
                        width: overlay?.positionRect.width ?? 0
                        height: overlay?.positionRect.height ?? 0
                        visible: !!overlay && overlay.visible && overlay.inlineViewPosition
                        z: 40
                        HoverHandler { id: positionHover }
                        Components.AppToolTip {
                            objectName: "twoDPositionToolTip-" + cell.modelData.index
                            visible: positionHover.hovered && !plane.popup.visible
                            text: qsTrId("layout.positionHint")
                        }
                    }
                    Text {
                        anchors.fill: parent; anchors.margins: 12
                        visible: !cell.view
                        text: qsTrId("layout.dropHere")
                        horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
                        wrapMode: Text.Wrap
                        color: Theme.textMuted; font.pixelSize: 12
                    }
                    ViewportFrame {
                        id: frame
                        objectName: "viewportFrame-" + (cell.view?.viewportId ?? "empty")
                        anchors.fill: parent
                        active: cell.active
                        hovered: hover.hovered || dropArea.containsDrag
                        z: 30
                    }
                    HoverHandler { id: hover }
                    TapHandler {
                        onPressedChanged: if (pressed) root.controller.activateCell(cell.modelData.index)
                        onDoubleTapped: {
                            const p = plane.mapFromItem(surface, point.position)
                            if (plane.visible && plane.contains(p)) return
                            if (cell.view && cells.count > 1)
                                root.tabController.focusSingleViewport(root.focusedId ? "" : cell.view.viewportId)
                        }
                    }
                }
                SliceSlider {
                    id: slider
                    anchors.top: surface.top; anchors.bottom: parent.bottom; anchors.right: parent.right
                    viewportController: cell.view
                    allowOrthogonal: true
                }
                DropArea {
                    id: dropArea
                    objectName: "twoDSeriesDrop-" + cell.modelData.index
                    anchors.fill: parent
                    keys: ["application/x-voxenra-series"]
                    onEntered: drag => drag.accept(Qt.CopyAction)
                    onDropped: drop => {
                        const uid = drop.source?.seriesUid ?? drop.getDataAsString("application/x-voxenra-series")
                        if (root.controller.loadSeries(cell.modelData.index, uid))
                            drop.accept(Qt.CopyAction)
                    }
                }
                Rectangle {
                    anchors.fill: parent
                    visible: dropArea.containsDrag
                    color: Theme.selectionBackground; opacity: 0.25
                    border.width: 2; border.color: Theme.primaryColor
                }
            }
        }
    }
}
