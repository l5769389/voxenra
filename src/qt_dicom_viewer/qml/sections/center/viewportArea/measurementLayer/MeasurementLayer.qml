pragma ComponentBehavior: Bound

import QtQuick
import "../../../../theme"

Item {
    id: measurementLayer

    required property var measurementController
    required property var coordinateMapper
    required property var transformState
    property var preferences: ({})
    property bool showRoiMetrics: true
    property string roiLabel: ""
    property var avoidanceRegions: []
    property var reservedRegions: []
    property real instructionBottomMargin: 32
    readonly property var instructionRegions: instructionText.visible
        ? [{x: instructionText.x, y: instructionText.y, width: instructionText.width, height: instructionText.height}] : []
    property int labelLayoutRevision: 0
    readonly property var measurementBounds: {
        if (!transformState || !coordinateMapper) return []
        const bounds = []
        const items = measurementController?.measurementItems ?? []
        for (const item of items) {
            const points = (item.renderPoints ?? item.points ?? []).map(p =>
                coordinateMapper.mapDicomPixelToItem(measurementLayer, p.column, p.row))
            if (points.length < 2) continue
            const x = Math.min(...points.map(p => p.x)) - 6
            const y = Math.min(...points.map(p => p.y)) - 6
            bounds.push({measurementId: item.measurementId, x, y, width: Math.max(...points.map(p => p.x)) - x + 6,
                height: Math.max(...points.map(p => p.y)) - y + 6})
        }
        return bounds
    }

    function labelObstacles(measurementId, beforeIndex) {
        // One-way label dependencies avoid layout loops: later labels yield to
        // earlier ones. Cache outline bounds once per geometry/transform change.
        const revision = labelLayoutRevision
        const regions = avoidanceRegions.concat(measurementBounds.filter(r => r.measurementId !== measurementId))
        for (let index = 0; index < Math.min(beforeIndex, measurements.count); ++index) {
            const label = measurements.itemAt(index)?.labelItem
            if (label?.visible)
                regions.push({x: label.x - 4, y: label.y - 4, width: label.width + 8, height: label.height + 8})
        }
        return regions
    }

    // 测量坐标属于无限延伸的图像坐标系，可以绘制到图像矩形之外。
    // 最外层 ImageCanvas 仍会将最终内容限制在整个视口画布内。
    clip: false

    function labelHitRegions(targetItem) {
        const revision = labelLayoutRevision
        const regions = []
        for (let index = 0; index < measurements.count; ++index) {
            const item = measurements.itemAt(index) as MeasurementItem
            const region = item ? item.labelHitRegion(targetItem) : null
            if (region)
                regions.push(region)
        }
        return regions
    }

    Repeater {
        id: measurements
        onItemAdded: measurementLayer.labelLayoutRevision++
        onItemRemoved: measurementLayer.labelLayoutRevision++
        model: measurementLayer.measurementController
            ? measurementLayer.measurementController.measurementItems
            : []

        delegate: MeasurementItem {
            required property int index
            required property var modelData
            isDraft: false
            selectedDraft: !modelData.locked && isSelected && measurementLayer.measurementController?.selectedMeasurementState === "draft"
            preferences: measurementLayer.preferences
            settingsController: measurementLayer.measurementController?.settingsController ?? null
            showRoiMetrics: measurementLayer.showRoiMetrics
            roiLabel: measurementLayer.roiLabel
            reservedRegions: measurementLayer.reservedRegions.concat(measurementLayer.instructionRegions)
            avoidanceRegions: measurementLayer.labelObstacles(modelData.measurementId, index)
            isSelected: measurementLayer.measurementController
                ? modelData?.measurementId
                    === measurementLayer.measurementController.selectedMeasurementId
                : false
            width: measurementLayer.width
            height: measurementLayer.height
            measurement: modelData
            coordinateMapper: measurementLayer.coordinateMapper
            transformState: measurementLayer.transformState
        }
    }

    MeasurementItem {
        width: measurementLayer.width
        height: measurementLayer.height

        visible: measurementLayer.measurementController
                 && Object.keys(
                     measurementLayer.measurementController.activeTransaction ?? ({})
                 ).length > 0
        isDraft: true
        preferences: measurementLayer.preferences
        settingsController: measurementLayer.measurementController?.settingsController ?? null
        showRoiMetrics: measurementLayer.showRoiMetrics
        roiLabel: measurementLayer.roiLabel
        reservedRegions: measurementLayer.reservedRegions.concat(measurementLayer.instructionRegions)
        avoidanceRegions: measurementLayer.labelObstacles(measurement?.measurementId, measurements.count)
        isSelected: false
        measurement: measurementLayer.measurementController
            ? measurementLayer.measurementController.activeTransaction
            : ({})
        coordinateMapper: measurementLayer.coordinateMapper
        transformState: measurementLayer.transformState
        z: 3
    }

    Text {
        id: instructionText
        objectName: "measurementInstruction"
        width: Math.min(implicitWidth, Math.max(0, parent.width - 32))
        wrapMode: Text.Wrap
        horizontalAlignment: Text.AlignHCenter
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: measurementLayer.instructionBottomMargin
        text: measurementLayer.measurementController?.instruction ?? ""
        visible: text.length > 0
        color: Theme.drawingLineColor(measurementLayer.preferences.measurement ?? ({}), true)
        font.pixelSize: 13
        style: Text.Outline
        styleColor: Theme.overlayOutline
    }
}
