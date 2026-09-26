# spShelf v2.1.0 (Pure Qt / PySide rewrite)
# v2.1.0 - Added DPI & System Scaling support: automatic detection from Maya/Qt/OS
#          and manual scale override in Settings (75% - 300% / Custom).
# v2.0.0 - Full rewrite to native Qt (PySide2/PySide6) for instantaneous opening (0-2ms),
#          elimination of Windows DWM open/close animations, multi-monitor auto-detection,
#          mouse-release cancellation (cancel on drag-off), and cached UI singleton.
# v1.1.6 - Added option and checkbox to hide window title bar (titleBar flag).
# v1.1.5 - Fixed shelf file search: now correctly iterates all paths in MAYA_SHELF_PATH.

import os
import sys
import json
import time
import maya.cmds as cmds
import maya.mel as mel

# ----------------------------------------------------------------------
# Qt Imports (PySide6 for Maya 2025+, PySide2 for Maya <= 2024)
# ----------------------------------------------------------------------
try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:
    try:
        from PySide2 import QtCore, QtGui, QtWidgets
    except ImportError:
        raise ImportError("spShelf requires PySide6 or PySide2 to be installed in Maya.")

DEBUG = True

def log_debug(msg):
    if DEBUG:
        print(f"[spShelf DEBUG] {msg}")


def get_maya_main_window():
    """Returns Maya's main window widget as a QWidget parent."""
    for widget in QtWidgets.QApplication.topLevelWidgets():
        if widget.objectName() == "MayaWindow":
            return widget
    return None


def get_maya_icon(icon_name):
    """
    Locates and returns a QIcon for a given Maya icon identifier or file path.
    Supports absolute paths, Maya resource paths (':/icon.png'), and XBMLANGPATH.
    """
    if not icon_name:
        return QtGui.QIcon()

    # 1. Direct file path
    if os.path.exists(icon_name):
        return QtGui.QIcon(icon_name)

    # 2. Qt Resource path (Maya embeds thousands of icons in Qt resources)
    qrc_name = icon_name if icon_name.startswith(":/") else ":/" + icon_name
    if QtCore.QFile.exists(qrc_name):
        return QtGui.QIcon(qrc_name)

    # 3. Direct QIcon resolution
    icon = QtGui.QIcon(icon_name)
    if not icon.isNull():
        return icon

    # 4. Search XBMLANGPATH
    xbm_env = os.environ.get("XBMLANGPATH", "")
    for p in xbm_env.split(";"):
        clean_dir = p.replace("%B", "").rstrip("/\\")
        candidate = os.path.join(clean_dir, icon_name)
        if os.path.exists(candidate):
            return QtGui.QIcon(candidate)

    # Fallback default icon
    return QtGui.QIcon(":/commandButton.png")


def get_maya_pixmap(icon_name):
    """
    Locates and returns the highest resolution QPixmap for a Maya icon.
    Checks for high-DPI variants (_200, _150, @2x) if available.
    """
    if not icon_name:
        return QtGui.QPixmap()

    base, ext = os.path.splitext(icon_name)
    variants = [
        f"{base}_200{ext}",
        f"{base}_150{ext}",
        f"{base}@2x{ext}",
        icon_name
    ]

    for cand in variants:
        # 1. Direct file path
        if os.path.exists(cand):
            pix = QtGui.QPixmap(cand)
            if not pix.isNull():
                return pix

        # 2. Qt Resource path
        qrc = cand if cand.startswith(":/") else ":/" + cand
        if QtCore.QFile.exists(qrc):
            pix = QtGui.QPixmap(qrc)
            if not pix.isNull():
                return pix

        # 3. XBMLANGPATH
        xbm_env = os.environ.get("XBMLANGPATH", "")
        for p in xbm_env.split(";"):
            clean_dir = p.replace("%B", "").rstrip("/\\")
            c_path = os.path.join(clean_dir, cand)
            if os.path.exists(c_path):
                pix = QtGui.QPixmap(c_path)
                if not pix.isNull():
                    return pix

    # Fallback via QIcon available sizes
    icon = get_maya_icon(icon_name)
    if not icon.isNull():
        sizes = icon.availableSizes()
        if sizes:
            best_size = max(sizes, key=lambda s: s.width() * s.height())
            return icon.pixmap(best_size)
        return icon.pixmap(QtCore.QSize(128, 128))

    return QtGui.QPixmap(":/commandButton.png")


def get_system_scale(screen=None):
    """
    Detects the current DPI / interface scale factor from Maya, Qt Screen, or OS.
    Returns a float (e.g. 1.0, 1.25, 1.5, 2.0).
    """
    # 1. Maya DPI setting (reflects user's Maya interface scaling preference)
    try:
        import maya.cmds as cmds
        if hasattr(cmds, "mayaDpiSetting"):
            rsv = cmds.mayaDpiSetting(query=True, realScaleValue=True)
            if rsv and float(rsv) > 0 and float(rsv) != 1.0:
                return float(rsv)
            sys_dpi = cmds.mayaDpiSetting(query=True, systemDpi=True)
            if sys_dpi and float(sys_dpi) > 0:
                calc = round(float(sys_dpi) / 96.0, 2)
                if calc != 1.0:
                    return calc
    except Exception:
        pass

    # 2. Qt Screen DPI / devicePixelRatio (cursor position / active monitor)
    try:
        if not screen:
            cursor_pos = QtGui.QCursor.pos()
            try:
                screen = QtGui.QGuiApplication.screenAt(cursor_pos)
            except Exception:
                pass
        if not screen:
            try:
                screen = QtGui.QGuiApplication.primaryScreen()
            except Exception:
                pass

        if screen:
            # Check devicePixelRatio first (most accurate for high-DPI in Qt5/Qt6)
            dpr = screen.devicePixelRatio()
            if dpr and float(dpr) > 1.0:
                return float(dpr)
            # Check logicalDotsPerInch
            dpi = screen.logicalDotsPerInch()
            if dpi and float(dpi) > 0:
                calc = round(float(dpi) / 96.0, 2)
                if calc != 1.0:
                    return calc
    except Exception:
        pass

    # 3. Windows API (multi-monitor or system DPI)
    if sys.platform == "win32":
        try:
            import ctypes
            try:
                dpi = ctypes.windll.user32.GetDpiForSystem()
                if dpi and dpi > 0:
                    calc = round(float(dpi) / 96.0, 2)
                    if calc != 1.0:
                        return calc
            except Exception:
                pass
            hdc = ctypes.windll.user32.GetDC(0)
            if hdc:
                dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)
                ctypes.windll.user32.ReleaseDC(0, hdc)
                if dpi and dpi > 0:
                    calc = round(float(dpi) / 96.0, 2)
                    if calc != 1.0:
                        return calc
        except Exception:
            pass

    return 1.0


