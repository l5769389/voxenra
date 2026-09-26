pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic as Basic
import QtQuick.Layouts
import "../../../components" as Components
import "../../../theme"

Components.AppButton {
    id: root
    required property var controller
    readonly property var geometry: controller?.roiGeometry ?? ({})
    readonly property bool ramp: controller?.measurementMethod === "ramp"
    objectName: "editAnalysisRoi"
    text: qsTrId("analysis.editRoi")
    enabled: geometry.columns !== undefined && controller?.status !== "editing"
    Accessible.description: qsTrId("analysis.coordinates")
    onClicked: editor.open()
    onVisibleChanged: if (!visible) editor.close()

    Basic.Popup {
        id: editor
        objectName: "analysisRoiEditor"
        parent: Basic.Overlay.overlay
        property string sourceGeometry: ""
        property string sourceFrame: ""
        property string sourceTarget: ""
        popupType: Basic.Popup.Item
        modal: false
        focus: true
        padding: 14
        width: Math.min(340, (parent?.width ?? 356) - 16)
        closePolicy: Basic.Popup.CloseOnEscape | Basic.Popup.CloseOnPressOutside
        onAboutToShow: {
            const position = root.mapToItem(parent, 0, root.height)
            x = Math.max(8, Math.min(position.x, parent.width-width-8))
            y = Math.max(8, Math.min(position.y+6, parent.height-height-8))
            sourceGeometry = JSON.stringify(root.geometry)
            sourceFrame = root.controller.frameToken
            sourceTarget = root.controller.measurementMethod
            cx.text = String(Number(root.geometry.centerX.toFixed(6)))
            cy.text = String(Number(root.geometry.centerY.toFixed(6)))
            rw.text = String(Number(root.geometry.width.toFixed(6)))
            rh.text = String(Number(root.geometry.height.toFixed(6)))
            failure.visible = false
            cx.forceActiveFocus()
            cx.selectAll()
        }
        function apply() {
            if (!cx.acceptableInput || !cy.acceptableInput || !rw.acceptableInput
                    || (root.ramp && !rh.acceptableInput)) return
            if (root.controller.applyRoi(Number(cx.text), Number(cy.text), Number(rw.text),
                    root.ramp ? Number(rh.text) : Number(rw.text))) close()
            else failure.visible = true
        }
        Connections {
            target: root.controller
            function onStateChanged() {
                if (editor.opened && (root.controller.status === "editing"
                        || editor.sourceFrame !== root.controller.frameToken
                        || editor.sourceTarget !== root.controller.measurementMethod
                        || editor.sourceGeometry !== JSON.stringify(root.geometry))) editor.close()
            }
        }
        background: Rectangle { color: Theme.elevatedBackground; radius: 6; border.color: Theme.borderStrong }
        contentItem: ColumnLayout {
            spacing: 10
            Text { text: qsTrId("analysis.editRoi"); color: Theme.textPrimary; font.bold: true }
            Text {
                Layout.fillWidth: true
                text: qsTrId("analysis.coordinates")
                color: Theme.textSecondary
                font.pixelSize: 11
                wrapMode: Text.Wrap
            }
            GridLayout {
                Layout.fillWidth: true
                columns: 2
                component Label: Text { color: Theme.textSecondary; font.pixelSize: 12 }
                component Input: Components.AppTextField {
                    Layout.fillWidth: true
                    selectByMouse: true
                    validator: DoubleValidator { locale: "C"; bottom: 0; top: 100000; decimals: 6; notation: DoubleValidator.StandardNotation }
                    onAccepted: editor.apply()
                }
                Label { text: qsTrId("analysis.centerX") }
                Input { id: cx; objectName: "analysisRoiCenterX"; Accessible.name: qsTrId("analysis.centerX") }
                Label { text: qsTrId("analysis.centerY") }
                Input { id: cy; objectName: "analysisRoiCenterY"; Accessible.name: qsTrId("analysis.centerY") }
                Label { text: root.ramp ? qsTrId("analysis.width") : qsTrId("analysis.side") }
                Input { id: rw; objectName: "analysisRoiWidth"; Accessible.name: root.ramp ? qsTrId("analysis.width") : qsTrId("analysis.side") }
                Label { visible: root.ramp; text: qsTrId("analysis.height") }
                Input { id: rh; visible: root.ramp; objectName: "analysisRoiHeight"; Accessible.name: qsTrId("analysis.height") }
            }
            Text {
                id: failure
                objectName: "analysisRoiError"
                Layout.fillWidth: true
                visible: false
                text: qsTrId("analysis.invalidRoi")
                color: Theme.chartY
                wrapMode: Text.Wrap
                Accessible.role: Accessible.StaticText
                Accessible.name: text
            }
            Components.AppButton {
                objectName: "applyAnalysisRoi"
                Layout.fillWidth: true
                text: qsTrId("analysis.applyRoi")
                actionRole: "primary"
                enabled: cx.acceptableInput && cy.acceptableInput && rw.acceptableInput && (!root.ramp || rh.acceptableInput)
                onClicked: editor.apply()
            }
        }
    }
}
