pragma ComponentBehavior: Bound
import QtQuick

Item {
    id: root
    objectName: "measurementItem"
    required property var measurement
    required property bool isDraft
    required property bool isSelected
    property bool selectedDraft: false
    readonly property bool draftStyle: isDraft || selectedDraft
    required property var coordinateMapper
    required property var transformState
    property var preferences: ({})
    property var settingsController: null
    property bool showRoiMetrics: true
    property string roiLabel: ""
    property var avoidanceRegions: []
    z: isSelected ? 2 : 1

    readonly property Item labelItem: (root.measurement?.type === "length" || root.measurement?.type === "arrow" || root.measurement?.type === "curve")
        ? lengthItem.labelItem
        : root.measurement?.type === "angle" ? angleItem.labelItem : roiItem.labelItem

    function labelHitRegion(targetItem) {
        if (!root.measurement || root.isDraft || !root.visible || !root.labelItem || !root.labelItem.visible)
            return null
        // 标签处于不缩放的屏幕层；与 InteractionLayer 统一坐标，不能拿图像坐标判断。
        const position = root.labelItem.parent.mapToItem(targetItem, root.labelItem.x, root.labelItem.y)
        const anchor = root.coordinateMapper.mapToDicomPixel(root.labelItem, Qt.point(0, 0))
        return {
            labelColumn: anchor.column, labelRow: anchor.row,
            measurementId: root.measurement?.measurementId,
            x: position.x, y: position.y,
            width: root.labelItem.width, height: root.labelItem.height
        }
    }

    readonly property var labelPosition: {
        if (!root.transformState || !root.coordinateMapper || !root.measurement?.labelPosition)
            return null
        const point = root.measurement.labelPosition
        return root.coordinateMapper.mapDicomPixelToItem(root, point.column, point.row)
    }

    readonly property var mappedPoints: {
        // 显式依赖所有图像变换，mapToItem 本身不会建立这些属性的绑定。
        if (!root.transformState || !root.coordinateMapper)
            return []
        return (root.measurement?.points ?? []).map(point =>
            root.coordinateMapper.mapDicomPixelToItem(root, point.column, point.row))
    }
    readonly property var renderPoints: {
        if (!root.transformState || !root.coordinateMapper) return []
        return (root.measurement?.renderPoints ?? root.measurement?.points ?? []).map(point =>
            root.coordinateMapper.mapDicomPixelToItem(root, point.column, point.row))
    }
    readonly property var corners: {
        if (!root.transformState || !root.coordinateMapper)
            return []
        const points = root.measurement?.points ?? []
        if (root.measurement?.type === "freehand")
            return root.renderPoints
        if (points.length !== 2)
            return []
        const a = points[0], b = points[1]
        return [a, {column: b.column, row: a.row}, b, {column: a.column, row: b.row}].map(point =>
            root.coordinateMapper.mapDicomPixelToItem(root, point.column, point.row))
    }

    LengthMeasurementItem {
        id: lengthItem
        anchors.fill: parent
        visible: (root.measurement?.type === "length" || root.measurement?.type === "arrow" || root.measurement?.type === "curve")
        preferences: root.preferences
        measurement: root.measurement
        labelPosition: root.labelPosition
        mappedPoints: root.mappedPoints
        renderedPoints: root.renderPoints
        isDraft: root.isDraft
        draftStyle: root.draftStyle
        isSelected: root.isSelected
    }
    AngleMeasurementItem {
        id: angleItem
        anchors.fill: parent
        visible: root.measurement?.type === "angle"
        preferences: root.preferences
        measurement: root.measurement
        labelPosition: root.labelPosition
        mappedPoints: root.mappedPoints
        isDraft: root.isDraft
        draftStyle: root.draftStyle
        isSelected: root.isSelected
    }
    RoiMeasurementItem {
        id: roiItem
        settingsController: root.settingsController
        showMetrics: root.showRoiMetrics
        shortLabel: root.roiLabel
        avoidanceRegions: root.avoidanceRegions
        anchors.fill: parent
        visible: root.measurement?.type === "rect" || root.measurement?.type === "ellipse" || root.measurement?.type === "freehand"
        preferences: root.preferences
        measurement: root.measurement
        labelPosition: root.labelPosition
        corners: root.corners
        controlPoints: root.mappedPoints
        isDraft: root.isDraft
        draftStyle: root.draftStyle
        isSelected: root.isSelected
    }
}
