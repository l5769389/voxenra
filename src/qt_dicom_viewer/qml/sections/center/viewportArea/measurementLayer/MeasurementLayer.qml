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

    // 测量坐标属于无限延伸的图像坐标系，可以绘制到图像矩形之外。
    // 最外层 ImageCanvas 仍会将最终内容限制在整个视口画布内。
    clip: false

    function labelHitRegions(targetItem) {
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
        model: measurementLayer.measurementController
            ? measurementLayer.measurementController.measurementItems
            : []

        delegate: MeasurementItem {
            required property var modelData
            isDraft: false
            selectedDraft: !modelData.locked && isSelected && measurementLayer.measurementController?.selectedMeasurementState === "draft"
            preferences: measurementLayer.preferences
            settingsController: measurementLayer.measurementController?.settingsController ?? null
            showRoiMetrics: measurementLayer.showRoiMetrics
            roiLabel: measurementLayer.roiLabel
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
        isSelected: false
        measurement: measurementLayer.measurementController
            ? measurementLayer.measurementController.activeTransaction
            : ({})
        coordinateMapper: measurementLayer.coordinateMapper
        transformState: measurementLayer.transformState
        z: 3
    }

    Text {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 32
        text: measurementLayer.measurementController?.instruction ?? ""
        visible: text.length > 0
        color: Theme.measurementSelected
        font.pixelSize: 13
        style: Text.Outline
        styleColor: Theme.overlayOutline
    }
}
