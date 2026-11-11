pragma ComponentBehavior: Bound
import QtQuick
import "../../../theme"
import QtQuick.Shapes

Item {
    id: overlay
    objectName: "mprVoiOverlay"
    required property var items
    required property var coordinateMapper
    required property var transformState
    property int mappingRevision: 0
    function refreshMapping() { mappingRevision += 1 }
    onTransformStateChanged: Qt.callLater(refreshMapping)
    function mapPoint(p) {
        if (mappingRevision < 0 || !transformState) return Qt.point(0, 0)
        return coordinateMapper.mapDicomPixelToItem(overlay, p[0], p[1])
    }
    Repeater {
        // Keep scene-graph objects alive while the same regions move.
        model: overlay.items.length
        delegate: Item {
            id: roi
            required property int index
            readonly property var modelData: overlay.items[index]
            anchors.fill: parent
            readonly property var points: modelData.polygon.map(p => overlay.mapPoint(p))
            Shape {
                anchors.fill: parent
                ShapePath {
                    strokeColor: roi.modelData.color
                    strokeWidth: roi.modelData.selected ? 2 : 1
                    fillColor: roi.modelData.fill ? Qt.alpha(roi.modelData.color, 0.08) : "transparent"
                    PathPolyline {
                        path: roi.points.length < 3 ? [] : roi.points.concat([roi.points[0]])
                    }
                }
            }
            Repeater {
                model: roi.modelData.selected ? roi.modelData.handles.map(p => overlay.mapPoint(p)) : []
                delegate: Rectangle {
                    required property var modelData
                    width: 8; height: 8; radius: 4
                    x: modelData.x - 4; y: modelData.y - 4
                    color: roi.modelData.color
                    border.color: Theme.imageHandleBorder
                }
            }
        }
    }
}