# ----------------------------------------------------------------------
# Custom UI Components
# ----------------------------------------------------------------------
class ShelfButton(QtWidgets.QToolButton):
    """
    Custom shelf button:
    - Displays icon and optional overlay label with high contrast.
    - Implements 'cancel on drag-off' (moving cursor outside button cancels action).
    - Supports right-click context menu (sub-commands and deletion).
    - Supports double-click commands.
    """
    def __init__(self, button_data, shelf_index, button_index, shelf_manager, scale=1.0, parent=None):
        super(ShelfButton, self).__init__(parent)
        self.button_data = button_data
        self.shelf_index = shelf_index
        self.button_index = button_index
        self.shelf_manager = shelf_manager
        self.scale = scale
        self._is_pressed = False

        self.overlay_label = button_data.get("imageOverlayLabel", "")
        self.command = button_data.get("command", "")
        self.source_type = button_data.get("sourceType", "mel")
        self.double_click_command = button_data.get("doubleClickCommand", "")
        annotation = button_data.get("annotation", "") or button_data.get("label", "")
        
        self.setToolTip(annotation)
        btn_sz = max(24, int(round(38 * self.scale)))
        self.setFixedSize(btn_sz, btn_sz)
        self.setAutoRaise(True)
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

        icon_name = button_data.get("image", "commandButton.png")
        self._pixmap = get_maya_pixmap(icon_name)

    def paintEvent(self, event):
        super(ShelfButton, self).paintEvent(event)

        painter = None
        # Draw icon scaled to the full button with DPI and smooth filtering
        if self._pixmap and not self._pixmap.isNull():
            painter = QtGui.QPainter(self)
            painter.setRenderHint(QtGui.QPainter.Antialiasing)
            painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)

            rect = self.rect().adjusted(1, 1, -1, -1)
            if self.isDown():
                rect.adjust(1, 1, 1, 1)

            scaled_pix = self._pixmap.scaled(
                rect.size(),
                QtCore.Qt.KeepAspectRatio,
                QtCore.Qt.SmoothTransformation
            )
            target_x = rect.x() + (rect.width() - scaled_pix.width()) // 2
            target_y = rect.y() + (rect.height() - scaled_pix.height()) // 2
            painter.drawPixmap(target_x, target_y, scaled_pix)

        # Draw overlay label centered at bottom
        if self.overlay_label:
            if painter is None:
                painter = QtGui.QPainter(self)
            painter.setRenderHint(QtGui.QPainter.TextAntialiasing)

            font = painter.font()
            if hasattr(font, "setPointSizeF"):
                font.setPointSizeF(5.0 * self.scale)
            else:
                font.setPointSize(max(3, int(round(5.0 * self.scale))))
            font.setBold(True)
            painter.setFont(font)

            pad = max(1, int(round(2 * self.scale)))
            text_rect = self.rect().adjusted(pad, pad, -pad, -pad)
            if self.isDown():
                text_rect.adjust(1, 1, 1, 1)

            # High-contrast outline/shadow
            painter.setPen(QtGui.QColor(0, 0, 0, 220))
            offset = max(1, int(round(1 * self.scale)))
            for dx, dy in ((-offset, 0), (offset, 0), (0, -offset), (0, offset), (offset, offset)):
                painter.drawText(text_rect.translated(dx, dy), QtCore.Qt.AlignBottom | QtCore.Qt.AlignHCenter, self.overlay_label)

            # Bright foreground text
            painter.setPen(QtGui.QColor(255, 255, 255, 240))
            painter.drawText(text_rect, QtCore.Qt.AlignBottom | QtCore.Qt.AlignHCenter, self.overlay_label)

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self._is_pressed = True
        super(ShelfButton, self).mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton and self._is_pressed:
            self._is_pressed = False
            inside = self.rect().contains(event.pos())
            super(ShelfButton, self).mouseReleaseEvent(event)
            self.setDown(False)
            self.update()
            if inside:
                self.shelf_manager.execute_command(self.command, self.source_type)
            else:
                print(f"spShelf: Action '{self.overlay_label or 'Button'}' canceled (dragged off)")
            return
        super(ShelfButton, self).mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton and self.double_click_command:
            super(ShelfButton, self).mouseDoubleClickEvent(event)
            self.setDown(False)
            self.update()
            self.shelf_manager.execute_command(self.double_click_command, self.source_type)
            return
        super(ShelfButton, self).mouseDoubleClickEvent(event)

    def _show_context_menu(self, pos):
        menu = QtWidgets.QMenu(self)
        menu_items = self.button_data.get("menuItems", [])
        for item in menu_items:
            label = item.get("label", "Unnamed")
            cmd = item.get("command", "")
            action = menu.addAction(label)
            action.triggered.connect(lambda checked=False, c=cmd, t=self.source_type: self.shelf_manager.execute_command(c, t))

        if menu_items:
            menu.addSeparator()

        del_action = menu.addAction("Delete Button")
        del_action.triggered.connect(lambda: self.shelf_manager.confirm_and_delete_button(self.shelf_index, self.button_index))

        menu.exec_(self.mapToGlobal(pos))


class SeparatorWidget(QtWidgets.QFrame):
    """Separator line or dotted indicator for shelves."""
    def __init__(self, horizontal=False, dotted=False, shelf_index=0, item_index=0, shelf_manager=None, scale=1.0, parent=None):
        super(SeparatorWidget, self).__init__(parent)
        self.shelf_index = shelf_index
        self.item_index = item_index
        self.shelf_manager = shelf_manager
        self.horizontal = horizontal
        self.dotted = dotted
        self.scale = scale

        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

        btn_sz = max(24, int(round(38 * self.scale)))

        if dotted:
            layout = QtWidgets.QHBoxLayout(self) if horizontal else QtWidgets.QVBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(max(1, int(round(1 * self.scale))))
            lbl = QtWidgets.QLabel(". . . ." if horizontal else ".\n.\n.\n.")
            lbl.setAlignment(QtCore.Qt.AlignCenter)
            font_sz = max(8, int(round(10 * self.scale)))
            lbl.setStyleSheet(f"color: #777777; font-weight: bold; font-size: {font_sz}px;")
            layout.addWidget(lbl)
            if horizontal:
                self.setFixedHeight(max(8, int(round(12 * self.scale))))
            else:
                self.setFixedWidth(max(6, int(round(10 * self.scale))))
                self.setFixedHeight(btn_sz)
        else:
            if horizontal:
                self.setFixedHeight(max(4, int(round(8 * self.scale))))
            else:
                self.setFixedWidth(max(4, int(round(8 * self.scale))))
                self.setFixedHeight(btn_sz)
            self.setStyleSheet("background: transparent;")

    def paintEvent(self, event):
        if self.dotted:
            super(SeparatorWidget, self).paintEvent(event)
            return

        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, False)
        w = self.width()
        h = self.height()

        line_color = QtGui.QColor("#606060")
        line_w = max(1, int(round(1 * self.scale)))
        pen = QtGui.QPen(line_color, line_w)
        painter.setPen(pen)

        if self.horizontal:
            mid_y = h // 2
            pad_h = max(2, int(round(4 * self.scale)))
            painter.drawLine(pad_h, mid_y, w - pad_h, mid_y)
        else:
            mid_x = w // 2
            pad_v = max(2, int(round(4 * self.scale)))
            painter.drawLine(mid_x, pad_v, mid_x, h - pad_v)

    def _show_context_menu(self, pos):
        if not self.shelf_manager:
            return
        menu = QtWidgets.QMenu(self)
        del_action = menu.addAction("Delete Separator")
        del_action.triggered.connect(lambda: self.shelf_manager.confirm_and_delete_button(self.shelf_index, self.item_index))
        menu.exec_(self.mapToGlobal(pos))


