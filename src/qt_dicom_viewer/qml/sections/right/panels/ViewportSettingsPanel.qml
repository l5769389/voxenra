pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls.Basic as Basic
import QtQuick.Layouts
import "../../../theme"
import "../../../components" as Components

ColumnLayout {
    id: settingsPanel
    objectName: "viewportSettingsPanel"
    required property var viewportController
    property var tabController: viewportController?.workspaceTab ?? null
    readonly property var scene: tabController?.twoDLayout ?? null
    readonly property var mprLayout: tabController?.mprLayout ?? null
    readonly property bool isVolume: viewportController?.viewportType === "volume"
    spacing: 4
    readonly property var petWorkspace: viewportController?.reconstructionController ?? null

    readonly property var compareWorkspace: viewportController?.workspaceTab?.syncOperations !== undefined
        ? viewportController.workspaceTab : null

    Components.PanelHeading {
        objectName: "ViewportSettingsPanelHeading"
        title: qsTrId("text.0311")
        explanation: (settingsPanel.mprLayout ? qsTrId("mpr.reference.hint") + "\n\n" : "") + (settingsPanel.scene?.settingsScope === "tab" ? qsTrId("viewport.scope.tabHint") : qsTrId("viewport.scope.currentHint"))
    }

    ColumnLayout {
        Layout.fillWidth: true
        visible: !!settingsPanel.mprLayout
        spacing: 8
        Text { Layout.fillWidth: true; Layout.minimumWidth: 0; wrapMode: Text.Wrap; text: qsTrId("mpr.reference.title"); color: Theme.textPrimary; font.pixelSize: 14; font.bold: true }
        Components.AppComboBox {
            objectName: "mprReferenceMode"
            Layout.fillWidth: true
            model: [{label: qsTrId("mpr.reference.planes"), value: "planes"},
                    {label: qsTrId("mpr.reference.point"), value: "point"}, {label: qsTrId("mpr.reference.hidden"), value: "hidden"}]
            textRole: "label"
            currentIndex: model.findIndex(o => o.value === settingsPanel.mprLayout?.referenceMode)
            onActivated: settingsPanel.mprLayout.setReferenceMode(model[currentIndex].value)
        }
        Components.AppCheckBox {
            objectName: "mprLinkRotation"
            Layout.fillWidth: true
            text: qsTrId("mpr.reference.linkRotation")
            checked: settingsPanel.mprLayout?.linkRotation ?? true
            onToggled: settingsPanel.mprLayout.setLinkRotation(checked)
        }

    }
    Rectangle {
        visible: !!settingsPanel.mprLayout && !settingsPanel.isVolume
        Layout.fillWidth: true; height: 1; color: Theme.dividerColor
    }

    ColumnLayout {
        Layout.fillWidth: true
        visible: settingsPanel.compareWorkspace !== null
        spacing: 6
        Text { Layout.fillWidth: true; Layout.minimumWidth: 0; wrapMode: Text.Wrap; text: qsTrId("compare.syncTitle"); color: Theme.textPrimary; font.bold: true }
        Text {
            Layout.fillWidth: true
            text: qsTrId("compare.independentMeasurements")
            color: Theme.textMuted
            font.pixelSize: 11
            wrapMode: Text.Wrap
        }
        Components.AppComboBox {
            objectName: "compareScrollMode"
            Layout.fillWidth: true
            model: [qsTrId("compare.patientCoordinates"), qsTrId("compare.relativeProgress")]
            currentIndex: settingsPanel.compareWorkspace?.scrollMode === "spatial" ? 0 : 1
            onActivated: settingsPanel.compareWorkspace?.setScrollMode(currentIndex === 0 ? "spatial" : "relative")
        }
        GridLayout {
            Layout.fillWidth: true
            columns: 2
            columnSpacing: 4
            rowSpacing: 0
            Repeater {
                model: settingsPanel.compareWorkspace ? ["scroll", "window", "pan", "zoom", "rotate", "flip", "pseudocolor", "invert", "viewport"] : []
                delegate: Components.AppCheckBox {
                    required property string modelData
                    objectName: "compareSync-" + modelData
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    implicitHeight: 34
                    text: qsTrId("compare.sync." + modelData)
                    checked: settingsPanel.compareWorkspace?.syncOperations[modelData] ?? false
                    onToggled: settingsPanel.compareWorkspace?.setSyncOperation(modelData, checked)
                }
            }
        }
        Text {
            Layout.fillWidth: true
            text: settingsPanel.compareWorkspace?.navigationNotice ?? ""
            color: Theme.textMuted
            font.pixelSize: 11
            wrapMode: Text.Wrap
        }
        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.dividerColor }
    }

    ColumnLayout {
        Layout.fillWidth: true
        visible: settingsPanel.petWorkspace !== null
        spacing: 8
        Text { Layout.fillWidth: true; Layout.minimumWidth: 0; wrapMode: Text.Wrap; text: qsTrId("text.1102"); color: Theme.textPrimary; font.bold: true }
        Text { Layout.fillWidth: true; Layout.minimumWidth: 0; wrapMode: Text.Wrap; text: qsTrId("text.1103"); color: Theme.textMuted; font.pixelSize: 12 }
        RowLayout {
            Layout.fillWidth: true
            Repeater {
                model: [{label:qsTrId("text.1104"), compact:true}, {label:qsTrId("text.1105"), compact:false}]
                delegate: Components.AppButton {
                    id: locatorButton
                    required property var modelData
                    implicitHeight: Math.max(32, contentItem.implicitHeight + topPadding + bottomPadding)
                    contentItem: Text {
                        text: locatorButton.text
                        font.pixelSize: 13
                        color: locatorButton.textColor
                        wrapMode: Text.WordWrap
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    objectName: "petLocator-" + (modelData.compact ? "compact" : "lines")
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    Layout.preferredWidth: 1
                    text: modelData.label
                    compact: true; checkable: true; autoExclusive: true; baseBorderWidth: 1
                    checked: settingsPanel.petWorkspace?.compactCrosshair === modelData.compact
                    onClicked: settingsPanel.petWorkspace.setCompactCrosshair(modelData.compact)
                }
            }
        }
        Text { Layout.fillWidth: true; Layout.minimumWidth: 0; wrapMode: Text.Wrap; text: qsTrId("text.0826"); color: Theme.textMuted; font.pixelSize: 12 }
        RowLayout {
            Layout.fillWidth: true
            Repeater {
                model: [{label:qsTrId("text.1106"), compact:true}, {label:qsTrId("text.1107"), compact:false}]
                delegate: Components.AppButton {
                    required property var modelData
                    objectName: "petInfo-" + (modelData.compact ? "compact" : "detail")
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    Layout.preferredWidth: 1
                    text: modelData.label
                    compact: true; checkable: true; autoExclusive: true; baseBorderWidth: 1
                    checked: settingsPanel.petWorkspace?.compactOverlay === modelData.compact
                    onClicked: settingsPanel.petWorkspace.setCompactOverlay(modelData.compact)
                }
            }
        }
        Text { Layout.fillWidth: true; Layout.minimumWidth: 0; wrapMode: Text.Wrap; text: qsTrId("text.1108"); color: Theme.textMuted; font.pixelSize: 11 }
        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.dividerColor }
    }

    ColumnLayout {
        Layout.fillWidth: true
        visible: !!settingsPanel.scene
        spacing: 6
        Text { Layout.fillWidth: true; Layout.minimumWidth: 0; wrapMode: Text.Wrap; text: qsTrId("viewport.scope.title"); color: Theme.textPrimary; font.bold: true }
        RowLayout {
            Layout.fillWidth: true
            spacing: 6
            Repeater {
                model: [{value: "current", label: qsTrId("viewport.scope.current")},
                        {value: "tab", label: qsTrId("viewport.scope.tab")}]
                delegate: Components.AppButton {
                    required property var modelData
                    objectName: "viewportScope-" + modelData.value
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
                    text: modelData.label
                    compact: true
                    checkable: true
                    checked: settingsPanel.scene?.settingsScope === modelData.value
                    onClicked: settingsPanel.scene?.setSettingsScope(modelData.value)
                }
            }
        }

        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.dividerColor }
    }
    readonly property var settings: [
        {code: "window-annotations", label: qsTrId("text.1109"), separator: false},
        {code: "hide-sensitive-info", label: qsTrId("text.1110"), separator: false},
        {code: "scale-bar", label: qsTrId("text.0828"), separator: false},
        {code: "color-bar", label: qsTrId("text.1111"), separator: false},
        {code: "dicom-overlay", label: qsTrId("viewport.orientationMarkers"), separator: false},
        {code: "localizer", label: qsTrId("text.1112"), separator: true},
        {code: "fit-to-window", label: qsTrId("text.1113"), separator: true}
    ].filter(item => item.code !== "localizer" || (!settingsPanel.scene && settingsPanel.viewportController?.hasCrosshair === true))

    function valueFor(code) {
        const controller = settingsPanel.viewportController
        if (!controller)
            return false
        switch (code) {
        case "window-annotations": return controller.showWindowAnnotations
        case "hide-sensitive-info": return controller.hideSensitiveInfo
        case "scale-bar": return controller.showScaleBar
        case "color-bar": return controller.showColorBar
        case "dicom-overlay": return controller.showDicomOverlay
        case "localizer": return controller.showLocalizer
        case "fit-to-window": return controller.fitToWindow
        default: return false
        }
    }

    Repeater {
        model: settingsPanel.isVolume ? [] : settingsPanel.settings

        delegate: ColumnLayout {
            id: settingRow
            required property var modelData
            Layout.fillWidth: true
            spacing: 4

            Rectangle {
                visible: settingRow.modelData.separator
                Layout.fillWidth: true
                Layout.topMargin: 3
                height: 1
                color: Theme.dividerColor
            }

            Components.AppCheckBox {
                id: settingCheckBox
                objectName: "viewportSetting-" + settingRow.modelData.code
                Layout.fillWidth: true
                implicitHeight: Math.max(36, contentItem.implicitHeight + topPadding + bottomPadding)
                contentItem: Text {
                    text: settingCheckBox.text
                    color: settingCheckBox.enabled ? Theme.textSecondary : Theme.textDisabled
                    font.pixelSize: Theme.bodyFontSize
                    leftPadding: settingCheckBox.indicator.width + settingCheckBox.spacing
                    verticalAlignment: Text.AlignVCenter
                    wrapMode: Text.WordWrap
                }
                text: settingRow.modelData.label
                tristate: settingsPanel.scene?.settingsScope === "tab"
                checkState: settingsPanel.scene
                    ? (settingsPanel.scene.viewportSettingStates[settingRow.modelData.code] ?? Qt.Unchecked)
                    : settingsPanel.valueFor(settingRow.modelData.code) ? Qt.Checked : Qt.Unchecked
                nextCheckState: function() { return checkState === Qt.Checked ? Qt.Unchecked : Qt.Checked }
                onClicked: {
                    const target = settingsPanel.scene ?? settingsPanel.viewportController
                    target?.setViewportSetting(settingRow.modelData.code, checkState === Qt.Checked)
                }
            }
        }
    }

    Item { Layout.fillHeight: true }

}
