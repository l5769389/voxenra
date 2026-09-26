pragma ComponentBehavior: Bound

import QtQuick
import "CursorPolicy.js" as CursorPolicy
import QtQuick.Controls.Basic as Basic
import QtQuick.Layouts
import "../../../components" as Components
import "../../../theme"

Item {
    id: montageRoot

    property bool anonymousExport: false
    required property var viewportController
    readonly property var metadataItems: [
        {
            "label": qsTrId("text.0028"),
            "value": montageRoot.viewportController?.patientName
        },
        {
            "label": qsTrId("text.0993"),
            "value": montageRoot.viewportController?.patientSummary
        },
        {
            "label": qsTrId("text.0994"),
            "value": montageRoot.viewportController?.descriptionSummary
        },
        {
            "label": montageRoot.viewportController?.isMrViewport ? qsTrId("mr.parameters") : qsTrId("text.0995"),
            "value": montageRoot.viewportController?.scanParameters
        },
        {
            "label": qsTrId("text.0996"),
            "value": montageRoot.viewportController?.acquisitionDateTime
        },
        {
            "label": qsTrId("text.0030"),
            "value": montageRoot.viewportController?.sliceThickness
        }
    ]

    function formatNumber(value) {
        if (!Number.isFinite(value))
            return "—"
        const scale = montageRoot.viewportController?.isMrViewport ? 1000 : 100
        const rounded = Math.round(value * scale) / scale
        return String(rounded)
    }

    function setColumnCount(count) {
        if (!montageRoot.viewportController) return
        const oldColumns = Math.max(1, montageRoot.viewportController?.columnCount)
        const oldRow = Math.max(0, Math.floor(montageGrid.contentY / montageGrid.cellHeight))
        const anchorIndex = Math.min(
            montageRoot.viewportController?.sliceCount - 1,
            oldRow * oldColumns
        )
        montageRoot.viewportController?.setColumnCount(count)
        Qt.callLater(function() {
            if (anchorIndex >= 0)
                montageGrid.positionViewAtIndex(anchorIndex, GridView.Beginning)
            montageGrid.updateVisibleRange()
        })
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            Layout.fillWidth: true
            objectName: "montageHeader"
            Layout.preferredHeight: headerContents.implicitHeight + 24
            color: Theme.panelBackgroundSoft

            ColumnLayout {
                id: headerContents
                anchors.fill: parent
                anchors.margins: 12
                spacing: 10

                GridLayout {
                    Layout.fillWidth: true
                    columns: montageRoot.width < 560 ? 1 : 2
                    columnSpacing: 12
                    rowSpacing: 8

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 4

                        Text {
                            text: qsTrId("text.0699")
                            color: Theme.textPrimary
                            font.pixelSize: 15
                            font.weight: Font.DemiBold
                        }

                        Text {
                            Layout.fillWidth: true
                            text: I18n.format(qsTrId("montage.summary"), {count: montageRoot.viewportController?.sliceCount,
                                width: montageRoot.viewportController?.hasWindow ? montageRoot.formatNumber(montageRoot.viewportController?.windowWidth) : "—",
                                center: montageRoot.viewportController?.hasWindow ? montageRoot.formatNumber(montageRoot.viewportController?.windowCenter) : "—",
                                modality: montageRoot.viewportController?.modality || "—"})
                            color: Theme.textMuted
                            font.pixelSize: 11
                            elide: Text.ElideRight
                        }
                    }

                    RowLayout {
                        Layout.alignment: Qt.AlignRight | Qt.AlignVCenter
                        spacing: 4
                        Repeater {
                            model: [2, 3, 4, 5, 6]

                            delegate: Components.AppButton {
                                required property int modelData

                                compact: true
                                minimumButtonWidth: 32
                                Accessible.name: I18n.format(qsTrId("montage.columns"), {count: modelData})
                                text: String(modelData)
                                checked: modelData
                                    === montageRoot.viewportController?.columnCount
                                onClicked: montageRoot.setColumnCount(modelData)
                            }
                        }
                        Components.AppButton {
                            objectName: "montageDetailsToggle"
                            compact: true
                            minimumButtonWidth: 32
                            Layout.preferredWidth: 32
                            iconName: montageRoot.viewportController?.detailsExpanded ? "chevron-up" : "chevron-down"
                            textColor: Theme.textMuted
                            normalColor: "transparent"
                            Accessible.name: montageRoot.viewportController?.detailsExpanded ? qsTrId("text.0999") : qsTrId("text.1000")
                            onClicked: montageRoot.viewportController?.toggleDetails()
                            Components.AppToolTip {
                                visible: parent.hovered
                                delay: 500
                                text: parent.Accessible.name
                            }
                        }
                    }
                }

                GridLayout {
                    objectName: "montageDetails"
                    opacity: montageRoot.anonymousExport ? 0 : 1
                    visible: montageRoot.viewportController?.detailsExpanded ?? false
                    Layout.fillWidth: true
                    columns: montageRoot.width < 560 ? 2 : 3
                    columnSpacing: 24
                    rowSpacing: 8

                    Repeater {
                        model: montageRoot.metadataItems

                        delegate: ColumnLayout {
                            id: metadataEntry
                            required property var modelData

                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            spacing: 2

                            Text {
                                Layout.fillWidth: true
                                text: metadataEntry.modelData.label
                                color: Theme.textSubtle
                                font.pixelSize: 9
                                elide: Text.ElideRight
                            }

                            Text {
                                Layout.fillWidth: true
                                text: metadataEntry.modelData.value || "—"
                                color: Theme.textSecondary
                                font.pixelSize: 11
                                elide: Text.ElideRight
                            }
                        }
                    }
                }
            }

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: 1
                color: Theme.dividerColor
            }
        }

        Rectangle {
            id: gridViewport
            property Item hoveredTile: null
            property Item draggedTile: null
            readonly property Item cursorTile: draggedTile || hoveredTile
            readonly property point cursorPosition: draggedTile
                ? draggedTile.mapToItem(gridViewport, draggedTile.dragPosition)
                : gridHover.point.position

            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            color: Theme.workspaceBackground

            GridView {
                id: montageGrid
                objectName: "montageGrid"

                anchors.fill: parent
                clip: true
                interactive: false
                boundsBehavior: Flickable.StopAtBounds
                model: montageRoot.viewportController?.sliceModel ?? null
                readonly property real gutter: 8
                cellWidth: width / Math.max(
                    1,
                    montageRoot.viewportController?.columnCount ?? 4
                )
                cellHeight: Math.max(
                    96,
                    (cellWidth - gutter)
                        / (montageRoot.viewportController?.imageAspectRatio ?? 1)
                        + gutter
                )

                function updateVisibleRange() {
                    if (!montageRoot.viewportController || count <= 0 || cellHeight <= 0 || height <= 0)
                        return
                    const columns = montageRoot.viewportController?.columnCount
                    const firstRow = Math.max(
                        0,
                        Math.floor(contentY / cellHeight)
                    )
                    const lastRow = Math.max(
                        firstRow,
                        Math.floor((contentY + height - 1) / cellHeight)
                    )
                    const first = Math.min(count - 1, firstRow * columns)
                    const last = Math.min(
                        count - 1,
                        (lastRow + 1) * columns - 1
                    )
                    montageRoot.viewportController?.setVisibleRange(first, last)
                }

                onContentYChanged: updateVisibleRange()
                onHeightChanged: Qt.callLater(updateVisibleRange)
                onWidthChanged: Qt.callLater(updateVisibleRange)
                onCellHeightChanged: Qt.callLater(updateVisibleRange)
                onCountChanged: Qt.callLater(updateVisibleRange)
                Component.onCompleted: Qt.callLater(updateVisibleRange)

                Basic.ScrollBar.vertical: Basic.ScrollBar {
                    policy: Basic.ScrollBar.AlwaysOn
                }

                delegate: Rectangle {
                id: tile

                required property int sliceIndex
                required property string imageSource
                required property string loadState
                required property string errorText

                width: montageGrid.cellWidth - montageGrid.gutter
                height: montageGrid.cellHeight - montageGrid.gutter
                x: montageGrid.gutter / 2
                y: montageGrid.gutter / 2
                clip: true
                color: Theme.canvasBackground
                border.width: tileHover.hovered ? 1 : 0
                border.color: Theme.selectionBorder
                radius: 4

                Item {
                    id: imageScene

                    width: parent.width
                    height: parent.height
                    x: (montageRoot.viewportController?.panX ?? 0) * parent.width
                    y: (montageRoot.viewportController?.panY ?? 0) * parent.height
                    transformOrigin: Item.Center
                    scale: montageRoot.viewportController?.zoom ?? 1
                    rotation: montageRoot.viewportController?.rotationDegrees ?? 0

                    Item {
                        id: flipLayer
                        anchors.fill: parent

                        transform: Scale {
                            origin.x: flipLayer.width / 2
                            origin.y: flipLayer.height / 2
                            xScale: montageRoot.viewportController?.horizontalFlip
                                ? -1 : 1
                            yScale: montageRoot.viewportController?.verticalFlip
                                ? -1 : 1
                        }

                        Image {
                            objectName: "montageSliceImage-" + tile.sliceIndex
                            anchors.fill: parent
                            source: tile.imageSource
                            fillMode: Image.PreserveAspectFit
                            cache: false
                            smooth: true
                        }
                    }
                }

                Basic.BusyIndicator {
                    anchors.centerIn: parent
                    running: tile.loadState === "loading"
                    visible: running
                    width: 28
                    height: 28
                }

                Column {
                    anchors.centerIn: parent
                    spacing: 8
                    visible: tile.loadState === "error"

                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: Math.min(180, tile.width - 24)
                        text: tile.errorText || qsTrId("text.0605")
                        color: Theme.dangerColor
                        font.pixelSize: 10
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.Wrap
                    }

                    Components.AppButton {
                        id: closeButton
                        objectName: "montageClose-" + tile.sliceIndex
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: qsTrId("text.0897")
                        onClicked: montageRoot.viewportController?.closeTab()
                    }
                }

                Rectangle {
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    anchors.margins: 7
                    width: sliceLabel.implicitWidth + 12
                    height: 23
                    radius: 5
                    color: Theme.imageBadgeBackground

                    Text {
                        id: sliceLabel
                        objectName: "montageSliceLabel"
                        anchors.centerIn: parent
                        text: (tile.sliceIndex + 1) + " / "
                            + montageRoot.viewportController?.sliceCount
                        color: Theme.overlayText
                        font.pixelSize: 10
                        font.weight: Font.DemiBold
                    }
                }

                readonly property string hoverCursorKind: CursorPolicy.resolve(
                    montageRoot.viewportController?.activeInteraction ?? "", "", "", "")
                property string dragCursorKind: ""
                readonly property string cursorKind: tileDrag.active ? dragCursorKind : hoverCursorKind
                readonly property point dragPosition: tileDrag.centroid.position
                Component.onDestruction: {
                    if (gridViewport.hoveredTile === tile) gridViewport.hoveredTile = null
                    if (gridViewport.draggedTile === tile) gridViewport.draggedTile = null
                }
                HoverHandler {
                    id: tileHover
                    enabled: !closeButton.hovered
                    cursorShape: tile.cursorKind ? Qt.BlankCursor : Qt.ArrowCursor
                    onHoveredChanged: {
                        if (hovered) gridViewport.hoveredTile = tile
                        else if (gridViewport.hoveredTile === tile) gridViewport.hoveredTile = null
                    }
                }

                TapHandler {
                    enabled: !closeButton.hovered
                    acceptedButtons: Qt.LeftButton
                    onDoubleTapped: montageRoot.viewportController?.openSlice(
                        tile.sliceIndex
                    )
                }

                DragHandler {
                    id: tileDrag
                    enabled: active || !closeButton.hovered
                    cursorShape: tile.cursorKind ? Qt.BlankCursor : Qt.ArrowCursor
                    target: null
                    acceptedButtons: Qt.LeftButton
                        | Qt.RightButton
                        | Qt.MiddleButton
                    property point lastPosition: Qt.point(0, 0)

                    onActiveChanged: {
                        if (active) {
                            tile.dragCursorKind = CursorPolicy.resolveDrag(tile.hoverCursorKind, centroid.pressedButtons, false)
                            gridViewport.draggedTile = tile
                            lastPosition = centroid.position
                            montageRoot.viewportController?.beginInteraction(
                                centroid.pressPosition.x,
                                centroid.pressPosition.y,
                                centroid.pressedButtons,
                                tile.width,
                                tile.height
                            )
                        } else {
                            if (gridViewport.draggedTile === tile) gridViewport.draggedTile = null
                            montageRoot.viewportController?.endInteraction(
                                centroid.position.x,
                                centroid.position.y
                            )
                        }
                    }

                    onActiveTranslationChanged: {
                        if (!active)
                            return
                        const current = centroid.position
                        const step = Qt.point(
                            current.x - lastPosition.x,
                            current.y - lastPosition.y
                        )
                        montageRoot.viewportController?.updateInteraction(
                            centroid.pressPosition,
                            current,
                            step,
                            activeTranslation
                        )
                        lastPosition = current
                    }
                }
            }
            }

            // One cursor for the whole grid: crossing tile edges must not
            // duplicate it or clip the pointer/tool badge against a tile.
            HoverHandler { id: gridHover }
            CursorGlyph {
                objectName: "montageToolCursor"
                iconName: gridViewport.cursorTile ? gridViewport.cursorTile.cursorKind : ""
                width: 40; height: 32
                x: gridViewport.cursorPosition.x - 2
                y: gridViewport.cursorPosition.y - 2
                visible: !!iconName && (gridHover.hovered || gridViewport.draggedTile !== null)
                z: 100
            }

            // A full-size MouseArea also owns the system cursor, even with
            // NoButton and hover disabled. Only consume wheel events here so
            // the image handlers can hide it while drawing the tool cursor.
            WheelHandler {
                objectName: "montageWheelHandler"
                target: null
                orientation: Qt.Vertical
                blocking: true
                acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad

                onWheel: wheelEvent => {
                    const pixelStep = wheelEvent.pixelDelta.y !== 0
                        ? wheelEvent.pixelDelta.y
                        : wheelEvent.angleDelta.y / 120
                            * montageGrid.cellHeight * 0.65
                    const maximum = Math.max(
                        0,
                        montageGrid.contentHeight - montageGrid.height
                    )
                    montageGrid.contentY = Math.max(
                        0,
                        Math.min(maximum, montageGrid.contentY - pixelStep)
                    )
                    wheelEvent.accepted = true
                }
            }
        }
    }
}
