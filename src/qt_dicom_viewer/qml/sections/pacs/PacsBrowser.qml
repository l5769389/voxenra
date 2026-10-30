pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic as Basic
import QtQuick.Layouts
import "../../components" as Components
import "../../theme"

Rectangle {
    id: browser
    Components.DelayedActivity { id: feedback; active: browser.visible && browser.pacsController.busy }
    objectName: "pacsBrowser"
    required property var pacsController
    required property var workspaceController
    readonly property bool available: pacsController.pacsEnabled && pacsController.enabledProfiles.length > 0
    readonly property bool canQuery: available && !pacsController.busy
    function submitQuery() {
        if (!canQuery) return
        browser.pacsController.queryStudies({
            PatientName: patientName.text,
            PatientID: patientId.text,
            AccessionNumber: accession.text,
            ModalitiesInStudy: modality.currentIndex > 0 ? modality.currentText : "",
            dateFrom: dateFrom.text,
            dateTo: dateTo.text,
            StudyInstanceUID: studyUid.text,
            StudyDescription: description.text
        }, Number(pageSize.currentText))
    }
    color: Theme.panelBackgroundStrong

    component Caption: Text {
        color: Theme.textMuted
        font.pixelSize: 11
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 20
        spacing: 15
        RowLayout {
            Layout.fillWidth: true
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 6
                Text {
                    Layout.fillWidth: true
                    text: qsTrId("text.0494")
                    color: Theme.textPrimary
                    font.pixelSize: 23
                    font.bold: true
                }
                Text {
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                    text: qsTrId("text.0965")
                    color: Theme.textMuted
                    font.pixelSize: 12
                }
            }
            Components.AppButton {
                objectName: "pacsManageSources"
                text: qsTrId("text.0966")
                onClicked: browser.workspaceController.openDataSources()
            }
        }
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 1
            color: Theme.dividerColor
        }
        RowLayout {
            visible: browser.available
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 15
            ColumnLayout {
                Layout.preferredWidth: browser.width < 900 ? 190 : 225
                Layout.maximumWidth: browser.width < 900 ? 190 : 225
                Layout.fillHeight: true
                spacing: 10
                Basic.ScrollView {
                    id: filterScroll
                    objectName: "pacsFilterScroll"
                    rightPadding: 12
                    Basic.ScrollBar.vertical: Components.AppScrollBar {}
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    contentWidth: availableWidth
                    clip: true
                    ColumnLayout {
                        width: filterScroll.availableWidth
                        spacing: 8
                        Caption {
                            text: qsTrId("text.0967")
                        }
                        Components.AppComboBox {
                            id: profileChoice
                            objectName: "pacsProfileChoice"
                            Layout.fillWidth: true
                            model: browser.pacsController.enabledProfiles
                            textRole: "name"
                            currentIndex: {
                                const rows = browser.pacsController.enabledProfiles;
                                for (let i = 0; i < rows.length; i++)
                                    if (rows[i].id === browser.pacsController.selectedProfileId)
                                        return i;
                                return -1;
                            }
                            enabled: !browser.pacsController.busy
                            onActivated: index => browser.pacsController.selectProfile(browser.pacsController.enabledProfiles[index].id)
                        }
                        Caption {
                            text: qsTrId("text.0028")
                            Layout.topMargin: 5
                        }
                        Components.AppTextField {
                            id: patientName
                            objectName: "pacsPatientName"
                            Layout.fillWidth: true
                            placeholderText: qsTrId("pacs.patientWildcard")
                            onAccepted: browser.submitQuery()
                            text: browser.pacsController.filterInputs.PatientName || ""
                            enabled: !browser.pacsController.busy
                        }
                        Caption {
                            text: qsTrId("text.0029")
                        }
                        Components.AppTextField {
                            id: patientId
                            objectName: "pacsPatientId"
                            Layout.fillWidth: true
                            placeholderText: "ID…"
                            onAccepted: browser.submitQuery()
                            text: browser.pacsController.filterInputs.PatientID || ""
                            enabled: !browser.pacsController.busy
                        }
                        Caption {
                            text: qsTrId("text.0968")
                        }
                        Components.AppTextField {
                            id: accession
                            objectName: "pacsAccession"
                            Layout.fillWidth: true
                            placeholderText: qsTrId("pacs.accessionPlaceholder")
                            onAccepted: browser.submitQuery()
                            text: browser.pacsController.filterInputs.AccessionNumber || ""
                            enabled: !browser.pacsController.busy
                        }
                        Caption {
                            text: qsTrId("text.0026")
                        }
                        Components.AppComboBox {
                            id: modality
                            Layout.fillWidth: true
                            model: [qsTrId("text.0969"), "CT", "MR", "PT", "CR", "DX", "US", "MG", "NM", "XA", "RF", "OT"]
                            currentIndex: Math.max(0, model.indexOf(browser.pacsController.filterInputs.ModalitiesInStudy || qsTrId("text.0969")))
                            enabled: !browser.pacsController.busy
                        }
                        Caption {
                            text: qsTrId("text.0970")
                        }
                        Components.AppDateField {
                            id: dateFrom
                            objectName: "pacsDateFrom"
                            Layout.fillWidth: true
                            placeholderText: "YYYY-MM-DD"
                            onAccepted: browser.submitQuery()
                            text: browser.pacsController.filterInputs.dateFrom || ""
                            enabled: !browser.pacsController.busy
                        }
                        Caption {
                            text: qsTrId("text.0971")
                        }
                        Components.AppDateField {
                            id: dateTo
                            objectName: "pacsDateTo"
                            Layout.fillWidth: true
                            placeholderText: "YYYY-MM-DD"
                            onAccepted: browser.submitQuery()
                            text: browser.pacsController.filterInputs.dateTo || ""
                            enabled: !browser.pacsController.busy
                        }
                        Caption {
                            text: qsTrId("text.0972")
                        }
                        Components.AppComboBox {
                            id: pageSize
                            Layout.fillWidth: true
                            model: ["20", "50", "100"]
                            currentIndex: model.indexOf(String(browser.pacsController.pageSize))
                            enabled: !browser.pacsController.busy
                        }
                        ColumnLayout {
                            id: advanced
                            Layout.fillWidth: true
                            visible: false
                            spacing: 8
                            Caption {
                                text: qsTrId("text.0973")
                            }
                            Components.AppTextField {
                                id: studyUid
                                Layout.fillWidth: true
                                onAccepted: browser.submitQuery()
                                text: browser.pacsController.filterInputs.StudyInstanceUID || ""
                                enabled: !browser.pacsController.busy
                            }
                            Caption {
                                text: qsTrId("text.0025")
                            }
                            Components.AppTextField {
                                id: description
                                objectName: "pacsStudyDescription"
                                Layout.fillWidth: true
                                onAccepted: browser.submitQuery()
                                text: browser.pacsController.filterInputs.StudyDescription || ""
                                enabled: !browser.pacsController.busy
                            }
                        }
                        Components.AppButton {
                            objectName: "pacsMoreFilters"
                            Layout.fillWidth: true
                            text: advanced.visible ? qsTrId("text.0974") : qsTrId("text.0975")
                            onClicked: advanced.visible = !advanced.visible
                        }
                    }
                }
                Components.AppButton {
                    objectName: "pacsQueryStudies"
                    Layout.fillWidth: true
                    text: browser.pacsController.busy && browser.pacsController.operation === "studies" ? qsTrId("text.0976") : qsTrId("text.0977")
                    actionRole: "primary"
                    enabled: browser.canQuery
                    onClicked: browser.submitQuery()
                }
            }
            Rectangle {
                Layout.preferredWidth: 1
                Layout.fillHeight: true
                color: Theme.dividerColor
            }
            ColumnLayout {
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                Layout.fillHeight: true
                spacing: 10
                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        Layout.fillWidth: true
                        text: qsTrId("text.0978")
                        color: Theme.textPrimary
                        font.pixelSize: 15
                        font.bold: true
                    }
                    Components.AppButton {
                        objectName: "pacsStudyPrevious"
                        text: "‹"
                        compact: true
                        minimumButtonWidth: 26
                        enabled: !browser.pacsController.busy && browser.pacsController.studyPage > 1
                        onClicked: browser.pacsController.changeStudyPage(-1)
                    }
                    Caption {
                        text: browser.pacsController.studyPage
                    }
                    Components.AppButton {
                        objectName: "pacsStudyNext"
                        text: "›"
                        compact: true
                        minimumButtonWidth: 26
                        enabled: !browser.pacsController.busy && browser.pacsController.hasStudyNext
                        onClicked: browser.pacsController.changeStudyPage(1)
                    }
                }
                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    color: Theme.cardBackground
                    border.color: Theme.borderDefault
                    radius: 10
                    ListView {
                        id: studiesList
                        objectName: "pacsStudiesList"
                        anchors.fill: parent
                        anchors.margins: 7
                        clip: true
                        spacing: 6
                        model: browser.pacsController.studies
                        Basic.ScrollBar.vertical: Components.AppScrollBar {}
                        function focusStudy(index) {
                            currentIndex = Math.max(0, Math.min(count - 1, index));
                            positionViewAtIndex(currentIndex, ListView.Contain);
                            if (currentItem) {
                                currentItem.forceActiveFocus(Qt.TabFocusReason);
                                // ListView may focus the new current item before forceActiveFocus.
                                currentItem.focusReason = Qt.TabFocusReason;
                            }
                        }
                        delegate: Components.AppButton {
                            id: studyRow
                            required property int index
                            required property var modelData
                            objectName: "pacsStudy-" + modelData.uid
                            width: studiesList.width - 12
                            height: studyContent.implicitHeight + 24
                            cornerRadius: 7
                            padding: 12
                            normalColor: Theme.panelBackgroundStrong
                            hoverColor: Theme.cardBackgroundHover
                            baseBorderWidth: 1
                            baseBorderColor: Theme.borderSubtle
                            checked: browser.pacsController.selectedStudyUid === modelData.uid
                            enabled: !browser.pacsController.busy
                            activeFocusOnTab: index === studiesList.currentIndex
                            Accessible.name: [studyPatient.text, studyPatientId.text, studyDescription.text,
                                studyDate.text, studyAccession.text].join(", ")
                            onActiveFocusChanged: {
                                if (activeFocus) {
                                    studiesList.currentIndex = index;
                                    studiesList.positionViewAtIndex(index, ListView.Contain);
                                }
                            }
                            Keys.onUpPressed: studiesList.focusStudy(index - 1)
                            Keys.onDownPressed: studiesList.focusStudy(index + 1)
                            Keys.onPressed: event => {
                                if (event.key === Qt.Key_Home || event.key === Qt.Key_End) {
                                    studiesList.focusStudy(event.key === Qt.Key_Home ? 0 : studiesList.count - 1);
                                    event.accepted = true;
                                }
                            }
                            Keys.onReturnPressed: click()
                            Keys.onEnterPressed: click()
                            onClicked: browser.pacsController.selectStudy(modelData.uid)
                            contentItem: ColumnLayout {
                                id: studyContent
                                spacing: 6
                                Text {
                                    Layout.fillWidth: true
                                    id: studyPatient
                                    text: studyRow.modelData.patientName || qsTrId("text.0258")
                                    color: Theme.textPrimary
                                    font.pixelSize: 14
                                    font.bold: true
                                    elide: Text.ElideRight
                                }
                                Caption {
                                    Layout.fillWidth: true
                                    id: studyPatientId
                                    text: "ID  " + (studyRow.modelData.patientId || "—")
                                    elide: Text.ElideRight
                                }
                                Text {
                                    Layout.fillWidth: true
                                    id: studyDescription
                                    text: studyRow.modelData.description || qsTrId("text.0979")
                                    color: Theme.textSecondary
                                    font.pixelSize: 12
                                    wrapMode: Text.Wrap
                                }
                                Caption {
                                    Layout.fillWidth: true
                                    id: studyDate
                                    text: (studyRow.modelData.date || qsTrId("text.0257")) + "  ·  " + (studyRow.modelData.modality || "—")
                                    wrapMode: Text.Wrap
                                }
                                Caption {
                                    Layout.fillWidth: true
                                    id: studyAccession
                                    text: I18n.format(qsTrId("pacs.accession"), {value: studyRow.modelData.accession || "—"})
                                    elide: Text.ElideRight
                                }
                            }
                        }
                    }
                    Text {
                        anchors.centerIn: parent
                        width: parent.width - 28
                        visible: browser.pacsController.studies.length === 0
                        text: browser.pacsController.busy && browser.pacsController.operation === "studies" ? qsTrId("text.0981") : qsTrId("text.0982")
                        color: Theme.textSubtle
                        wrapMode: Text.Wrap
                        horizontalAlignment: Text.AlignHCenter
                        font.pixelSize: 12
                        lineHeight: 1.6
                    }
                }
            }
            ColumnLayout {
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                Layout.fillHeight: true
                spacing: 10
                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        Layout.fillWidth: true
                        text: qsTrId("text.0160")
                        color: Theme.textPrimary
                        font.pixelSize: 15
                        font.bold: true
                    }
                    Components.AppButton {
                        objectName: "pacsSeriesPrevious"
                        text: "‹"
                        compact: true
                        minimumButtonWidth: 26
                        enabled: !browser.pacsController.busy && browser.pacsController.seriesPage > 1
                        onClicked: browser.pacsController.changeSeriesPage(-1)
                    }
                    Caption {
                        text: browser.pacsController.seriesPage
                    }
                    Components.AppButton {
                        objectName: "pacsSeriesNext"
                        text: "›"
                        compact: true
                        minimumButtonWidth: 26
                        enabled: !browser.pacsController.busy && browser.pacsController.hasSeriesNext
                        onClicked: browser.pacsController.changeSeriesPage(1)
                    }
                }
                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    color: Theme.cardBackground
                    border.color: Theme.borderDefault
                    radius: 10
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 7
                        spacing: 6
                        Components.AppCheckBox {
                            objectName: "pacsSelectAll"
                            text: qsTrId("text.0983")
                            enabled: browser.pacsController.series.length > 0 && !browser.pacsController.busy
                            checked: browser.pacsController.selectedCount > 0 && browser.pacsController.selectedCount === browser.pacsController.series.length
                            onClicked: browser.pacsController.selectAllSeries(checked)
                        }
                        ListView {
                            id: seriesList
                            objectName: "pacsSeriesList"
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            clip: true
                            spacing: 6
                            model: browser.pacsController.series
                            Basic.ScrollBar.vertical: Components.AppScrollBar {}
                            delegate: Rectangle {
                                id: seriesRow
                                readonly property bool selected: browser.pacsController.selectedSeriesUids.indexOf(modelData.uid) >= 0
                                required property var modelData
                                width: seriesList.width - 12
                                height: seriesContent.implicitHeight + 24
                                radius: 7
                                color: seriesRow.selected ? Theme.selectionBackground : Theme.panelBackgroundStrong
                                border.color: seriesRow.selected ? Theme.selectionBorder : Theme.borderSubtle
                                ColumnLayout {
                                    id: seriesContent
                                    anchors.fill: parent
                                    anchors.margins: 12
                                    spacing: 6
                                    Components.AppCheckBox {
                                        objectName: "pacsSeries-" + seriesRow.modelData.uid
                                        text: (seriesRow.modelData.modality || "DICOM") + "  " + (seriesRow.modelData.number || "")
                                        checked: seriesRow.selected
                                        enabled: !browser.pacsController.busy
                                        onClicked: browser.pacsController.selectSeries(seriesRow.modelData.uid, checked)
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: seriesRow.modelData.description || qsTrId("text.0661")
                                        color: Theme.textPrimary
                                        font.pixelSize: 13
                                        wrapMode: Text.Wrap
                                    }
                                    Caption {
                                        text: I18n.format(qsTrId("pacs.instanceCount"), {count: seriesRow.modelData.instances || "—"})
                                    }
                                }
                            }
                            Text {
                                anchors.centerIn: parent
                                width: parent.width - 20
                                visible: browser.pacsController.series.length === 0
                                text: browser.pacsController.busy && browser.pacsController.operation === "series" ? qsTrId("text.0511") : qsTrId("text.0985")
                                horizontalAlignment: Text.AlignHCenter
                                wrapMode: Text.Wrap
                                color: Theme.textSubtle
                                font.pixelSize: 12
                                lineHeight: 1.6
                            }
                        }
                    }
                }
                Components.AppButton {
                    objectName: "pacsImportSelected"
                    Layout.fillWidth: true
                    text: I18n.format(qsTrId("pacs.importSelected"), {count: browser.pacsController.selectedCount})
                    enabled: browser.pacsController.selectedCount > 0 && !browser.pacsController.busy
                    actionRole: "primary"
                    onClicked: browser.pacsController.importSelected()
                }
            }
        }
        Item {
            visible: !browser.available
            Layout.fillWidth: true
            Layout.fillHeight: true
            ColumnLayout {
                anchors.centerIn: parent
                width: Math.min(420, parent.width - 24)
                spacing: 18
                Text {
                    Layout.fillWidth: true
                    text: qsTrId("text.0987")
                    color: Theme.textPrimary
                    font.pixelSize: 22
                    horizontalAlignment: Text.AlignHCenter
                }
                Text {
                    Layout.fillWidth: true
                    text: qsTrId("text.0988")
                    color: Theme.textMuted
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.Wrap
                    font.pixelSize: 13
                    lineHeight: 1.5
                }
                Components.AppButton {
                    objectName: "pacsConfigureEmpty"
                    Layout.alignment: Qt.AlignHCenter
                    text: qsTrId("text.0989")
                    actionRole: "primary"
                    onClicked: browser.workspaceController.openDataSources()
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            visible: feedback.showing || (!browser.pacsController.busy && browser.pacsController.message !== "")
            Text {
                objectName: "pacsBrowserMessage"
                Layout.fillWidth: true
                text: browser.pacsController.message
                color: browser.pacsController.isError ? Theme.dangerColor : Theme.textMuted
                wrapMode: Text.Wrap
                font.pixelSize: 12
            }
            Components.AppButton {
                objectName: "pacsCancel"
                visible: browser.pacsController.busy
                text: qsTrId("text.0539")
                compact: true
                onClicked: browser.pacsController.cancel()
            }
        }
        Basic.ProgressBar {
            Layout.fillWidth: true
            visible: feedback.showing
            value: browser.pacsController.progress
            indeterminate: browser.pacsController.operation !== "import" || value === 0
        }
    }
}
