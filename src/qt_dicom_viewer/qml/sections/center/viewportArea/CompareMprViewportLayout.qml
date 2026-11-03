pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../../../components" as Components
import "../../../theme"

Item {
    id: root
    required property var tabController
    readonly property string pair: tabController?.pairPlane ?? ""
    readonly property var planes: ["axial", "coronal", "sagittal"]
    function activeExportItem() {
        for (let i = 0; i < views.count; ++i) {
            const cell = views.itemAt(i)
            if (cell?.modelData === tabController?.activeViewport) return cell.exportItem
        }
        return null
    }
    RowLayout {
        id: links
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        height: 30
        spacing: 6
        Text { text: qsTrId("compare.mpr.linking"); color: Theme.textSecondary; font.pixelSize: 11 }
        Repeater {
            model: [{key:"position", icon:"nav-view-mpr", label:qsTrId("compare.mpr.position")},
                    {key:"rotation", icon:"rotate-3d", label:qsTrId("compare.mpr.rotation")},
                    {key:"window", icon:"window", label:qsTrId("compare.mpr.window")},
                    {key:"zoom", icon:"zoom", label:qsTrId("compare.mpr.zoom")}]
            delegate: Components.AppButton {
                id: linkButton
                required property var modelData
                objectName: "compareMprStatus-" + modelData.key
                Layout.preferredWidth: 28
                Layout.preferredHeight: 26
                minimumButtonWidth: 28
                compact: true
                iconName: modelData.icon
                iconSize: 17
                checkable: true
                checked: root.tabController?.linkStates[modelData.key] ?? false
                enabled: (root.tabController?.ready ?? false)
                    && (modelData.key !== "window" || root.tabController.windowLinkAvailable)
                Accessible.name: modelData.label + " · " + qsTrId(checked ? "compare.mpr.linkOn" : "compare.mpr.linkOff")
                onClicked: root.tabController.setLink(modelData.key, checked)
                Components.AppToolTip { requested: linkButton.hovered; text: linkButton.Accessible.name }
            }
        }
        Item { Layout.fillWidth: true }
    }
    GridLayout {
        anchors.top: links.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        rows: root.pair ? 2 : 4
        columns: root.pair ? 2 : 3
        uniformCellWidths: true
        rowSpacing: 4
        columnSpacing: 4
        Repeater {
            model: root.tabController ? 2 : 0
            delegate: Text {
                id: heading
                required property int index
                readonly property string role: index === 0 ? "a" : "b"
                readonly property bool active: root.tabController?.activeViewport?.viewportRole === role
                objectName: "compareMprHeading-" + role
                Layout.row: root.pair ? 0 : index * 2
                Layout.column: root.pair ? index : 0
                Layout.columnSpan: root.pair ? 1 : 3
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                Layout.leftMargin: 6
                Layout.preferredHeight: 24
                Layout.minimumHeight: 24
                Layout.maximumHeight: 24
                text: (index === 0 ? "A · " : "B · ") + (root.tabController?.groupLabels[index] ?? "")
                textFormat: Text.PlainText
                color: active ? Theme.primaryColor : Theme.textSecondary
                font.bold: active
                font.pixelSize: 11
                verticalAlignment: Text.AlignVCenter
                elide: Text.ElideRight
                HoverHandler { id: headingHover }
                Components.AppToolTip { requested: headingHover.hovered && heading.truncated; text: heading.text }
            }
        }
        Repeater {
            id: views
            model: root.tabController?.comparisonViews ?? []
            delegate: Item {
                id: cell
                required property var modelData
                readonly property alias exportItem: canvas
                readonly property bool active: modelData === root.tabController?.activeViewport
                readonly property int groupIndex: modelData.viewportRole === "a" ? 0 : 1
                objectName: "compareMprCell-" + modelData.viewportId
                visible: !root.pair || modelData.viewportType === root.pair
                Layout.row: root.pair ? 1 : groupIndex * 2 + 1
                Layout.column: root.pair ? groupIndex : root.planes.indexOf(modelData.viewportType)
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumWidth: 0
                Layout.minimumHeight: 0
                Viewport {
                    id: canvas
                    objectName: "imageViewport-" + cell.modelData.viewportId
                    anchors.fill: parent
                    anchors.margins: frame.contentInset
                    viewportController: cell.modelData
                    hasTabs: true
                    multiViewport: true
                    outsideImageRange: root.tabController?.outOfRangeViewports[cell.modelData.viewportId] ?? false
                    onReturnToVolumeRequested: root.tabController.recenterSeries(cell.modelData.viewportId)
                    onImageFitScaleChanged: root.tabController?.updateViewportFitScale(cell.modelData.viewportId, imageFitScale)
                    Component.onCompleted: root.tabController?.updateViewportFitScale(cell.modelData.viewportId, imageFitScale)
                }
                HoverHandler { id: hover }
                ViewportFrame {
                    id: frame
                    objectName: "viewportFrame-" + cell.modelData.viewportId
                    anchors.fill: parent
                    active: cell.active
                    hovered: hover.hovered
                    z: 30
                }
                TapHandler {
                    onPressedChanged: if (pressed) root.tabController.activateViewport(cell.modelData.viewportId)
                    onDoubleTapped: {
                        if (canvas.doubleClickEditsPoints) return
                        root.tabController.togglePair(cell.modelData.viewportId)
                    }
                }
            }
        }
    }
}
