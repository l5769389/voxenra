pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic as Basic
import QtQuick.Layouts
import "../components" as Components
import "../theme"

Components.AppDialog {
    id: dialog
    objectName: "fusionSeriesDialog"
    required property var controller
    parent: Basic.Overlay.overlay
    anchors.centerIn: parent
    width: Math.min(780, parent ? parent.width - 32 : 780)
    height: Math.min(640, parent ? parent.height - 32 : 640)
    padding: 16
    modal: true
    Basic.Overlay.modal: Rectangle { color: Theme.modalScrim }
    title: qsTrId("text.0658")
    titleIcon: "fusion"
    subtitle: qsTrId("text.0659")

    function syncVisibility() {
        if (controller.fusionDialogOpen && !visible) open()
        else if (!controller.fusionDialogOpen && visible) close()
    }
    Component.onCompleted: syncVisibility()
    Connections {
        target: dialog.controller
        function onFusionDialogChanged() { dialog.syncVisibility() }
    }
    onClosed: {
        identityCheck.checked = false
        if (controller.fusionDialogOpen) controller.cancelFusion()
    }

    component SeriesPreview: Rectangle {
        id: preview
        required property var series
        implicitWidth: 80
        implicitHeight: 80
        color: Theme.canvasBackground
        radius: 5
        Image {
            id: thumbnail
            objectName: "fusionPreview-" + (preview.series.seriesUid || "")
            anchors.fill: parent
            anchors.margins: 3
            source: dialog.controller.fusionThumbnails[preview.series.seriesUid] || ""
            fillMode: Image.PreserveAspectFit
            smooth: true
        }
        Text {
            anchors.centerIn: parent
            visible: thumbnail.status !== Image.Ready
            text: qsTrId("text.0660")
            color: Theme.textSubtle
            font.pixelSize: 10
        }
    }

    component SeriesDetails: ColumnLayout {
        id: details
        required property var series
        spacing: 4
        Text {
            Layout.fillWidth: true
            text: details.series.description || qsTrId("text.0661")
            textFormat: Text.PlainText
            color: Theme.textPrimary
            font.pixelSize: 13
            font.weight: Font.DemiBold
            elide: Text.ElideRight
        }
        Text {
            Layout.fillWidth: true
            text: (details.series.patientName || qsTrId("text.0662")) + " · "
                + (details.series.patientId || qsTrId("text.0481"))
            textFormat: Text.PlainText
            color: Theme.textSecondary
            font.pixelSize: 12
            elide: Text.ElideRight
        }
        Text {
            Layout.fillWidth: true
            text: I18n.format(qsTrId("fusion.seriesCount"), {date: details.series.studyDate || qsTrId("text.0257"), count: details.series.count || 0})
            color: Theme.textMuted
            font.pixelSize: 11
            elide: Text.ElideRight
        }
        Text {
            Layout.fillWidth: true
            visible: text !== ""
            text: [details.series.relationship, details.series.spatialStatus].filter(Boolean).join(" · ")
            color: Theme.textMuted
            font.pixelSize: 11
            elide: Text.ElideRight
        }
        Text {
            Layout.fillWidth: true
            visible: text !== ""
            text: details.series.error || ""
            color: Theme.dangerColor
            font.pixelSize: 11
            wrapMode: Text.Wrap
        }
    }

    contentItem: ColumnLayout {
        spacing: 10
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: Math.max(100, anchorRow.implicitHeight + 20)
            visible: !!dialog.controller.fusionAnchor.seriesUid
            color: Theme.cardBackground
            radius: 6
            RowLayout {
                id: anchorRow
                anchors.fill: parent
                anchors.margins: 10
                spacing: 12
                SeriesPreview { series: dialog.controller.fusionAnchor }
                SeriesDetails { Layout.fillWidth: true; series: dialog.controller.fusionAnchor }
                Text {
                    text: dialog.controller.fusionAnchor.modality === "CT" ? qsTrId("text.0664") : qsTrId("text.0665")
                    color: Theme.primaryHover
                    font.pixelSize: 12
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Text {
                text: dialog.controller.fusionAnchor.modality === "CT" ? qsTrId("text.0666") : qsTrId("text.0667")
                color: Theme.textPrimary
                font.pixelSize: 13
                font.weight: Font.DemiBold
            }
            Item { Layout.fillWidth: true }
            Text { text: qsTrId("text.0668"); color: Theme.textSubtle; font.pixelSize: 11 }
        }
        ListView {
            id: candidates
            objectName: "fusionCandidates"
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: 6
            model: dialog.controller.fusionCandidates
            Basic.ScrollBar.vertical: Components.AppScrollBar {}
            delegate: Basic.ItemDelegate {
                id: candidate
                required property var modelData
                objectName: "fusionCandidate-" + modelData.seriesUid
                width: candidates.width - 12
                height: Math.max(100, candidateRow.implicitHeight + 20)
                enabled: !modelData.error
                padding: 10
                hoverEnabled: true
                highlighted: dialog.controller.fusionPartnerUid === modelData.seriesUid
                onClicked: { identityCheck.checked = false; dialog.controller.selectFusionPartner(modelData.seriesUid) }
                background: Rectangle {
                    color: candidate.highlighted ? Theme.selectionBackground
                        : candidate.hovered ? Theme.controlHover : Theme.cardBackground
                    border.color: candidate.highlighted ? Theme.selectionBorder : Theme.borderSubtle
                    border.width: candidate.visualFocus ? 2 : 1
                    radius: 6
                }
                contentItem: RowLayout {
                    id: candidateRow
                    spacing: 12
                    SeriesPreview { series: candidate.modelData }
                    SeriesDetails { Layout.fillWidth: true; series: candidate.modelData }
                    Components.AppIcon {
                        iconName: "check"
                        iconSize: 20
                        iconColor: Theme.primaryColor
                        opacity: candidate.highlighted ? 1 : 0
                    }
                }
            }
            Text {
                anchors.centerIn: parent
                width: parent.width - 24
                visible: candidates.count === 0
                text: dialog.controller.fusionShowAllPatients ? qsTrId("text.0669")
                    : I18n.format(qsTrId("fusion.noMatch"), {modality: dialog.controller.fusionTargetModality})
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                color: Theme.textMuted
                font.pixelSize: 12
            }
        }
        Components.AppCheckBox {
            objectName: "fusionShowAllPatients"
            Layout.fillWidth: true
            text: qsTrId("text.0672")
            checked: dialog.controller.fusionShowAllPatients
            onClicked: { identityCheck.checked = false; dialog.controller.setFusionShowAllPatients(checked) }
        }
        Text {
            Layout.fillWidth: true
            text: dialog.controller.fusionError
            visible: text !== ""
            color: Theme.dangerColor
            font.pixelSize: 12
            wrapMode: Text.Wrap
        }
        Text {
            Layout.fillWidth: true
            text: dialog.controller.fusionIdentityWarning
            visible: text !== ""
            color: Theme.textSecondary
            font.pixelSize: 12
            wrapMode: Text.Wrap
        }
        Components.AppCheckBox {
            id: identityCheck
            objectName: "fusionIdentityConfirmation"
            Layout.fillWidth: true
            visible: dialog.controller.fusionIdentityWarning !== ""
            text: qsTrId("text.0673")
        }
    }
    footer: Components.AppDialogFooter {
        leading: Text {
            Layout.fillWidth: true
            text: qsTrId("text.0674")
            color: Theme.textSubtle
            font.pixelSize: 11
            elide: Text.ElideRight
        }
        Components.AppButton {
            objectName: "cancelFusion"
            text: qsTrId("text.0539")
            minimumButtonWidth: 80
            onClicked: dialog.controller.cancelFusion()
        }
        Components.AppButton {
            objectName: "confirmFusion"
            text: qsTrId("text.0675")
            iconName: "fusion"
            actionRole: "primary"
            minimumButtonWidth: 112
            enabled: dialog.controller.fusionCanConfirm
                && (dialog.controller.fusionIdentityWarning === "" || identityCheck.checked)
            onClicked: dialog.controller.confirmFusion(identityCheck.checked)
        }
    }
}