class CollapsibleSection(QtWidgets.QWidget):
    """Collapsible container representing a single Maya shelf or Settings panel."""
    def __init__(self, title, collapsed=False, label_visible=True, on_collapse_changed=None, shelf_window=None, scale=1.0, parent=None):
        super(CollapsibleSection, self).__init__(parent)
        self.on_collapse_changed = on_collapse_changed
        self.shelf_window = shelf_window
        self._is_collapsed = collapsed
        self.scale = scale or (shelf_window.scale if shelf_window else 1.0)

        main_layout = QtWidgets.QVBoxLayout(self)
        margin_bottom = max(1, int(round(2 * self.scale)))
        main_layout.setContentsMargins(0, 0, 0, margin_bottom)
        main_layout.setSpacing(0)

        # Header bar
        self.header_btn = QtWidgets.QToolButton(self)
        self.header_btn.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.header_btn.setText(f" {title}")
        self.header_btn.setCheckable(True)
        self.header_btn.setChecked(not collapsed)
        self.header_btn.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        
        header_h = max(20, int(round(22 * self.scale)))
        self.header_btn.setFixedHeight(header_h)
        font_sz = max(9, int(round(11 * self.scale)))
        pad_l = max(3, int(round(4 * self.scale)))
        radius = max(1, int(round(2 * self.scale)))

        self.header_btn.setStyleSheet(f"""
            QToolButton {{
                background-color: #383838;
                border: 1px solid #2e2e2e;
                border-radius: {radius}px;
                color: #e0e0e0;
                font-weight: bold;
                font-size: {font_sz}px;
                text-align: left;
                padding-left: {pad_l}px;
            }}
            QToolButton:hover {{
                background-color: #444444;
            }}
        """)
        self.header_btn.clicked.connect(self._toggle_collapse)

        # Content container
        self.content_widget = QtWidgets.QWidget(self)
        self.content_layout = QtWidgets.QVBoxLayout(self.content_widget)
        pad = max(1, int(round(2 * self.scale)))
        self.content_layout.setContentsMargins(pad, pad, pad, pad)
        self.content_layout.setSpacing(pad)

        main_layout.addWidget(self.header_btn)
        main_layout.addWidget(self.content_widget)

        self.set_label_visible(label_visible)
        self._update_arrow()
        self.content_widget.setVisible(not self._is_collapsed)

    def _toggle_collapse(self):
        self._is_collapsed = not self.header_btn.isChecked()
        log_debug(f"CollapsibleSection '{self.header_btn.text()}': clicked -> is_collapsed={self._is_collapsed}")
        self.content_widget.setVisible(not self._is_collapsed)
        self._update_arrow()
        if self.on_collapse_changed:
            self.on_collapse_changed(self._is_collapsed)

        target_win = self.shelf_window or self.window()
        if hasattr(target_win, "adjust_size_to_content"):
            log_debug(f"CollapsibleSection notifying window: {target_win}")
            target_win.adjust_size_to_content()
        else:
            log_debug(f"CollapsibleSection: target_win ({target_win}) has NO adjust_size_to_content!")

    def _update_arrow(self):
        arrow = QtCore.Qt.DownArrow if not self._is_collapsed else QtCore.Qt.RightArrow
        self.header_btn.setArrowType(arrow)

    def set_label_visible(self, visible):
        if not visible and self._is_collapsed:
            self.set_collapsed(False)
        self.header_btn.setVisible(visible)

    def set_collapsed(self, collapsed):
        self._is_collapsed = collapsed
        self.header_btn.setChecked(not collapsed)
        self.content_widget.setVisible(not collapsed)
        self._update_arrow()
        target_win = self.shelf_window or self.window()
        if hasattr(target_win, "adjust_size_to_content"):
            target_win.adjust_size_to_content()


class AdaptiveScrollArea(QtWidgets.QScrollArea):
    """ScrollArea whose sizeHint dynamically adapts to its child widget."""
    def __init__(self, parent=None, scale=1.0):
        super(AdaptiveScrollArea, self).__init__(parent)
        self.scale = scale

    def sizeHint(self):
        if self.widget():
            w_hint = self.widget().sizeHint()
            f = self.frameWidth() * 2
            return QtCore.QSize(w_hint.width() + f, w_hint.height() + f)
        return super(AdaptiveScrollArea, self).sizeHint()

    def minimumSizeHint(self):
        return QtCore.QSize(max(80, int(round(100 * self.scale))), max(24, int(round(30 * self.scale))))


