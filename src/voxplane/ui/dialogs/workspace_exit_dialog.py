"""Theme-aware exit confirmation for new and existing workspace documents."""
from PySide6.QtCore import Qt

from voxplane.i18n import message as _msg
from voxplane.i18n.widgets import QCheckBox, QMessageBox


class WorkspaceExitDialog(QMessageBox):
    def __init__(self, appearance, *, workspace_name="", new_workspace=False):
        self._workspace_name = workspace_name
        self._new_workspace = new_workspace
        title = 'workspace.new.action' if new_workspace else 'workspace.exit.title'
        question = ('workspace.new.question' if new_workspace else
                    'workspace.exit.updateQuestion' if workspace_name else 'text.0433')
        super().__init__(QMessageBox.NoIcon, _msg(title), _msg(question),
                         QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        self.setObjectName("workspaceNewConfirmation" if new_workspace else "workspaceExitConfirmation")
        # A platform-native alert can ignore the application's selected palette.
        self.setOption(QMessageBox.Option.DontUseNativeDialog, True)
        self.setTextFormat(Qt.PlainText)
        if new_workspace:
            self.setInformativeText(_msg('workspace.new.details'))
        elif not workspace_name:
            self.setInformativeText(_msg('workspace.exit.saveDetails'))
        self.button(QMessageBox.Save).setObjectName("workspaceExitSave")
        self.setDefaultButton(QMessageBox.Save)
        self.setEscapeButton(QMessageBox.Cancel)
        if not new_workspace:
            remember = QCheckBox(_msg('text.0435'), self)
            remember.setObjectName("rememberWorkspaceExit")
            remember.setToolTip(_msg('text.0434'))
            self.setCheckBox(remember)
        self._appearance = appearance
        appearance.changed.connect(self._apply_theme)
        self._apply_theme()

    def _button_message_ids(self):
        if self._new_workspace:
            save, discard = 'workspace.new.save', 'workspace.new.discard'
        elif self._workspace_name:
            save, discard = 'workspace.exit.update', 'workspace.exit.dontUpdate'
        else:
            save, discard = 'workspace.exit.save', 'common.dontSave'
        return {QMessageBox.Save: save, QMessageBox.Discard: discard, QMessageBox.Cancel: 'workspace.exit.cancel'}

    def _apply_theme(self):
        style = """
            QMessageBox { background: @panelBackground; color: @textPrimary; }
            QLabel, QCheckBox { color: @textPrimary; background: transparent; }
            QLabel#qt_msgbox_informativelabel { color: @textSecondary; }
            QCheckBox { spacing: 8px; }
            QPushButton { background: @controlBackground; color: @textPrimary;
                border: 1px solid @controlBorder; border-radius: 4px; padding: 7px 14px; }
            QPushButton:hover { background: @controlHover; border-color: @controlHoverBorder; }
            QPushButton:pressed { background: @controlPressed; }
            QPushButton:focus { border-color: @focusBorder; }
            QPushButton#workspaceExitSave { background: @primaryButtonBackground;
                color: @textOnPrimary; border-color: @primaryButtonBorder; }
            QPushButton#workspaceExitSave:hover { background: @primaryButtonHover; }
            QPushButton#workspaceExitSave:pressed { background: @primaryButtonPressed; }
        """
        colors = self._appearance.colors
        for key in sorted(colors, key=len, reverse=True):
            style = style.replace('@' + key, colors[key])
        self.setStyleSheet(style)
