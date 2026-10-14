"""Explicit, theme-aware confirmation before tab editing work is removed."""
from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QDialogButtonBox

from qt_dicom_viewer.i18n import localize, message as _msg
from qt_dicom_viewer.i18n.widgets import QMessageBox


class TabCloseDialog(QMessageBox):
    def __init__(self, appearance=None, owner=None):
        super().__init__(QMessageBox.Warning, _msg('tabs.closeEditedTitle'),
                         _msg('tabs.closeEditedMessage'),
                         QMessageBox.Close | QMessageBox.Cancel)
        self.setObjectName('tabCloseConfirmation')
        self.setOption(QMessageBox.Option.DontUseNativeDialog, True)
        self.setTextFormat(Qt.PlainText)
        self.setDefaultButton(QMessageBox.Cancel)
        self.setEscapeButton(QMessageBox.Cancel)
        self._button_box = self.findChild(QDialogButtonBox)
        self._button_box.installEventFilter(self)
        self._appearance = appearance
        if appearance is not None:
            appearance.changed.connect(self._apply_theme)
            self._apply_theme()
        if owner is not None:
            self.winId()
            self.windowHandle().setTransientParent(owner)

    def eventFilter(self, watched, event):
        if watched is self._button_box and event.type() == QEvent.LanguageChange:
            # These labels belong to the app. The child can receive this event
            # after the dialog, so prevent Qt from restoring system labels.
            self._translate_buttons()
            return True
        return super().eventFilter(watched, event)

    def _translate_buttons(self):
        super()._translate_buttons()
        button = self.button(QMessageBox.Close)
        if button is not None:
            button.setText(localize(_msg('tabs.closeEditedConfirm')))

    def _apply_theme(self):
        style = """
            QMessageBox { background: @panelBackground; color: @textPrimary; }
            QLabel { color: @textPrimary; background: transparent; }
            QPushButton { background: @controlBackground; color: @textPrimary;
                border: 1px solid @controlBorder; border-radius: 4px; padding: 7px 14px; }
            QPushButton:hover { background: @controlHover; border-color: @controlHoverBorder; }
            QPushButton:pressed { background: @controlPressed; }
            QPushButton:focus { border-color: @focusBorder; }
        """
        colors = self._appearance.colors
        for key in sorted(colors, key=len, reverse=True):
            style = style.replace('@' + key, colors[key])
        self.setStyleSheet(style)
