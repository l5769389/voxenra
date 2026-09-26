pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic as Basic
import QtQuick.Layouts
import "../components" as Components
import "../theme"

Components.AppDialog {
    id: dialog
    objectName: "compareSeriesDialog"
    required property var controller
    required property var thumbnails
    property bool nativePopup: false
    property bool nativeWindowActive: false
    closeButtonVisible: !nativeWindowActive
    // Native VTK child windows would cover an in-scene picker.
    parent: Basic.Overlay.overlay
    anchors.centerIn: parent
    implicitWidth: 680
    implicitHeight: 540
    width: Math.min(implicitWidth, parent.width - 32)
    height: Math.min(implicitHeight, parent.height - 32)
    title: controller.mode === "mpr" ? qsTrId("compare.mpr.title") : qsTrId("compare.title")
    titleIcon: controller.mode === "mpr" ? "nav-compare-mpr" : "nav-compare-2d"
    subtitle: controller.mode === "mpr" ? qsTrId("compare.mpr.choose") : qsTrId("compare.choose")

    function syncVisibility() {
        if (controller.dialogOpen && !visible) {
            nativeWindowActive = nativePopup
            popupType = nativeWindowActive ? Basic.Popup.Window : Basic.Popup.Item
            open()
        }
        else if (!controller.dialogOpen && visible) close()
    }
    Component.onCompleted: syncVisibility()
    Connections {
        target: dialog.controller
        function onChanged() { dialog.syncVisibility() }
    }
    onClosed: controller.cancel()

    component SeriesSummary: RowLayout {
        id: summary
        required property var series
        spacing: 12
        Rectangle {
            Layout.preferredWidth: 56
            Layout.preferredHeight: 56
            color: Theme.imageBlack
            radius: 4
            Image {
                anchors.fill: parent
                anchors.margins: 2
                source: dialog.thumbnails[summary.series.seriesUid] ?? ""
                fillMode: Image.PreserveAspectFit
                asynchronous: true
            }
        }
        ColumnLayout {
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            spacing: 3
            Text {
                Layout.fillWidth: true
                text: summary.series.description ?? ""
                textFormat: Text.PlainText
                font.bold: true
                font.pixelSize: 13
                color: Theme.textPrimary
                elide: Text.ElideRight
            }
            Text {
                Layout.fillWidth: true
                text: [summary.series.patientName, summary.series.patientId, summary.series.studyDate].filter(Boolean).join(" · ")
                textFormat: Text.PlainText
                font.pixelSize: 12
                color: Theme.textSecondary
                elide: Text.ElideRight
            }
            Text {
                Layout.fillWidth: true
                text: (summary.series.modality ?? "") + " · " + I18n.format(qsTrId("compare.slices"), {count: summary.series.count ?? 0})
                font.pixelSize: 11
                color: Theme.textMuted
                elide: Text.ElideRight
            }
        }
    }

    contentItem: ColumnLayout {
        spacing: 12
        Text { text: qsTrId("compare.reference"); color: Theme.textMuted; font.pixelSize: 12 }
        SeriesSummary { Layout.fillWidth: true; series: dialog.controller.anchor }
        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.dividerColor }
        Text { text: qsTrId("compare.partner"); color: Theme.textPrimary; font.pixelSize: 13; font.bold: true }
        ListView {
            id: candidates
            objectName: "compareCandidates"
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: 6
            model: dialog.controller.candidates
            Basic.ScrollBar.vertical: Basic.ScrollBar {}
            delegate: Basic.ItemDelegate {
                id: candidate
                required property var modelData
                width: ListView.view.width
                height: 78
                objectName: "compareCandidate-" + modelData.seriesUid
                padding: 9
                hoverEnabled: true
                highlighted: dialog.controller.partnerUids.indexOf(modelData.seriesUid) >= 0
                onClicked: dialog.controller.togglePartner(modelData.seriesUid)
                background: Rectangle {
                    radius: 6
                    color: candidate.down ? Theme.controlPressed : candidate.highlighted ? Theme.selectionBackground
                        : candidate.hovered ? Theme.controlHover : Theme.panelBackgroundSoft
                    border.width: 1
                    border.color: candidate.highlighted || candidate.visualFocus ? Theme.primaryColor : "transparent"
                }
                contentItem: SeriesSummary { series: candidate.modelData }
            }
            Text {
                anchors.centerIn: parent
                width: parent.width - 20
                visible: candidates.count === 0
                text: qsTrId("compare.empty")
                wrapMode: Text.Wrap
                horizontalAlignment: Text.AlignHCenter
                color: Theme.textMuted
                font.pixelSize: 13
            }
        }
    }
    footer: Components.AppDialogFooter {
        Components.AppButton {
            objectName: "cancelCompare"
            text: qsTrId("text.0539")
            minimumButtonWidth: 80
            onClicked: dialog.controller.cancel()
        }
        Components.AppButton {
            objectName: "confirmCompare"
            text: qsTrId("compare.open")
            iconName: dialog.controller.mode === "mpr" ? "nav-compare-mpr" : "nav-compare-2d"
            actionRole: "primary"
            minimumButtonWidth: 120
            enabled: dialog.controller.canConfirm
            onClicked: dialog.controller.confirm()
        }
    }
}
