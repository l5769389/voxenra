pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../../../components" as Components
import "../../../theme"

Item {
    id: page
    objectName: "cprPage"
    required property var controller
    property bool anonymousExport: false
    function activeExportItem() {
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
            model: page.controller.cprViews
            delegate: Rectangle {
                id: cell
                required property int index
                required property var modelData
                property alias imageItem: viewport
                readonly property bool focused: page.controller.focusedViewportId !== ""
                visible: !focused || page.controller.focusedViewportId === modelData.viewportId
                Layout.row: focused ? 0 : Math.floor(index / 2)
                Layout.column: focused ? 0 : index % 2
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumWidth: 0
                Layout.minimumHeight: 100
                color: Theme.canvasBackground
                border.color: page.controller.activeViewport === modelData ? Theme.primaryColor : Theme.controlBorder
                border.width: 1
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 2
                    spacing: 2
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 32
                        Text {
                            Layout.leftMargin: 6
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            text: qsTrId("cpr." + cell.modelData.viewportRole)
                                + (cell.modelData.historicalPlane ? " · " + qsTrId("cpr.historical") : "")
                            elide: Text.ElideRight
                            color: Theme.textSecondary
                            font.pixelSize: 12
                        }
                        Components.AppComboBox {
                            objectName: "cprPlane-" + cell.index
                            visible: cell.index < 2
                            Layout.preferredWidth: 92
                            model: [qsTrId("text.0384"), qsTrId("text.0385"), qsTrId("text.0386")]
                            currentIndex: ["axial", "coronal", "sagittal"].indexOf(page.controller.referencePlanes[cell.index] ?? "axial")
                            onActivated: page.controller.setReferencePlane(cell.index, ["axial", "coronal", "sagittal"][currentIndex])
                        }
                        Components.AppButton {
                            objectName: "cprFocus-" + cell.modelData.viewportRole
                            compact: true
                            iconName: "fullscreen"
                            minimumButtonWidth: 28
                            Accessible.name: qsTrId(cell.focused ? "reading.restoreViewport" : "reading.maximizeViewport")
                            onClicked: {
                                page.controller.activateViewport(cell.modelData.viewportId)
                                page.controller.focusSingleViewport(cell.focused ? "" : cell.modelData.viewportId)
                            }
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        spacing: 1
                        Viewport {
                            id: viewport
                            objectName: "cprViewport-" + cell.modelData.viewportRole
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            viewportController: cell.modelData
                            hasTabs: true
                            anonymousExport: page.anonymousExport
                            multiViewport: !cell.focused
                            TapHandler {
                                onPressedChanged: if (pressed) page.controller.activateViewport(cell.modelData.viewportId)
                            }
                        }
                        SliceSlider {
                            Layout.fillHeight: true
                            viewportController: cell.modelData
                            allowOrthogonal: true
                        }
                    }
                    Text {
                        Layout.fillWidth: true
                        Layout.leftMargin: 6
                        Layout.bottomMargin: 3
                        visible: cell.index >= 2
                        text: cell.modelData.historicalPlane ? cell.modelData.historicalDescription
                            : page.controller.busy ? qsTrId("cpr.computing")
                            : !page.controller.ready ? qsTrId("cpr.empty")
                            : qsTrId("cpr.distance").arg(page.controller.positionMm.toFixed(1)).arg(page.controller.totalLength.toFixed(1))
                        color: Theme.textSecondary
                        font.pixelSize: 11
                        elide: Text.ElideRight
                    }
                }
            }
        }
    }
}
