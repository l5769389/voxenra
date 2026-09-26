pragma Singleton

import QtQuick
import "PaletteData.js" as PaletteData

QtObject {
    readonly property var palette: typeof appController !== "undefined" && appController.appearanceController
        ? appController.appearanceController.colors : PaletteData.data.defaults

    // Brand colors: cold cyan is the main interaction color, while steel blue
    // is used for neutral secondary actions. Warm orange is intentionally rare.
    readonly property color primaryColor: palette.primaryColor ?? PaletteData.data.defaults.primaryColor
    readonly property color primaryStrong: palette.primaryStrong ?? PaletteData.data.defaults.primaryStrong
    readonly property color primaryHover: palette.primaryHover ?? PaletteData.data.defaults.primaryHover
    readonly property color primaryPressed: palette.primaryPressed ?? PaletteData.data.defaults.primaryPressed
    readonly property color primarySoft: palette.primarySoft ?? PaletteData.data.defaults.primarySoft
    readonly property color primarySoftHover: palette.primarySoftHover ?? PaletteData.data.defaults.primarySoftHover

    readonly property color secondaryColor: palette.secondaryColor ?? PaletteData.data.defaults.secondaryColor
    readonly property color secondaryStrong: palette.secondaryStrong ?? PaletteData.data.defaults.secondaryStrong
    readonly property color secondaryHover: palette.secondaryHover ?? PaletteData.data.defaults.secondaryHover
    readonly property color secondaryPressed: palette.secondaryPressed ?? PaletteData.data.defaults.secondaryPressed
    readonly property color secondarySoft: palette.secondarySoft ?? PaletteData.data.defaults.secondarySoft

    readonly property color accentWarm: palette.accentWarm ?? PaletteData.data.defaults.accentWarm

    // Surface hierarchy. Keep the DICOM canvas darker than application chrome.
    readonly property color appBackground: palette.appBackground ?? PaletteData.data.defaults.appBackground
    readonly property color shellBackground: palette.shellBackground ?? PaletteData.data.defaults.shellBackground
    readonly property color panelBackground: palette.panelBackground ?? PaletteData.data.defaults.panelBackground
    readonly property color panelBackgroundSoft: palette.panelBackgroundSoft ?? PaletteData.data.defaults.panelBackgroundSoft
    readonly property color panelBackgroundStrong: palette.panelBackgroundStrong ?? PaletteData.data.defaults.panelBackgroundStrong
    readonly property color workspaceBackground: palette.workspaceBackground ?? PaletteData.data.defaults.workspaceBackground
    readonly property color canvasBackground: PaletteData.data.imaging.canvasBackground
    readonly property color cardBackground: palette.cardBackground ?? PaletteData.data.defaults.cardBackground
    readonly property color cardBackgroundHover: palette.cardBackgroundHover ?? PaletteData.data.defaults.cardBackgroundHover
    readonly property color elevatedBackground: palette.elevatedBackground ?? PaletteData.data.defaults.elevatedBackground

    // Image cards retain their contrast independently from application chrome.
    readonly property color overlayMuted: PaletteData.data.imaging.overlayMuted
    readonly property color overlayDivider: PaletteData.data.imaging.overlayDivider
    readonly property color overlayCard: PaletteData.data.imaging.overlayCard
    // Viewport selection is interface chrome; image and annotation colors stay fixed.
    readonly property color viewportActiveBorder: palette.viewportActiveBorder ?? PaletteData.data.defaults.viewportActiveBorder
    readonly property color viewportHoverBorder: palette.viewportHoverBorder ?? PaletteData.data.defaults.viewportHoverBorder
    readonly property color viewportBorder: palette.viewportBorder ?? PaletteData.data.defaults.viewportBorder
    readonly property color chartX: palette.chartX ?? PaletteData.data.defaults.chartX
    readonly property color chartY: palette.chartY ?? PaletteData.data.defaults.chartY

    readonly property color panelBorder: palette.panelBorder ?? PaletteData.data.defaults.panelBorder

    readonly property color tabSelectedBorder: palette.tabSelectedBorder ?? PaletteData.data.defaults.tabSelectedBorder

    // Borders and separators.
    readonly property color borderSubtle: palette.borderSubtle ?? PaletteData.data.defaults.borderSubtle
    readonly property color borderDefault: palette.borderDefault ?? PaletteData.data.defaults.borderDefault
    readonly property color borderStrong: palette.borderStrong ?? PaletteData.data.defaults.borderStrong
    readonly property color dividerColor: palette.dividerColor ?? PaletteData.data.defaults.dividerColor
    readonly property color focusBorder: palette.focusBorder ?? PaletteData.data.defaults.focusBorder

    // Typography.
    readonly property color textPrimary: palette.textPrimary ?? PaletteData.data.defaults.textPrimary
    readonly property color textSecondary: palette.textSecondary ?? PaletteData.data.defaults.textSecondary
    readonly property color textMuted: palette.textMuted ?? PaletteData.data.defaults.textMuted
    readonly property color textSubtle: palette.textSubtle ?? PaletteData.data.defaults.textSubtle
    readonly property color textDisabled: palette.textDisabled ?? PaletteData.data.defaults.textDisabled
    readonly property color textOnPrimary: palette.textOnPrimary ?? PaletteData.data.defaults.textOnPrimary
    readonly property color overlayText: PaletteData.data.imaging.overlayText
    readonly property color overlayOutline: PaletteData.data.imaging.overlayOutline

    // Generic controls.
    readonly property color controlBackground: palette.controlBackground ?? PaletteData.data.defaults.controlBackground
    readonly property color controlHover: palette.controlHover ?? PaletteData.data.defaults.controlHover
    readonly property color controlPressed: palette.controlPressed ?? PaletteData.data.defaults.controlPressed
    readonly property color controlDisabled: palette.controlDisabled ?? PaletteData.data.defaults.controlDisabled
    readonly property color controlBorder: palette.controlBorder ?? PaletteData.data.defaults.controlBorder
    readonly property color controlHoverBorder: palette.controlHoverBorder ?? PaletteData.data.defaults.controlHoverBorder

    // Selection / active interaction. A selected item is not a status message.
    readonly property color selectionBackground: palette.selectionBackground ?? PaletteData.data.defaults.selectionBackground
    readonly property color selectionHover: palette.selectionHover ?? PaletteData.data.defaults.selectionHover
    readonly property color selectionPressed: palette.selectionPressed ?? PaletteData.data.defaults.selectionPressed
    readonly property color selectionBorder: palette.selectionBorder ?? PaletteData.data.defaults.selectionBorder
    readonly property color activeIndicator: palette.activeIndicator ?? PaletteData.data.defaults.activeIndicator
    readonly property color iconDefault: palette.iconDefault ?? PaletteData.data.defaults.iconDefault
    readonly property color iconDisabled: palette.iconDisabled ?? PaletteData.data.defaults.iconDisabled
    readonly property color iconHover: palette.iconHover ?? PaletteData.data.defaults.iconHover
    readonly property color iconActive: palette.iconActive ?? PaletteData.data.defaults.iconActive

    // 两侧工具栏使用图标；完整操作名称由悬停和键盘焦点提示提供。
    readonly property int toolbarIconSize: PaletteData.data.metrics.toolbarIconSize
    readonly property int navigationIconSize: PaletteData.data.metrics.navigationIconSize
    readonly property int toolbarLabelSize: PaletteData.data.metrics.toolbarLabelSize
    readonly property int toolbarButtonHeight: PaletteData.data.metrics.toolbarButtonHeight
    readonly property int controlRadius: PaletteData.data.metrics.controlRadius
    readonly property int bodyFontSize: PaletteData.data.metrics.bodyFontSize

    readonly property color folderAccent: palette.folderAccent ?? PaletteData.data.defaults.folderAccent
    readonly property color folderSurface: palette.folderSurface ?? PaletteData.data.defaults.folderSurface
    readonly property color fusionAccent: palette.fusionAccent ?? PaletteData.data.defaults.fusionAccent
    readonly property int controlHeight: PaletteData.data.metrics.controlHeight
    readonly property int compactControlHeight: PaletteData.data.metrics.compactControlHeight
    readonly property color inputBorder: palette.inputBorder ?? PaletteData.data.defaults.inputBorder
    readonly property color sliderTrack: palette.sliderTrack ?? PaletteData.data.defaults.sliderTrack

    // Primary command buttons, such as "Open DICOM folder".
    readonly property color primaryButtonBackground: palette.primaryButtonBackground ?? PaletteData.data.defaults.primaryButtonBackground
    readonly property color primaryButtonHover: palette.primaryButtonHover ?? PaletteData.data.defaults.primaryButtonHover
    readonly property color primaryButtonPressed: palette.primaryButtonPressed ?? PaletteData.data.defaults.primaryButtonPressed
    readonly property color primaryButtonDisabled: palette.primaryButtonDisabled ?? PaletteData.data.defaults.primaryButtonDisabled
    readonly property color primaryButtonBorder: palette.primaryButtonBorder ?? PaletteData.data.defaults.primaryButtonBorder

    // Semantic status colors. Use their surface variants for backgrounds.
    readonly property color infoColor: palette.infoColor ?? PaletteData.data.defaults.infoColor
    readonly property color infoSurface: palette.infoSurface ?? PaletteData.data.defaults.infoSurface
    readonly property color successColor: palette.successColor ?? PaletteData.data.defaults.successColor
    readonly property color successSurface: palette.successSurface ?? PaletteData.data.defaults.successSurface
    readonly property color warningColor: palette.warningColor ?? PaletteData.data.defaults.warningColor
    readonly property color warningSurface: palette.warningSurface ?? PaletteData.data.defaults.warningSurface
    readonly property color dangerColor: palette.dangerColor ?? PaletteData.data.defaults.dangerColor
    readonly property color dangerSurface: palette.dangerSurface ?? PaletteData.data.defaults.dangerSurface
    readonly property color dangerButtonHover: palette.dangerButtonHover ?? PaletteData.data.defaults.dangerButtonHover
    readonly property color dangerButtonPressed: palette.dangerButtonPressed ?? PaletteData.data.defaults.dangerButtonPressed

    // 重置保留琥珀图标提示；常态使用中性表面，避免抢占影像注意力。
    readonly property color resetActionColor: palette.resetActionColor ?? PaletteData.data.defaults.resetActionColor
    readonly property color resetActionSurface: palette.resetActionSurface ?? PaletteData.data.defaults.resetActionSurface
    readonly property color resetActionHover: palette.resetActionHover ?? PaletteData.data.defaults.resetActionHover
    readonly property color resetActionPressed: palette.resetActionPressed ?? PaletteData.data.defaults.resetActionPressed
    readonly property color resetActionBorder: palette.resetActionBorder ?? PaletteData.data.defaults.resetActionBorder

    // Measurement colors are separate from UI selection colors so overlays
    // remain visible on grayscale and pseudo-color images.
    readonly property color measurementPrimary: PaletteData.data.imaging.measurementPrimary
    readonly property color measurementSelected: PaletteData.data.imaging.measurementSelected
    readonly property color measurementHandle: PaletteData.data.imaging.measurementHandle

    // Shared semantic tokens; image overlays remain independent of UI themes.
    readonly property color modalScrim: palette.modalScrim ?? PaletteData.data.defaults.modalScrim
    readonly property color dateModalScrim: palette.dateModalScrim ?? PaletteData.data.defaults.dateModalScrim
    readonly property color dropBackground: palette.dropBackground ?? PaletteData.data.defaults.dropBackground
    readonly property color dropText: palette.dropText ?? PaletteData.data.defaults.dropText
    readonly property color dropMuted: palette.dropMuted ?? PaletteData.data.defaults.dropMuted
    readonly property color dropCard: palette.dropCard ?? PaletteData.data.defaults.dropCard
    readonly property color diagramBackground: palette.diagramBackground ?? PaletteData.data.defaults.diagramBackground
    readonly property color diagramText: palette.diagramText ?? PaletteData.data.defaults.diagramText
    readonly property color diagramFill: palette.diagramFill ?? PaletteData.data.defaults.diagramFill
    readonly property color diagramVolume: palette.diagramVolume ?? PaletteData.data.defaults.diagramVolume
    readonly property color diagramPrimary: palette.diagramPrimary ?? PaletteData.data.defaults.diagramPrimary
    readonly property color diagramAccent: palette.diagramAccent ?? PaletteData.data.defaults.diagramAccent
    readonly property color diagramMuted: palette.diagramMuted ?? PaletteData.data.defaults.diagramMuted
    readonly property color diagramBand: palette.diagramBand ?? PaletteData.data.defaults.diagramBand
    readonly property color imageBlack: PaletteData.data.imaging.imageBlack
    readonly property color imageHandleBorder: PaletteData.data.imaging.imageHandleBorder
    readonly property color imageBadgeBackground: PaletteData.data.imaging.imageBadgeBackground
    readonly property color qaCardBackground: PaletteData.data.imaging.qaCardBackground
    readonly property color annotationHandle: PaletteData.data.imaging.annotationHandle
    readonly property color annotationBackground: PaletteData.data.imaging.annotationBackground
    readonly property color annotationSelectedBackground: PaletteData.data.imaging.annotationSelectedBackground
    readonly property color annotationArrowBackground: PaletteData.data.imaging.annotationArrowBackground
    readonly property color annotationBorder: PaletteData.data.imaging.annotationBorder
    readonly property color overlayDarkText: PaletteData.data.imaging.overlayDarkText
    readonly property color overlayLightOutline: PaletteData.data.imaging.overlayLightOutline
    readonly property color scaleText: PaletteData.data.imaging.scaleText
    readonly property color scaleOutline: PaletteData.data.imaging.scaleOutline
    readonly property color crosshairPreview: PaletteData.data.imaging.crosshairPreview
    readonly property color annotationDefault: PaletteData.data.imaging.annotationDefault
    readonly property color previewGradientTop: PaletteData.data.imaging.previewGradientTop
    readonly property color previewGradientMiddle: PaletteData.data.imaging.previewGradientMiddle
    readonly property color previewGradientBottom: PaletteData.data.imaging.previewGradientBottom
    readonly property color intensityBlack: PaletteData.data.imaging.intensityBlack
    readonly property color intensityWhite: PaletteData.data.imaging.intensityWhite
    readonly property color axisAxial: PaletteData.data.imaging.axisAxial
    readonly property color axisCoronal: PaletteData.data.imaging.axisCoronal
    readonly property color axisSagittal: PaletteData.data.imaging.axisSagittal
    readonly property var segmentationSwatches: PaletteData.data.swatches.segmentation
    readonly property var annotationSwatches: PaletteData.data.swatches.annotation
    readonly property var overlaySwatches: PaletteData.data.swatches.overlay

    function previewColors(theme) {
        return Object.assign({}, PaletteData.data.defaults, PaletteData.data.themes[theme] || {}, PaletteData.data.imaging)
    }
}