# ----------------------------------------------------------------------
# Main Shelf Window (Pure Qt)
# ----------------------------------------------------------------------
class SpShelfWindow(QtWidgets.QWidget):
    """
    Main floating shelf window.
    - Kept in memory (Singleton cache) for instant 0ms show/hide.
    - Seamlessly clamps inside the monitor under mouse cursor.
    - Full DPI and interface scaling support.
    """
    def __init__(self, manager, parent=None):
        # Clean up any leftover window instances from module reloads
        for widget in QtWidgets.QApplication.topLevelWidgets():
            if widget.objectName() == "sp_shelf_window_qt":
                try:
                    widget.close()
                    widget.deleteLater()
                except Exception:
                    pass

        super(SpShelfWindow, self).__init__(parent or get_maya_main_window())
        self.manager = manager
        self.scale = self.manager.get_ui_scale()
        self.shelf_sections = []
        self.setObjectName("sp_shelf_window_qt")
        self.setWindowTitle("spShelf")

        self._configure_window_flags()
        self._setup_ui()
        self._apply_stylesheet()

    def _configure_window_flags(self):
        hide_title_bar = self.manager.settings.get("HIDE_TITLE_BAR", False)
        if hide_title_bar:
            # Frameless Tool gives instant 0ms appearance with no Windows DWM animation
            self.setWindowFlags(QtCore.Qt.Tool | QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint)
        else:
            self.setWindowFlags(QtCore.Qt.Tool | QtCore.Qt.WindowStaysOnTopHint)

    def _apply_stylesheet(self):
        s = self.scale
        font_sz = max(9, int(round(11 * s)))
        chk_sz = max(12, int(round(14 * s)))
        chk_spacing = max(4, int(round(6 * s)))
        btn_pad_v = max(2, int(round(4 * s)))
        btn_pad_h = max(4, int(round(6 * s)))
        radius_sm = max(1, int(round(2 * s)))
        radius_md = max(2, int(round(3 * s)))
        radius_lg = max(3, int(round(4 * s)))
        scrollbar_w = max(7, int(round(8 * s)))
        scrollbar_min_h = max(16, int(round(20 * s)))
        input_pad_v = max(2, int(round(2 * s)))
        input_pad_h = max(4, int(round(6 * s)))
        combo_drop_w = max(14, int(round(16 * s)))
        arrow_w = max(3, int(round(3 * s)))
        arrow_h = max(4, int(round(4 * s)))
        arrow_margin = max(2, int(round(2 * s)))
        menu_pad = max(2, int(round(4 * s)))
        menu_item_pad_v = max(2, int(round(4 * s)))
        menu_item_pad_h = max(10, int(round(16 * s)))

        self.setStyleSheet(f"""
            QWidget#sp_shelf_window_qt {{
                background-color: #262626;
                border: 1px solid #454545;
                border-radius: {radius_lg}px;
            }}
            QScrollArea {{
                background: transparent;
                border: none;
            }}
            ShelfButton, QToolButton {{
                background-color: transparent;
                border: 1px solid transparent;
                border-radius: {radius_md}px;
                padding: 0px;
                margin: 0px;
            }}
            ShelfButton:hover, QToolButton:hover {{
                background-color: #444444;
                border: 1px solid #606060;
            }}
            ShelfButton:pressed, QToolButton:pressed {{
                background-color: #1f1f1f;
                border: 1px solid #333333;
                padding: 1px 0px 0px 1px;
            }}
            ShelfButton:focus, QToolButton:focus {{
                outline: none;
            }}
            QCheckBox {{
                color: #cccccc;
                font-size: {font_sz}px;
                spacing: {chk_spacing}px;
            }}
            QCheckBox::indicator {{
                width: {chk_sz}px;
                height: {chk_sz}px;
            }}
            QSpinBox {{
                background-color: #1e1e1e;
                color: #ffffff;
                border: 1px solid #444444;
                border-radius: {radius_sm}px;
                padding: {input_pad_v}px {input_pad_h}px;
                font-size: {font_sz}px;
            }}
            QSpinBox:hover {{
                border-color: #606060;
            }}
            QComboBox {{
                background-color: #1e1e1e;
                color: #ffffff;
                border: 1px solid #444444;
                border-radius: {radius_sm}px;
                padding: {input_pad_v}px {input_pad_h}px;
                font-size: {font_sz}px;
            }}
            QComboBox:hover {{
                border-color: #606060;
            }}
            QComboBox::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: {combo_drop_w}px;
                border-left: 1px solid #383838;
            }}
            QComboBox::down-arrow {{
                width: 0;
                height: 0;
                border-left: {arrow_w}px solid transparent;
                border-right: {arrow_w}px solid transparent;
                border-top: {arrow_h}px solid #cccccc;
                margin-right: {arrow_margin}px;
            }}
            QComboBox QAbstractItemView {{
                background-color: #262626;
                color: #ffffff;
                selection-background-color: #005f52;
                selection-color: #ffffff;
                border: 1px solid #444444;
                font-size: {font_sz}px;
            }}
            QPushButton {{
                background-color: #383838;
                color: #e0e0e0;
                border: 1px solid #484848;
                border-radius: {radius_sm}px;
                padding: {btn_pad_v}px {btn_pad_h}px;
                font-size: {font_sz}px;
            }}
            QPushButton:hover {{
                background-color: #4c4c4c;
            }}
            QScrollBar:vertical {{
                background: #202020;
                width: {scrollbar_w}px;
                margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: #505050;
                min-height: {scrollbar_min_h}px;
                border-radius: {radius_lg}px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QMenu {{
                background-color: #2b2b2b;
                color: #e0e0e0;
                border: 1px solid #444444;
                padding: {menu_pad}px;
                font-size: {font_sz}px;
            }}
            QMenu::item {{
                padding: {menu_item_pad_v}px {menu_item_pad_h}px;
            }}
            QMenu::item:selected {{
                background-color: #005f52;
            }}
        """)

    def _setup_ui(self):
        root_layout = QtWidgets.QVBoxLayout(self)
        root_pad = max(2, int(round(4 * self.scale)))
        root_layout.setContentsMargins(root_pad, root_pad, root_pad, root_pad)
        root_layout.setSpacing(root_pad)

        # Scroll area for multi-shelf scalability
        self.scroll_area = AdaptiveScrollArea(self, scale=self.scale)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)

        self.container = QtWidgets.QWidget()
        self.container_layout = QtWidgets.QVBoxLayout(self.container)
        self.container_layout.setContentsMargins(0, 0, 0, 0)
        self.container_layout.setSpacing(root_pad)

        self.scroll_area.setWidget(self.container)
        root_layout.addWidget(self.scroll_area)

        self.rebuild_content()

    def update_scale(self, new_scale=None):
        """Updates the scale factor and refreshes styling and layouts."""
        if new_scale is not None:
            self.scale = new_scale
        else:
            self.scale = self.manager.get_ui_scale()

        self.scroll_area.scale = self.scale
        root_pad = max(2, int(round(4 * self.scale)))
        self.layout().setContentsMargins(root_pad, root_pad, root_pad, root_pad)
        self.layout().setSpacing(root_pad)
        self.container_layout.setSpacing(root_pad)
        self._apply_stylesheet()
        self.rebuild_content()

    def rebuild_content(self):
        """Clears and re-populates shelves and settings widgets."""
        # Clear existing items
        self.shelf_sections = []
        while self.container_layout.count():
            item = self.container_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        # Build Shelves
        col_count = max(1, self.manager.settings.get("COLUMN_COUNT", 4))
        show_separators = self.manager.settings.get("SHOW_SEPARATORS", True)
        horizontal_sep = self.manager.settings.get("HORIZONTAL_SEPARATORS", False)
        dotted_sep = self.manager.settings.get("DOTTED_SEPARATORS", False)
        global_label_vis = self.manager.settings.get("SHOW_FRAME_LABEL", True)

        for shelf_idx, shelf in enumerate(self.manager.shelves):
            shelf_name = shelf.get("name", f"Shelf {shelf_idx+1}")
            is_collapsed = shelf.get("collapsed", False)
            label_vis = shelf.get("label_visible", global_label_vis)
            if not label_vis:
                is_collapsed = False

            section = CollapsibleSection(
                title=shelf_name,
                collapsed=is_collapsed,
                label_visible=label_vis,
                on_collapse_changed=lambda col, idx=shelf_idx: self.manager.on_shelf_collapse(idx, col),
                shelf_window=self,
                scale=self.scale,
                parent=self.container
            )
            self.shelf_sections.append(section)

            # Header context menu
            section.header_btn.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
            section.header_btn.customContextMenuRequested.connect(
                lambda pos, idx=shelf_idx, sec=section: self._show_shelf_header_menu(pos, idx, sec, sec.header_btn)
            )

            # Grid layout for buttons
            grid_widget = QtWidgets.QWidget(section.content_widget)
            grid_widget.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
            grid_widget.customContextMenuRequested.connect(
                lambda pos, idx=shelf_idx, sec=section, gw=grid_widget: self._show_shelf_header_menu(pos, idx, sec, gw)
            )
            grid = QtWidgets.QGridLayout(grid_widget)
            grid_pad = max(1, int(round(2 * self.scale)))
            grid.setContentsMargins(grid_pad, grid_pad, grid_pad, grid_pad)
            grid.setSpacing(grid_pad)
            grid.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
            grid.setColumnStretch(col_count, 1)

            cur_row = 0
            cur_col = 0

            for btn_idx, b in enumerate(shelf.get("buttons", [])):
                is_separator = (b.get("type") == "separator")

                if is_separator:
                    if not show_separators:
                        continue
                    sep = SeparatorWidget(
                        horizontal=horizontal_sep,
                        dotted=dotted_sep,
                        shelf_index=shelf_idx,
                        item_index=btn_idx,
                        shelf_manager=self.manager,
                        scale=self.scale,
                        parent=grid_widget
                    )
                    if horizontal_sep:
                        # Spans across all columns in row
                        if cur_col > 0:
                            cur_row += 1
                            cur_col = 0
                        grid.addWidget(sep, cur_row, 0, 1, col_count + 1)
                        cur_row += 1
                    else:
                        grid.addWidget(sep, cur_row, cur_col, QtCore.Qt.AlignHCenter)
                        cur_col += 1
                        if cur_col >= col_count:
                            cur_col = 0
                            cur_row += 1
                else:
                    btn = ShelfButton(
                        button_data=b,
                        shelf_index=shelf_idx,
                        button_index=btn_idx,
                        shelf_manager=self.manager,
                        scale=self.scale,
                        parent=grid_widget
                    )
                    grid.addWidget(btn, cur_row, cur_col)
                    cur_col += 1
                    if cur_col >= col_count:
                        cur_col = 0
                        cur_row += 1

            section.content_layout.addWidget(grid_widget)
            self.container_layout.addWidget(section)

        # Settings Section
        self._build_settings_section()
        self.container_layout.addStretch()

        self.adjust_size_to_content()

    def adjust_size_to_content(self):
        """Triggers size adjustment immediately and with a short deferral for Maya."""
        self._do_adjust_size()
        QtCore.QTimer.singleShot(10, self._do_adjust_size)

    def _do_adjust_size(self):
        """Dynamically adjusts the window height and width to fit the visible rollouts."""
        log_debug(f"_do_adjust_size: START. Current win size={self.width()}x{self.height()}")
        if self.container.layout():
            self.container.layout().activate()
        self.container.adjustSize()
        self.container.updateGeometry()
        self.scroll_area.updateGeometry()
        self.updateGeometry()
        self.layout().activate()

        container_hint = self.container.sizeHint()
        scroll_hint = self.scroll_area.sizeHint()
        hint = self.layout().sizeHint()
        log_debug(f"_do_adjust_size: container_hint={container_hint.width()}x{container_hint.height()}, "
                  f"scroll_hint={scroll_hint.width()}x{scroll_hint.height()}, "
                  f"win_hint={hint.width()}x{hint.height()}")

        # Multi-monitor bounds check
        cursor_pos = QtGui.QCursor.pos()
        screen = None
        try:
            screen = QtGui.QGuiApplication.screenAt(cursor_pos)
        except Exception:
            pass

        if screen:
            screen_geo = screen.availableGeometry()
        else:
            desktop = QtWidgets.QApplication.desktop()
            screen_num = desktop.screenNumber(cursor_pos)
            screen_geo = desktop.availableGeometry(screen_num)

        max_h = int(screen_geo.height() * 0.85)
        min_w = max(120, int(round(160 * self.scale)))
        target_w = max(hint.width(), min_w)
        target_h = min(hint.height(), max_h)

        # If expanding pushes below the monitor, shift window upward
        cur_x = self.x()
        cur_y = self.y()
        if cur_y + target_h > screen_geo.bottom():
            cur_y = max(screen_geo.top(), screen_geo.bottom() - target_h)
            self.move(cur_x, cur_y)

        log_debug(f"_do_adjust_size: calling self.resize({target_w}, {target_h})")
        self.resize(target_w, target_h)
        log_debug(f"_do_adjust_size: END. Result win size={self.width()}x{self.height()}")

    def _show_shelf_header_menu(self, pos, shelf_index, section, parent_widget=None):
        target = parent_widget or section.header_btn
        menu = QtWidgets.QMenu(target)
        vis = self.manager.shelves[shelf_index].get("label_visible", True)
        label_action = menu.addAction("Hide Label" if vis else "Show Label")
        label_action.triggered.connect(lambda: self.manager.toggle_single_shelf_label(shelf_index, not vis))

        del_action = menu.addAction("Delete Shelf")
        del_action.triggered.connect(lambda: self.manager.delete_shelf(shelf_index))

        menu.exec_(target.mapToGlobal(pos))

    def _build_settings_section(self):
        settings_collapsed = self.manager.settings.get("SETTINGS_COLLAPSED", True)
        settings_section = CollapsibleSection(
            title="Settings",
            collapsed=settings_collapsed,
            label_visible=True,
            on_collapse_changed=lambda col: self.manager.on_settings_collapse("SETTINGS_COLLAPSED", col),
            shelf_window=self,
            scale=self.scale,
            parent=self.container
        )

        layout = settings_section.content_layout
        btn_h = max(24, int(round(26 * self.scale)))
        font_sz = max(9, int(round(11 * self.scale)))

        # Add current shelf button
        add_shelf_btn = QtWidgets.QPushButton("Add Current Shelf", settings_section)
        add_shelf_btn.setStyleSheet(f"background-color: #005f52; font-weight: bold; min-height: {btn_h}px;")
        add_shelf_btn.setFixedHeight(btn_h)
        add_shelf_btn.clicked.connect(self.manager.add_current_shelf)
        layout.addWidget(add_shelf_btn)

        # UI Scale row
        scale_layout = QtWidgets.QHBoxLayout()
        scale_layout.setContentsMargins(0, 0, 0, 0)
        scale_layout.setSpacing(max(2, int(round(4 * self.scale))))

        scale_lbl = QtWidgets.QLabel("UI Scale:", settings_section)
        scale_lbl.setStyleSheet(f"color: #cccccc; font-size: {font_sz}px;")

        self.scale_combo = QtWidgets.QComboBox(settings_section)
        self.scale_combo.setFixedHeight(btn_h)
        self.scale_combo.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)

        sys_scale = self.manager.get_system_scale()
        sys_pct = int(round(sys_scale * 100))

        self.scale_combo.addItem(f"Auto (System: {sys_pct}%)", "auto")
        presets = [75, 100, 125, 150, 175, 200, 250, 300]

        scale_mode = self.manager.settings.get("SCALE_MODE", "auto")
        custom_val = self.manager.settings.get("CUSTOM_SCALE", 100)

        if custom_val not in presets and isinstance(custom_val, (int, float)):
            presets.append(int(custom_val))
            presets.sort()

        for val in presets:
            lbl = f"{val}% (Default)" if val == 100 else f"{val}%"
            self.scale_combo.addItem(lbl, val)

        if scale_mode == "auto":
            self.scale_combo.setCurrentIndex(0)
        else:
            found_idx = self.scale_combo.findData(custom_val)
            if found_idx != -1:
                self.scale_combo.setCurrentIndex(found_idx)
            else:
                self.scale_combo.setCurrentIndex(0)

        scale_layout.addWidget(scale_lbl)
        scale_layout.addWidget(self.scale_combo)
        layout.addLayout(scale_layout)

        # Columns count row
        col_layout = QtWidgets.QHBoxLayout()
        col_lbl = QtWidgets.QLabel("Columns count:", settings_section)
        col_lbl.setStyleSheet(f"color: #cccccc; font-size: {font_sz}px;")
        self.col_spin = QtWidgets.QSpinBox(settings_section)
        self.col_spin.setFixedHeight(btn_h)
        self.col_spin.setRange(1, 20)
        self.col_spin.setValue(self.manager.settings.get("COLUMN_COUNT", 4))
        col_layout.addWidget(col_lbl)
        col_layout.addWidget(self.col_spin)
        layout.addLayout(col_layout)

        # Checkboxes
        self.cb_close_repeat = QtWidgets.QCheckBox("Close on Key Release", settings_section)
        self.cb_close_repeat.setChecked(self.manager.settings.get("CLOSE_ON_REPEAT_FLAG", False))

        self.cb_under_cursor = QtWidgets.QCheckBox("Open under Cursor", settings_section)
        self.cb_under_cursor.setChecked(self.manager.settings.get("SHOW_WINDOW_UNDER_CURSOR", True))

        self.cb_show_label = QtWidgets.QCheckBox("Show Frame Label", settings_section)
        self.cb_show_label.setChecked(self.manager.settings.get("SHOW_FRAME_LABEL", True))
        self.cb_show_label.toggled.connect(self._on_toggle_show_frame_label)

        self.cb_hide_title = QtWidgets.QCheckBox("Hide Title Bar", settings_section)
        self.cb_hide_title.setChecked(self.manager.settings.get("HIDE_TITLE_BAR", False))

        self.cb_show_sep = QtWidgets.QCheckBox("Show Separators", settings_section)
        self.cb_show_sep.setChecked(self.manager.settings.get("SHOW_SEPARATORS", True))

        self.cb_horiz_sep = QtWidgets.QCheckBox("Horizontal Separators", settings_section)
        self.cb_horiz_sep.setChecked(self.manager.settings.get("HORIZONTAL_SEPARATORS", False))

        self.cb_dotted_sep = QtWidgets.QCheckBox("Dotted Style", settings_section)
        self.cb_dotted_sep.setChecked(self.manager.settings.get("DOTTED_SEPARATORS", False))

        for cb in [self.cb_close_repeat, self.cb_under_cursor, self.cb_show_label,
                   self.cb_hide_title, self.cb_show_sep, self.cb_horiz_sep, self.cb_dotted_sep]:
            layout.addWidget(cb)

        # Save Settings button
        save_btn = QtWidgets.QPushButton("Save Settings", settings_section)
        save_btn.setStyleSheet(f"background-color: #1a6d9e; font-weight: bold; min-height: {btn_h}px;")
        save_btn.setFixedHeight(btn_h)
        save_btn.clicked.connect(self._save_settings_from_ui)
        layout.addWidget(save_btn)

        # Delete All Shelves section
        del_collapsed = self.manager.settings.get("DELETE_COLLAPSED", True)
        del_section = CollapsibleSection(
            title="Delete All Shelves",
            collapsed=del_collapsed,
            label_visible=True,
            on_collapse_changed=lambda col: self.manager.on_settings_collapse("DELETE_COLLAPSED", col),
            shelf_window=self,
            scale=self.scale,
            parent=settings_section
        )
        del_all_btn = QtWidgets.QPushButton("Delete All Shelves", del_section)
        del_all_btn.setStyleSheet(f"background-color: #8c2a2a; color: white; font-weight: bold; min-height: {btn_h}px;")
        del_all_btn.setFixedHeight(btn_h)
        del_all_btn.clicked.connect(self.manager.delete_all_shelves)
        del_section.content_layout.addWidget(del_all_btn)
        layout.addWidget(del_section)

        self.container_layout.addWidget(settings_section)

    def _on_toggle_show_frame_label(self, checked):
        self.manager.toggle_frame_labels(checked)

    def update_frame_labels_visibility(self, visible):
        """Live updates header button visibility across all shelf sections without full rebuild."""
        for sec in self.shelf_sections:
            try:
                if not visible:
                    sec.set_collapsed(False)
                sec.set_label_visible(visible)
            except Exception:
                pass
        self.adjust_size_to_content()

    def _save_settings_from_ui(self):
        self.manager.settings["COLUMN_COUNT"] = self.col_spin.value()
        self.manager.settings["CLOSE_ON_REPEAT_FLAG"] = self.cb_close_repeat.isChecked()
        self.manager.settings["SHOW_WINDOW_UNDER_CURSOR"] = self.cb_under_cursor.isChecked()
        show_frame_label = self.cb_show_label.isChecked()
        self.manager.settings["SHOW_FRAME_LABEL"] = show_frame_label
        for shelf in self.manager.shelves:
            shelf["label_visible"] = show_frame_label
            if not show_frame_label:
                shelf["collapsed"] = False
        self.manager.settings["HIDE_TITLE_BAR"] = self.cb_hide_title.isChecked()
        self.manager.settings["SHOW_SEPARATORS"] = self.cb_show_sep.isChecked()
        self.manager.settings["HORIZONTAL_SEPARATORS"] = self.cb_horiz_sep.isChecked()
        self.manager.settings["DOTTED_SEPARATORS"] = self.cb_dotted_sep.isChecked()

        selected_data = self.scale_combo.itemData(self.scale_combo.currentIndex())
        if selected_data == "auto":
            self.manager.settings["SCALE_MODE"] = "auto"
        else:
            self.manager.settings["SCALE_MODE"] = "custom"
            self.manager.settings["CUSTOM_SCALE"] = int(selected_data)

        self.manager.save_user_data()
        self._configure_window_flags()
        self.update_scale()
        self.position_under_cursor()
        self.show()

    def position_under_cursor(self):
        """Calculates monitor boundaries and positions window centered on mouse cursor."""
        self.adjust_size_to_content()

        if not self.manager.settings.get("SHOW_WINDOW_UNDER_CURSOR", True):
            return

        cursor_pos = QtGui.QCursor.pos()

        # Multi-monitor detection
        screen = None
        try:
            screen = QtGui.QGuiApplication.screenAt(cursor_pos)
        except Exception:
            pass

        if screen:
            screen_geo = screen.availableGeometry()
        else:
            # Fallback for older Qt
            desktop = QtWidgets.QApplication.desktop()
            screen_num = desktop.screenNumber(cursor_pos)
            screen_geo = desktop.availableGeometry(screen_num)

        min_w = max(120, int(round(160 * self.scale)))
        min_h = max(30, int(round(40 * self.scale)))
        w = max(self.width(), min_w)
        h = max(self.height(), min_h)

        # Center on cursor
        target_x = cursor_pos.x() - (w // 2)
        target_y = cursor_pos.y() - (h // 2)

        # Clamp strictly inside monitor viewport
        target_x = max(screen_geo.left(), min(target_x, screen_geo.right() - w))
        target_y = max(screen_geo.top(), min(target_y, screen_geo.bottom() - h))

        self.move(target_x, target_y)


# ----------------------------------------------------------------------
# Manager Controller
# ----------------------------------------------------------------------
class SpShelf:
    DEFAULT_SETTINGS = {
        "COLUMN_COUNT": 4,
        "SCALE_MODE": "auto",
        "CUSTOM_SCALE": 100,
        "CLOSE_ON_REPEAT_FLAG": False,
        "SHOW_WINDOW_UNDER_CURSOR": True,
        "SHOW_FRAME_LABEL": True,
        "TOOLBOX_WINDOW_STYLE": False,
        "HIDE_TITLE_BAR": True,
        "SETTINGS_COLLAPSED": True,
        "DELETE_COLLAPSED": True,
        "SHOW_SEPARATORS": True,
        "HORIZONTAL_SEPARATORS": False,
        "DOTTED_SEPARATORS": False
    }

    def get_system_scale(self, screen=None):
        return get_system_scale(screen=screen)

    def get_ui_scale(self, screen=None):
        mode = self.settings.get("SCALE_MODE", "auto")
        if mode == "auto":
            return self.get_system_scale(screen=screen)
        custom_val = self.settings.get("CUSTOM_SCALE", 100)
        try:
            return max(0.5, min(4.0, float(custom_val) / 100.0))
        except (ValueError, TypeError):
            return 1.0

    def __init__(self):
        self.user_app_dir = cmds.internalVar(userAppDir=True)
        self.user_version = cmds.about(version=True)
        self.user_data_file = os.path.join(self.user_app_dir, self.user_version, 'scripts', 'sp_shelf_data.json')

        self.shelves = []
        self.settings = self.DEFAULT_SETTINGS.copy()
        self.load_user_data()

        # Cached Qt Window instance
        self.window_widget = None

    def load_user_data(self):
        """Loads shelves and settings from JSON file into memory."""
        if os.path.exists(self.user_data_file):
            try:
                with open(self.user_data_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.shelves = data.get("shelves", [])
                self.settings = data.get("settings", self.DEFAULT_SETTINGS)
                for k, v in self.DEFAULT_SETTINGS.items():
                    if k not in self.settings:
                        self.settings[k] = v
                if not self.settings.get("SHOW_FRAME_LABEL", True):
                    for shelf in self.shelves:
                        shelf["label_visible"] = False
                        shelf["collapsed"] = False
            except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
                cmds.warning(f"Resetting corrupted JSON file: {self.user_data_file}")
                self.save_user_data()
        else:
            self.shelves = []
            self.settings = self.DEFAULT_SETTINGS.copy()

    def save_user_data(self):
        """Persists current state to JSON."""
        data = {
            "shelves": self.shelves,
            "settings": self.settings
        }
        os.makedirs(os.path.dirname(self.user_data_file), exist_ok=True)
        with open(self.user_data_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

    def execute_command(self, command, source_type="mel"):
        if not isinstance(command, str) or not command.strip():
            cmds.warning("Invalid or empty command provided.")
            return
        try:
            try:
                command = command.encode('utf-8').decode('unicode_escape')
            except Exception:
                pass

            if source_type.lower() == "python":
                print(f"Executing Python command:\n{command}")
                exec(command, globals())
            else:
                print(f"Executing MEL command:\n{command}")
                mel.eval(command)
        except Exception as e:
            cmds.warning(f"Failed to execute command: {command}. Error: {e}")

    def on_shelf_collapse(self, shelf_index, collapsed):
        log_debug(f"on_shelf_collapse: shelf={shelf_index}, collapsed={collapsed}")
        if 0 <= shelf_index < len(self.shelves):
            self.shelves[shelf_index]["collapsed"] = collapsed
            self.save_user_data()
        if self.window_widget:
            self.window_widget.adjust_size_to_content()

    def on_settings_collapse(self, key, collapsed):
        log_debug(f"on_settings_collapse: key={key}, collapsed={collapsed}")
        self.settings[key] = collapsed
        self.save_user_data()
        if self.window_widget:
            self.window_widget.adjust_size_to_content()

    def toggle_frame_labels(self, visible):
        """Toggles header label visibility for all shelves and persists state."""
        self.settings["SHOW_FRAME_LABEL"] = visible
        for shelf in self.shelves:
            shelf["label_visible"] = visible
            if not visible:
                shelf["collapsed"] = False
        self.save_user_data()
        if self.window_widget:
            self.window_widget.update_frame_labels_visibility(visible)

    def toggle_single_shelf_label(self, shelf_index, visible):
        if 0 <= shelf_index < len(self.shelves):
            self.shelves[shelf_index]["label_visible"] = visible
            if not visible:
                self.shelves[shelf_index]["collapsed"] = False
            if all(s.get("label_visible", True) == visible for s in self.shelves):
                self.settings["SHOW_FRAME_LABEL"] = visible
            self.save_user_data()
            if self.window_widget:
                self.window_widget.rebuild_content()

    def delete_shelf(self, shelf_index):
        if 0 <= shelf_index < len(self.shelves):
            name = self.shelves[shelf_index].get("name", "shelf")
            res = cmds.confirmDialog(
                title="Delete Shelf",
                message=f"Delete shelf '{name}'?",
                button=["Yes", "No"],
                defaultButton="No",
                cancelButton="No",
                dismissString="No"
            )
            if res == "Yes":
                del self.shelves[shelf_index]
                self.save_user_data()
                if self.window_widget:
                    self.window_widget.rebuild_content()

    def confirm_and_delete_button(self, shelf_idx, button_idx):
        res = cmds.confirmDialog(
            title="Confirm Deletion",
            message="Are you sure you want to delete this item?",
            button=["Yes", "No"],
            defaultButton="No",
            cancelButton="No",
            dismissString="No"
        )
        if res == "Yes":
            if 0 <= shelf_idx < len(self.shelves):
                buttons = self.shelves[shelf_idx].get("buttons", [])
                if 0 <= button_idx < len(buttons):
                    del buttons[button_idx]
                    self.save_user_data()
                    if self.window_widget:
                        self.window_widget.rebuild_content()

    def delete_all_shelves(self):
        confirm = cmds.confirmDialog(
            title="Confirm Deletion",
            message="Are you sure you want to delete all shelves?",
            button=["Yes", "No"],
            defaultButton="No",
            cancelButton="No",
            dismissString="No"
        )
        if confirm == "Yes":
            self.shelves = []
            self.save_user_data()
            if self.window_widget:
                self.window_widget.rebuild_content()
            cmds.warning("All shelves have been deleted.")

    def _find_shelf_file(self, shelf_name):
        mel_filename = f"shelf_{shelf_name}.mel"
        search_dirs = []
        try:
            shelf_path_env = mel.eval('getenv "MAYA_SHELF_PATH"') or ''
        except Exception:
            shelf_path_env = os.environ.get('MAYA_SHELF_PATH', '')

        for p in shelf_path_env.split(';'):
            p = p.strip()
            if p:
                search_dirs.append(p)

        user_shelf_dir = cmds.internalVar(userShelfDir=True) or ''
        for p in user_shelf_dir.split(';'):
            p = p.strip()
            if p and p not in search_dirs:
                search_dirs.append(p)

        for directory in search_dirs:
            candidate = os.path.join(directory, mel_filename)
            if os.path.exists(candidate):
                return candidate
        return None

    def parse_shelf_file(self, shelf_file_path):
        buttons = []
        if not os.path.exists(shelf_file_path):
            cmds.warning(f"Shelf file not found: {shelf_file_path}")
            return buttons

        with open(shelf_file_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        button_data = {}
        for line in lines:
            line = line.strip()
            if line.startswith("shelfButton"):
                if button_data:
                    buttons.append(button_data)
                button_data = {}
            elif line.startswith("separator"):
                if button_data:
                    buttons.append(button_data)
                buttons.append({"type": "separator"})
                button_data = {}
            elif any(line.startswith(k) for k in ["-label", "-image", "-annotation", "-command", "-sourceType", "-doubleClickCommand"]):
                parts = line.split("\"", 1)
                if len(parts) > 1:
                    key = line.split()[0][1:]
                    button_data[key] = parts[1].rsplit("\"", 1)[0]
            elif line.startswith("-mi"):
                menu_item_parts = line.split("(", 1)
                if len(menu_item_parts) == 2:
                    label = menu_item_parts[0].split("\"")[1]
                    command = menu_item_parts[1].rsplit(")", 1)[0].strip().strip('"')
                    button_data.setdefault("menuItems", []).append({"label": label, "command": command})

        if button_data:
            buttons.append(button_data)

        return buttons

    def add_current_shelf(self):
        shelf = cmds.shelfTabLayout("ShelfLayout", query=True, selectTab=True)
        shelf_file = self._find_shelf_file(shelf)
        if not shelf_file:
            cmds.warning(f"Shelf file 'shelf_{shelf}.mel' not found in MAYA_SHELF_PATH.")
            return

        global_vis = self.settings.get("SHOW_FRAME_LABEL", True)
        self.shelves.append({
            "name": shelf,
            "buttons": self.parse_shelf_file(shelf_file),
            "collapsed": False,
            "label_visible": global_vis
        })
        self.save_user_data()
        if self.window_widget:
            self.window_widget.rebuild_content()
            self.window_widget.adjust_size_to_content()
        cmds.warning(f"Shelf '{shelf}' added successfully.")

    def show(self, close_on_repeat=False, reopen=False):
        """
        Main display function called by hotkey.
        - Supports Toggle mode (press to open, press again to close).
        - Supports Hold mode (press to open, release to close).
        - Re-uses cached QWidget instance for instant 0ms latency.
        """
        log_debug(f"SpShelf.show called: close_on_repeat={close_on_repeat}, reopen={reopen}, window_widget={self.window_widget}")
        # Ensure window widget exists
        if self.window_widget is None or reopen:
            if self.window_widget is not None:
                self.window_widget.close()
                self.window_widget.deleteLater()
            log_debug("Creating new SpShelfWindow instance...")
            self.window_widget = SpShelfWindow(self)

        # Handle Hold mode (Key Release)
        if close_on_repeat:
            if self.settings.get("CLOSE_ON_REPEAT_FLAG", False):
                self.window_widget.hide()
            return

        # Handle Toggle mode
        if not self.settings.get("CLOSE_ON_REPEAT_FLAG", False):
            if self.window_widget.isVisible():
                self.window_widget.hide()
                return

        # Check if scale needs update (e.g. monitor DPI change in Auto mode)
        target_scale = self.get_ui_scale()
        if abs(getattr(self.window_widget, "scale", 1.0) - target_scale) > 0.01:
            log_debug(f"Scale changed to {target_scale}, updating window...")
            self.window_widget.update_scale(target_scale)

        # Instant display under cursor
        self.window_widget.position_under_cursor()
        self.window_widget.show()
        self.window_widget.raise_()
        self.window_widget.activateWindow()


# ----------------------------------------------------------------------
# Singleton instance and public entry point
# ----------------------------------------------------------------------
_shelf_instance = SpShelf()

def sp_shelf_ui(close_on_repeat=False, reopen=False):
    """
    Main entry point for hotkey and menu integration.
    Compatible with previous versions of spShelf.
    """
    log_debug(f"sp_shelf_ui invoked (close_on_repeat={close_on_repeat}, reopen={reopen})")
    _shelf_instance.show(close_on_repeat=close_on_repeat, reopen=reopen)

log_debug("spShelf.py loaded successfully.")