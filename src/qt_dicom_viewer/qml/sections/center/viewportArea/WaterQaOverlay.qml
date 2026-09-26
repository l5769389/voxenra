pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Shapes
import "../../../theme"

Item {
    id: overlay
    objectName: "waterQaOverlay"
    required property var controller
    readonly property var settingsController: controller?.settingsController ?? null
    readonly property int decimalPlaces: settingsController?.values.measurement.decimalPlaces ?? 2
    function metric(value) {
        return settingsController ? settingsController.formatMeasurement(value, decimalPlaces) : "—"
    }
    required property var coordinateMapper
    required property var transformState
    property int mappingRevision: 0
    function refreshMapping() { mappingRevision += 1 }
    // Mirror bindings and QQuickItem transforms settle in the same event turn.
    // Remap afterwards as well, so mapToItem cannot retain the previous mirror.
    onTransformStateChanged: Qt.callLater(refreshMapping)

    function mapPoint(column, row) {
        // Reading this dependency keeps mapped geometry current after pan,
        // rotation, zoom, physical pixel scaling and either mirror operation.
        if (overlay.mappingRevision < 0 || !overlay.transformState)
            return Qt.point(0, 0)
        return overlay.coordinateMapper.mapDicomPixelToItem(overlay, column, row)
    }

    Repeater {
        model: overlay.controller ? overlay.controller.roiItems : []
        delegate: Item {
            id: roi
            required property var modelData
            objectName: "waterQaVoi-" + modelData.key
            anchors.fill: parent
            readonly property point center: overlay.mapPoint(modelData.column, modelData.row)
            readonly property point u: overlay.mapPoint(modelData.column + modelData.radiusColumn, modelData.row)
            readonly property point v: overlay.mapPoint(modelData.column, modelData.row + modelData.radiusRow)
            readonly property real screenRadius: Math.hypot(u.x-center.x, u.y-center.y)
            readonly property string outlinePath: {
                const point = (a, b) => (center.x+a*(u.x-center.x)+b*(v.x-center.x)) + " "
                    + (center.y+a*(u.y-center.y)+b*(v.y-center.y))
                const k = 0.5522847498
                return "M " + point(1, 0)
                    + " C " + point(1, k) + " " + point(k, 1) + " " + point(0, 1)
                    + " C " + point(-k, 1) + " " + point(-1, k) + " " + point(-1, 0)
                    + " C " + point(-1, -k) + " " + point(-k, -1) + " " + point(0, -1)
                    + " C " + point(k, -1) + " " + point(1, -k) + " " + point(1, 0) + " Z"
            }
            Shape {
                anchors.fill: parent
                ShapePath {
                    strokeColor: roi.modelData.color
                    strokeWidth: roi.modelData.editing || roi.modelData.hovered || roi.modelData.selected ? 2.5 : 1.5
                    fillColor: roi.modelData.editing || roi.modelData.hovered
                        ? Qt.rgba(1, 1, 1, 0.08) : "transparent"
                    PathSvg { path: roi.outlinePath }
                }
            }
            Rectangle {
                width: label.implicitWidth + 12
                height: label.implicitHeight + 8
                x: Math.max(4, Math.min(overlay.width-width-4, roi.center.x-width/2))
                y: Math.max(4, Math.min(overlay.height-height-4, roi.center.y+roi.screenRadius+4))
                radius: 4
                color: Theme.qaCardBackground
                border.color: roi.modelData.color
                border.width: 1
                Text {
                    id: label
                    objectName: "waterQaVoiLabel-" + roi.modelData.key
                    anchors.centerIn: parent
                    text: roi.modelData.editing ? I18n.format(qsTrId("qa.editing"), {label: roi.modelData.label})
                        : roi.modelData.label + "  " + overlay.metric(roi.modelData.meanHu) + " HU\n"
                            + "SD  " + overlay.metric(roi.modelData.stdHu) + " HU"
                    color: Theme.overlayText
                    font.pixelSize: 10
                    lineHeight: 1.15
                }
            }
        }
    }
}
