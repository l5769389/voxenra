pragma ComponentBehavior: Bound
import QtQuick

// The fusion workspace uses the same content and spacing as 2D PET.
PetIntensityPanel {
    objectName: "petWorkspacePanel"
    required property var controller
    viewportController: controller?.petController ?? null
}
