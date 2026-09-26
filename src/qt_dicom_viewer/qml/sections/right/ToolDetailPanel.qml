pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import "panels" as Panels
import "../../theme"

Rectangle {
    id: detailPanel

    required property string activePanel
    required property var viewportController
    required property var toolController
    property var tabController: null
    property var exportController: null
    property Item exportItem: null
    signal manualRequested(string chapter)
    readonly property Item loadedPanel: contentLoader.item as Item
    readonly property string activeToolLabel:
        detailPanel.toolController
            ? detailPanel.toolController.activeToolLabel
            : ""
    readonly property string activeToolIcon:
        detailPanel.toolController
            ? detailPanel.toolController.activeToolIcon
            : ""
    readonly property bool petIntensityMode:
        detailPanel.viewportController
            ? (detailPanel.viewportController.displayMappingEditor !== undefined
                ? detailPanel.viewportController.displayMappingEditor === "pet-range"
                : detailPanel.viewportController.isPetViewport === true)
            : false

    implicitHeight: loadedPanel
        ? loadedPanel.implicitHeight + 24
        : 64
    color: Theme.panelBackgroundSoft

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 12
        spacing: 10

        Loader {
            id: contentLoader

            Layout.fillWidth: true
            Layout.minimumWidth: 0
            Layout.alignment: Qt.AlignTop
            Layout.preferredHeight: detailPanel.loadedPanel
                ? detailPanel.loadedPanel.implicitHeight
                : 0

            active: detailPanel.activePanel !== ""
            sourceComponent: {
                if (detailPanel.activePanel === "window")
                    return detailPanel.viewportController
                        && detailPanel.viewportController.reconstructionController
                        ? petWorkspaceComponent : detailPanel.petIntensityMode
                        ? petIntensityComponent : ["palette", "scalar-range"].includes(detailPanel.viewportController?.displayMappingEditor)
                        ? scalarMappingComponent : windowLevelComponent
                if (detailPanel.activePanel === "pseudocolor")
                    return detailPanel.viewportController?.reconstructionController
                        ? petColorComponent : detailPanel.viewportController?.displayMappingEditor === "palette"
                        ? scalarMappingComponent : pseudoColorComponent
                const map = {
                    'scroll': scrollComponent,
                    'mpr-layout': detailPanel.tabController?.mprCompare ? compareMprComponent : detailPanel.tabController?.twoDLayout ? twoDLayoutComponent : mprLayoutComponent,
                    'zoom': zoomComponent,
                    'export': exportComponent,
                    'import': importComponent,
                    'segmentation': voiComponent,
                    'voi': voiComponent,
                    'ct-window': ctWindowComponent,
                    'pet-window': petWorkspaceComponent,
                    'registration': petRegistrationComponent,
                    'fusion-blend': fusionBlendComponent,
                    'rotate': rotatePanelComponent,
                    'mip': mipPanelComponent,
                    'measure': measureComponent,
                    "annotate": annotateComponent,
                    "pseudocolor": pseudoColorComponent,
                    "viewport-settings": viewportSettingsComponent,
                    "service": serviceComponent,
                    "volume-direction": volumeDirectionComponent,
                    "volume-preset": volumePresetComponent,
                    "volume-crop": volumeCropComponent,
                    "play": playbackComponent,
                    "slice-play": playbackComponent
                }
                return map[detailPanel.activePanel] ?? null
            }
        }
    }

    Component {
        id: compareMprComponent
        Panels.CompareMprPanel { controller: detailPanel.tabController }
    }
    Component {
        id: twoDLayoutComponent
        Panels.TwoDLayoutPanel { controller: detailPanel.tabController?.twoDLayout ?? null }
    }
    Component {
        id: mprLayoutComponent
        Panels.MprLayoutPanel { controller: detailPanel.tabController?.mprLayout ?? null }
    }

    Component {
        id: scrollComponent
        Panels.ScrollToolPanel { viewportController: detailPanel.viewportController }
    }
    Component {
        id: zoomComponent
        Panels.ZoomToolPanel { viewportController: detailPanel.viewportController }
    }

    Component {
        id: exportComponent
        Panels.ExportPanel {
            exportController: detailPanel.exportController
            exportItem: detailPanel.exportItem
            onManualRequested: detailPanel.manualRequested("export")
        }
    }

    Component {
        id: importComponent
        Panels.ImportPanel {
            controller: detailPanel.exportController?.dicomResults ?? null
            regionController: detailPanel.tabController?.voiController ?? null
            toolController: detailPanel.toolController
        }
    }

    Component {
        id: voiComponent
        Panels.MprVoiPanel {
            controller: detailPanel.tabController?.voiController ?? detailPanel.viewportController?.voiController ?? null
            mode: detailPanel.activePanel
            onManualRequested: chapter => detailPanel.manualRequested(chapter)
        }
    }

    Component {
        id: volumeCropComponent
        Panels.VolumeCropPanel {
            viewportController: detailPanel.viewportController
        }
    }

    Component {
        id: volumeDirectionComponent
        Panels.VolumeDirectionPanel {
            viewportController: detailPanel.viewportController
        }
    }

    Component {
        id: volumePresetComponent
        Loader {
            sourceComponent: detailPanel.viewportController?.isStandalonePetVolume === true
                ? standalonePetVolumeComponent : detailPanel.viewportController?.isFusionVolume === true
                ? petVolumeComponent : genericVolumePresetComponent
        }
    }
    Component {
        id: genericVolumePresetComponent
        Panels.VolumePresetPanel { viewportController: detailPanel.viewportController }
    }
    Component {
        id: standalonePetVolumeComponent
        Panels.StandalonePetVolumePanel { controller: detailPanel.viewportController }
    }
    Component {
        id: petVolumeComponent
        Panels.PetVolumePanel { controller: detailPanel.viewportController }
    }

    Component {
        id: rotatePanelComponent
        Panels.RotateToolPanel {
            toolController: detailPanel.toolController
            onActionTriggered: action => {
                if (detailPanel.viewportController) {
                    detailPanel.viewportController.applyTransformAction(action)
                }
            }
        }
    }

    Component {
        id: mipPanelComponent
        Panels.MipPanel {
            toolController: detailPanel.toolController
        }
    }

    Component {
        id: petColorComponent
        Panels.PetColorPanel {
            controller: detailPanel.viewportController.reconstructionController
            Component.onCompleted: fusionTarget = detailPanel.viewportController.viewportRole === "fusion"
        }
    }

    Component {
        id: fusionBlendComponent
        Panels.FusionBlendPanel {
            controller: detailPanel.viewportController.reconstructionController
        }
    }

    Component {
        id: petRegistrationComponent
        Panels.PetRegistrationPanel {
            controller: detailPanel.viewportController.reconstructionController
        }
    }

    Component {
        id: ctWindowComponent
        Panels.FusionCtWindowPanel {
            controller: detailPanel.viewportController?.reconstructionController ?? null
        }
    }

    Component {
        id: petWorkspaceComponent
        Panels.PetWorkspacePanel {
            controller: detailPanel.viewportController?.reconstructionController ?? null
        }
    }

    Component {
        id: petIntensityComponent
        Panels.PetIntensityPanel {
            viewportController: detailPanel.viewportController
        }
    }

    Component {
        id: scalarMappingComponent
        Panels.ScalarMappingPanel { viewportController: detailPanel.viewportController }
    }

    Component {
        id: windowLevelComponent
        Panels.WindowLevelToolPanel {
            readonly property bool volumeWindow: detailPanel.viewportController?.viewportType === "volume"
            description: volumeWindow ? qsTrId("volume.windowHint") : detailPanel.viewportController?.overlayInfo?.supplementalColor ? qsTrId("ct.paletteHint") : ""
            settingsController: detailPanel.toolController?.settingsController ?? null
            currentCenter: detailPanel.viewportController?.windowCenter ?? NaN
            currentWidth: detailPanel.viewportController?.windowWidth ?? NaN
            allowEditing: detailPanel.viewportController?.isPetViewport !== true
            supportsAutoWindow: detailPanel.viewportController?.isMrViewport === true
            minimumWidth: detailPanel.viewportController?.minimumWindowWidth ?? 1
            inputPrecision: supportsAutoWindow ? 3 : 1
            allowTemplates: !supportsAutoWindow && !volumeWindow && detailPanel.viewportController?.supportsCtWindow === true
            onAutoWindowRequested: detailPanel.viewportController?.autoWindow()
            supportsInversion: (detailPanel.viewportController?.supportsGrayscaleWindow ?? detailPanel.viewportController?.supportsCtWindow) === true
                && detailPanel.viewportController?.viewportType !== "volume"
            inverted: detailPanel.viewportController?.inverted ?? false
            onInversionRequested: detailPanel.viewportController?.toggleInverted()
            presets: volumeWindow ? [] : detailPanel.viewportController
                && detailPanel.viewportController.windowPresets !== undefined
                ? detailPanel.viewportController.windowPresets
                : detailPanel.toolController
                ? detailPanel.toolController.windowPresets
                : []

            onActionTriggered: (presetId, center, width) => {
                if (detailPanel.viewportController) {
                    detailPanel.viewportController.applyWindowPreset(
                        center,
                        width
                    )
                }
            }
        }
    }

    Component {
        id: measureComponent
        Panels.MeasurePanel {
            resultsController: detailPanel.tabController?.measurementResults ?? null
            dicomResults: detailPanel.exportController?.dicomResults ?? null
            viewportController: detailPanel.viewportController
            maskConversionAvailable: !!detailPanel.tabController?.voiController && !detailPanel.tabController?.isFusion
            onManualRequested: detailPanel.manualRequested("measurement")
            toolController: detailPanel.toolController
            onActionTriggered: action => {
                if (detailPanel.toolController) {
                    detailPanel.toolController.selectInteraction(action)
                }
            }
        }
    }

    Component {
        id: serviceComponent
        Panels.ServicePanel {
            onManualRequested: chapter => detailPanel.manualRequested(chapter)
            toolController: detailPanel.toolController
            viewportController: detailPanel.viewportController
            onActionTriggered: action => {
                detailPanel.toolController?.selectService(action)
            }
        }
    }

    Component {
        id: annotateComponent
        Panels.AnnotatePanel {
            viewportController: detailPanel.viewportController
        }
    }

    Component {
        id: pseudoColorComponent
        Panels.PseudoColorPanel {
            viewportController: detailPanel.viewportController
        }
    }

    Component {
        id: viewportSettingsComponent
        Panels.ViewportSettingsPanel {
            viewportController: detailPanel.viewportController
            tabController: detailPanel.tabController ?? detailPanel.viewportController?.workspaceTab ?? null
        }
    }

    Component {
        id: playbackComponent
        Panels.PlaybackPanel {
            tabController: detailPanel.tabController
            sliceMode: detailPanel.activePanel === "slice-play"
        }
    }

}
