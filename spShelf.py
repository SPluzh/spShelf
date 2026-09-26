# spShelf v2.3.6 (Pure Qt / PySide rewrite)
# v2.3.6 - Disabled debug output: set DEBUG = False, routed execution and cancel notifications to log_debug.
# v2.3.5 - Interactive instant save on clicking any settings checkbox in Settings section:
#          instantly persists settings to JSON and dynamically refreshes UI (separators, frame labels, title bar).
# v2.3.4 - Added "Add Empty Shelf" button in Settings and shelf rename capability.
#          Added visual empty shelf drop zone and placeholder in ShelfGridWidget.
# v2.3.3 - Fixed separator context menu background color: properly scoped SeparatorWidget style
#          to avoid cascading inheritance, ensuring standard Maya dark color #525252 for separator dropdown menus.
# v2.3.2 - Set standard Maya dark color #525252 for dropdown/popup menus and added configurable FONT_SIZE setting (default 13px).
# v2.3.1 - Fixed separator parsing when importing shelves from MEL (parse_shelf_file):
#          separator flags are no longer captured as button properties, preventing empty buttons.
#          Added self-healing filter in load_user_data for orphaned/empty button entries.
# v2.3.0 - Added interactive Button Editor dialog with real-time Live Preview,
#          theme styling, color pickers, script editing, and RMB popup menu editor.
# v2.2.4 - Added button width parsing from MEL shelves (-width, -w, -flexibleWidthType/Value)
#          and drag-and-drop extraction, supporting custom-width shelf buttons.
# v2.2.3 - Fixed multi-row shelf separator sizing: separators now always maintain compact width
#          and do not expand to button width or consume button column slots when shelves wrap across multiple rows.
# v2.2.2 - Added white triangle indicator in the bottom-right corner for shelf buttons
#          with custom drop-down / popup menu items, matching native Maya shelf behavior.
# v2.2.1 - Filter out Maya's internal default shelf button RMB popup items (/*dSBRMBMI*/ Open, Edit, Edit Popup, Delete)
#          when dragging buttons from native Maya shelves into spShelf.
# v2.2.0 - Added full support for shelf buttons with Option Box menu items (-mio / -menuItemWithOptionBox):
#          parses multi-command option box items, preserves optionBoxCommand, and provides an accessible
#          Options submenu in the button context menu.
# v2.1.9 - Fixed parsing of popup menu items (-mi) containing parentheses in labels,
#          added auto-unwrapping and native execution for Python commands wrapped in MEL python("..."),
#          and added dedicated per-item sourceType support and automatic self-healing for corrupted commands.
# v2.1.8 - Added reading and rendering of label color, label background, background transparency, and button background (if set).
# v2.1.7 - Removed WindowStaysOnTopHint, added "Move Shelf Up/Down" to shelf context menus, and increased max columns to 30.
# v2.1.6 - Added "Add Separator" option to shelf, button, and separator context menus.
# v2.1.5 - Added native Maya shelf drag-and-drop support:
#          MMB drag buttons from Maya standard shelves and Script Editor into spShelf.
# v2.1.4 - Added Middle Mouse Button (MMB) drag-and-drop support:
#          reorder buttons within a shelf and move buttons between shelves
#          with animated high-contrast insertion indicators and collapsed shelf drop/expand.
# v2.1.3 - Added floating island shelf toggle button (mel: ToggleShelf;) to the left of settings
#          with real-time Maya shelf visibility sync and High-DPI miniature shelf icon.
# v2.1.2 - Added compact top-right island settings button with toggleable rollout panel
#          and integrated multi-resolution High-DPI gear icons.
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
import math
import re
import maya.cmds as cmds
import maya.mel as mel


def extract_command_and_type(cmd_str):
    """
    Analyzes a command string and detects whether it is Python or MEL.
    Unwraps Python code if embedded inside MEL's python(...) syntax:
      e.g. python("import foo; foo.bar()") -> ('import foo; foo.bar()', 'python')
    """
    if not isinstance(cmd_str, str):
        return cmd_str, "mel"
    s = cmd_str.strip()
    if r'\"' in s:
        s = s.replace(r'\"', '"')
    if r'\\' in s:
        s = s.replace(r'\\', '\\')

    # Remove outer quotes if wrapped like "python(...)"
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        s = s[1:-1].strip()

    if (s.startswith('python("') and s.endswith('")')) or (s.startswith("python('") and s.endswith("')")):
        inner = s[8:-2].strip()
        inner = inner.replace(r'\"', '"').replace(r"\'", "'")
        return inner, "python"
    elif s.startswith("python(") and s.endswith(")"):
        inner = s[7:-1].strip()
        if (inner.startswith('"') and inner.endswith('"')) or (inner.startswith("'") and inner.endswith("'")):
            inner = inner[1:-1].strip()
            inner = inner.replace(r'\"', '"').replace(r"\'", "'")
            return inner, "python"
    return s, "mel"


def sanitize_command(cmd, label=""):
    """
    Cleans up command strings and repairs corrupted items caused by previous
    regex or split bugs (such as labels with parentheses bleeding into commands:
    e.g. 'Selected Only)" ( "python(...)').
    Returns (label, clean_command, source_type).
    """
    if not isinstance(cmd, str):
        return label, cmd, "mel"
    s = cmd.strip()
    if ')"' in s and '("' in s:
        parts = s.split(')"', 1)
        trailing_label = parts[0].strip()
        after = parts[1].strip()
        m = re.search(r'\(\s*["\']?([\s\S]*)', after)
        if m:
            inner = m.group(1).strip()
            if inner.endswith('")') and not inner.startswith('python("'):
                inner = inner[:-2].strip()
            elif inner.endswith('"') and not (inner.startswith('"') and len(inner) > 1):
                inner = inner[:-1].strip()
            new_label = f"{label.rstrip()} ({trailing_label})".strip() if trailing_label and label else label
            clean_cmd, cmd_type = extract_command_and_type(inner)
            return new_label, clean_cmd, cmd_type

    clean_cmd, cmd_type = extract_command_and_type(s)
    return label, clean_cmd, cmd_type


def is_default_maya_menu_item(m_cmd, m_label=""):
    """
    Checks if a popup menu item is one of Autodesk Maya's internal default shelfButton items
    (such as Open, Edit, Edit Popup, Delete) which Maya automatically creates in its native UI.
    """
    if not m_cmd:
        return False
    if "/*dSBRMBMI*/" in m_cmd:
        return True
    if "shelfEditorWindow" in m_cmd:
        return True
    if "shelfTabRefresh" in m_cmd and "deleteUI" in m_cmd:
        return True
    return False

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

DEBUG = False

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


def get_gear_pixmap(scale=1.0):
    """
    Locates the best matching high-DPI gear icon from disk, resources, or Maya.
    Checks gear_{14, 19, 24, 28, 38}.png based on scaled target size.
    """
    target_sz = max(10, int(round(14 * scale)))
    presets = [14, 19, 24, 28, 38]
    best_preset = min(presets, key=lambda s: abs(s - target_sz))

    search_dirs = [
        os.path.dirname(os.path.abspath(__file__)),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources", "icons"),
    ]

    # 1. Check exact or closest preset
    for d in search_dirs:
        cand = os.path.join(d, f"gear_{best_preset}.png")
        if os.path.exists(cand):
            pix = QtGui.QPixmap(cand)
            if not pix.isNull():
                return pix

    # 2. Try largest available for high quality downscaling
    for d in search_dirs:
        for p in reversed(presets):
            cand = os.path.join(d, f"gear_{p}.png")
            if os.path.exists(cand):
                pix = QtGui.QPixmap(cand)
                if not pix.isNull():
                    return pix

    # 3. Direct gear.png or settings.png in search directories
    for d in search_dirs:
        for name in ["gear.png", "settings.png", "gear_icon.png"]:
            cand = os.path.join(d, name)
            if os.path.exists(cand):
                pix = QtGui.QPixmap(cand)
                if not pix.isNull():
                    return pix

    # 4. Maya fallback icons
    for name in ["gear.png", "SP_Settings.png", "hotkeyFieldEditor.png"]:
        pix = get_maya_pixmap(name)
        if not pix.isNull():
            return pix

    return QtGui.QPixmap()


def get_shelf_pixmap(scale=1.0):
    """
    Locates the best matching shelf icon from disk, resources, or Maya Qt resources.
    Checks shelfTab.png, shelf.png, shelfEditor.png, etc.
    """
    search_dirs = [
        os.path.dirname(os.path.abspath(__file__)),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources", "icons"),
    ]

    for d in search_dirs:
        for name in ["shelf_toggle.png", "shelfTab.png", "shelf.png"]:
            cand = os.path.join(d, name)
            if os.path.exists(cand):
                pix = QtGui.QPixmap(cand)
                if not pix.isNull():
                    return pix

    for name in ["shelfTab.png", "shelf.png", "shelfEditor.png", "shelfLayout.png"]:
        pix = get_maya_pixmap(name)
        if not pix.isNull():
            return pix

    return QtGui.QPixmap()


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


def get_maya_dpi_scale():
    """
    Returns the interface scaling factor that Maya applies to its native UI controls.
    Used to unscale control dimensions queried from Maya UI (e.g. shelfButton width/height).
    """
    try:
        import maya.cmds as cmds
        if hasattr(cmds, "mayaDpiSetting"):
            rsv = cmds.mayaDpiSetting(query=True, realScaleValue=True)
            if rsv and float(rsv) > 0:
                return float(rsv)
    except Exception:
        pass
    try:
        return get_system_scale()
    except Exception:
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
    def __init__(self, button_data, shelf_index, button_index, shelf_manager, scale=1.0, is_preview=False, parent=None):
        super(ShelfButton, self).__init__(parent)
        self.button_data = button_data
        self.shelf_index = shelf_index
        self.button_index = button_index
        self.item_index = button_index
        self.shelf_manager = shelf_manager
        self.scale = scale
        self.is_preview = is_preview
        self._is_pressed = False
        self._mmb_pressed = False
        self._mmb_drag_start_pos = QtCore.QPoint()

        self.setAutoRaise(True)
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

        self.update_data(button_data)

    def update_data(self, button_data):
        """
        Updates button properties (labels, width, colors, icon, commands)
        from a data dictionary and triggers a repaint.
        """
        self.button_data = button_data
        self.overlay_label = button_data.get("imageOverlayLabel", "")
        self.command = button_data.get("command", "")
        self.source_type = button_data.get("sourceType", "mel")
        self.double_click_command = button_data.get("doubleClickCommand", "")
        annotation = button_data.get("annotation", "") or button_data.get("label", "")

        self.setToolTip(annotation)
        btn_sz = max(24, int(round(38 * self.scale)))
        btn_w = btn_sz
        raw_width = button_data.get("width")
        if raw_width is None and button_data.get("flexibleWidthType") == 2:
            raw_width = button_data.get("flexibleWidthValue")
        if raw_width is not None:
            try:
                w_val = int(raw_width)
                is_custom_type = (button_data.get("flexibleWidthType") == 2)
                # In Maya MEL, 34 and 35 are the default square shelf button widths.
                # If width is custom (e.g. 20, 50, 100) or explicitly flexibleWidthType 2, apply it.
                if w_val > 0 and (w_val not in (34, 35) or is_custom_type):
                    btn_w = max(12, int(round(w_val * self.scale)))
            except (ValueError, TypeError):
                pass
        self.setFixedSize(btn_w, btn_sz)

        # Colors from button data
        self.label_color = (
            button_data.get("labelColor")
            or button_data.get("label_color")
            or button_data.get("overlayLabelColor")
        )
        self.label_background = (
            button_data.get("labelBackground")
            or button_data.get("label_background")
        )
        if not self.label_background and "overlayLabelBackColor" in button_data:
            olb = button_data["overlayLabelBackColor"]
            if olb and len(olb) >= 3:
                self.label_background = olb[:3]

        self.background_transparency = (
            button_data.get("backgroundTransparency")
            if "backgroundTransparency" in button_data
            else button_data.get("background_transparency")
        )
        if self.background_transparency is None and "overlayLabelBackColor" in button_data:
            olb = button_data["overlayLabelBackColor"]
            if olb and len(olb) >= 4:
                self.background_transparency = olb[3]

        enable_bg = button_data.get("enableBackground")
        if enable_bg is False:
            self.button_background = None
        else:
            self.button_background = (
                button_data.get("buttonBackground")
                or button_data.get("button_background")
                or button_data.get("backgroundColor")
            )

        icon_name = button_data.get("image", "commandButton.png")
        self._pixmap = get_maya_pixmap(icon_name)
        self.update()

    @property
    def has_custom_menu(self):
        """Checks if the button has user-defined custom popup/dropdown menu items."""
        menu_items = self.button_data.get("menuItems")
        if not menu_items or not isinstance(menu_items, list):
            return False
        for item in menu_items:
            if not isinstance(item, dict):
                continue
            cmd = item.get("command", "")
            lbl = item.get("label", "")
            if not is_default_maya_menu_item(cmd, lbl) and (cmd or lbl):
                return True
        return False

    def get_corner_radius(self):
        """Returns the configured corner radius for shelf buttons from settings (default: 1px)."""
        if self.shelf_manager and hasattr(self.shelf_manager, "settings"):
            val = self.shelf_manager.settings.get("BUTTON_RADIUS")
            if val is None:
                val = self.shelf_manager.settings.get("BUTTON_CORNER_RADIUS", 1)
            try:
                return max(0, int(val))
            except (ValueError, TypeError):
                return 1
        return 1

    def paintEvent(self, event):
        super(ShelfButton, self).paintEvent(event)

        painter = None

        # 1. Custom button background (if set)
        if self.button_background and len(self.button_background) >= 3:
            if painter is None:
                painter = QtGui.QPainter(self)
                painter.setRenderHint(QtGui.QPainter.Antialiasing)
            r = max(0, min(255, int(self.button_background[0] * 255)))
            g = max(0, min(255, int(self.button_background[1] * 255)))
            b = max(0, min(255, int(self.button_background[2] * 255)))
            bg_color = QtGui.QColor(r, g, b, 230)
            if self.isDown():
                bg_color = bg_color.darker(130)
            elif self.underMouse():
                bg_color = bg_color.lighter(120)

            bg_rect = self.rect().adjusted(1, 1, -1, -1)
            if self.isDown():
                bg_rect.adjust(1, 1, 1, 1)

            btn_r = int(round(self.get_corner_radius() * self.scale))
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(QtGui.QBrush(bg_color))
            if btn_r > 0:
                painter.drawRoundedRect(bg_rect, btn_r, btn_r)
            else:
                painter.drawRect(bg_rect)

        # 2. Draw icon scaled to the full button with DPI and smooth filtering
        if self._pixmap and not self._pixmap.isNull():
            if painter is None:
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

        # 3. Draw overlay label centered at bottom
        if self.overlay_label:
            if painter is None:
                painter = QtGui.QPainter(self)
            painter.setRenderHint(QtGui.QPainter.TextAntialiasing)
            painter.setRenderHint(QtGui.QPainter.Antialiasing)

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

            # Determine text foreground color
            if self.label_color and len(self.label_color) >= 3:
                tr = max(0, min(255, int(self.label_color[0] * 255)))
                tg = max(0, min(255, int(self.label_color[1] * 255)))
                tb = max(0, min(255, int(self.label_color[2] * 255)))
                fg_color = QtGui.QColor(tr, tg, tb, 255)
            else:
                fg_color = QtGui.QColor(255, 255, 255, 240)

            # Draw label background box if defined
            has_solid_bg = False
            if self.label_background and len(self.label_background) >= 3:
                bg_alpha = 0.5
                if self.background_transparency is not None:
                    try:
                        bg_alpha = float(self.background_transparency)
                    except (ValueError, TypeError):
                        bg_alpha = 0.5
                if bg_alpha > 0.01:
                    fm = QtGui.QFontMetrics(font)
                    text_w = fm.horizontalAdvance(self.overlay_label) if hasattr(fm, "horizontalAdvance") else fm.width(self.overlay_label)
                    text_h = fm.height()
                    center_x = text_rect.center().x()
                    bottom_y = text_rect.bottom()
                    box_pad_x = max(1, int(round(2 * self.scale)))
                    box_pad_y = max(0, int(round(1 * self.scale)))
                    box_w = min(self.rect().width() - 2, text_w + box_pad_x * 2)
                    box_h = text_h + box_pad_y
                    box_x = max(1, center_x - box_w // 2)
                    box_y = bottom_y - box_h + 1
                    label_box = QtCore.QRect(box_x, box_y, box_w, box_h)

                    lr = max(0, min(255, int(self.label_background[0] * 255)))
                    lg = max(0, min(255, int(self.label_background[1] * 255)))
                    lb = max(0, min(255, int(self.label_background[2] * 255)))
                    la = max(0, min(255, int(bg_alpha * 255)))
                    painter.setPen(QtCore.Qt.NoPen)
                    painter.setBrush(QtGui.QBrush(QtGui.QColor(lr, lg, lb, la)))
                    painter.drawRect(label_box)
                    if bg_alpha > 0.6:
                        has_solid_bg = True

            # High-contrast outline/shadow (only if no solid label background)
            if not has_solid_bg:
                lum = 0.299 * fg_color.red() + 0.587 * fg_color.green() + 0.114 * fg_color.blue()
                shadow_color = QtGui.QColor(0, 0, 0, 220) if lum > 128 else QtGui.QColor(255, 255, 255, 180)
                painter.setPen(shadow_color)
                offset = max(1, int(round(1 * self.scale)))
                for dx, dy in ((-offset, 0), (offset, 0), (0, -offset), (0, offset), (offset, offset)):
                    painter.drawText(text_rect.translated(dx, dy), QtCore.Qt.AlignBottom | QtCore.Qt.AlignHCenter, self.overlay_label)

            # Bright foreground text
            painter.setPen(fg_color)
            painter.drawText(text_rect, QtCore.Qt.AlignBottom | QtCore.Qt.AlignHCenter, self.overlay_label)

        # 4. Custom popup/dropdown menu indicator (white triangle in bottom right corner)
        if self.has_custom_menu:
            if painter is None:
                painter = QtGui.QPainter(self)
            painter.setRenderHint(QtGui.QPainter.Antialiasing, True)

            tri_size = max(4.0, 5.0 * self.scale)
            margin = max(2.0, 2.5 * self.scale)
            down_offset = 1.0 if self.isDown() else 0.0

            br_x = float(self.rect().width()) - margin + down_offset
            br_y = float(self.rect().height()) - margin + down_offset

            # Subtle drop shadow for high contrast on light/white button icons
            shadow_offset = max(0.5, round(0.7 * self.scale))
            shadow_poly = QtGui.QPolygonF([
                QtCore.QPointF(br_x, br_y - tri_size),
                QtCore.QPointF(br_x, br_y),
                QtCore.QPointF(br_x - tri_size, br_y)
            ]).translated(shadow_offset, shadow_offset)
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(QtGui.QBrush(QtGui.QColor(0, 0, 0, 160)))
            painter.drawPolygon(shadow_poly)

            # Main white triangle with delicate dark border for maximum sharpness
            tri_poly = QtGui.QPolygonF([
                QtCore.QPointF(br_x, br_y - tri_size),
                QtCore.QPointF(br_x, br_y),
                QtCore.QPointF(br_x - tri_size, br_y)
            ])
            painter.setPen(QtGui.QPen(QtGui.QColor(25, 25, 25, 180), max(0.5, 0.6 * self.scale)))
            painter.setBrush(QtGui.QBrush(QtGui.QColor(255, 255, 255, 255)))
            painter.drawPolygon(tri_poly)

        if painter is not None:
            painter.end()

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MiddleButton:
            self._mmb_pressed = True
            pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
            self._mmb_drag_start_pos = pos
            return
        if event.button() == QtCore.Qt.LeftButton:
            self._is_pressed = True
        super(ShelfButton, self).mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if getattr(self, "is_preview", False):
            super(ShelfButton, self).mouseMoveEvent(event)
            return
        if getattr(self, "_mmb_pressed", False) and (event.buttons() & QtCore.Qt.MiddleButton):
            pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
            dist = (pos - self._mmb_drag_start_pos).manhattanLength()
            if dist >= QtWidgets.QApplication.startDragDistance():
                self._mmb_pressed = False
                self._start_drag(pos)
                return
        super(ShelfButton, self).mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.MiddleButton:
            self._mmb_pressed = False
            return
        if event.button() == QtCore.Qt.LeftButton and self._is_pressed:
            self._is_pressed = False
            inside = self.rect().contains(event.pos())
            super(ShelfButton, self).mouseReleaseEvent(event)
            self.setDown(False)
            self.update()
            if inside:
                if getattr(self, "is_preview", False):
                    log_debug(f"Preview button clicked: {self.overlay_label or 'Button'}")
                elif self.shelf_manager:
                    self.shelf_manager.execute_command(self.command, self.source_type)
            else:
                log_debug(f"Action '{self.overlay_label or 'Button'}' canceled (dragged off)")
            return
        super(ShelfButton, self).mouseReleaseEvent(event)

    def _start_drag(self, pos):
        if getattr(self, "is_preview", False):
            return
        drag = QtGui.QDrag(self)
        mime_data = QtCore.QMimeData()
        payload = {
            "source_shelf_idx": self.shelf_index,
            "source_item_idx": self.item_index
        }
        mime_data.setData("application/x-spshelf-item", QtCore.QByteArray(json.dumps(payload).encode("utf-8")))
        drag.setMimeData(mime_data)

        pixmap = self.grab()
        if not pixmap.isNull():
            transparent_pix = QtGui.QPixmap(pixmap.size())
            transparent_pix.fill(QtCore.Qt.transparent)
            painter = QtGui.QPainter(transparent_pix)
            painter.setOpacity(0.7)
            painter.drawPixmap(0, 0, pixmap)
            painter.end()
            drag.setPixmap(transparent_pix)
            hot_x = max(0, min(pixmap.width() - 1, pos.x()))
            hot_y = max(0, min(pixmap.height() - 1, pos.y()))
            drag.setHotSpot(QtCore.QPoint(hot_x, hot_y))

        drag_exec = getattr(drag, "exec", getattr(drag, "exec_", None))
        if drag_exec:
            drag_exec(QtCore.Qt.MoveAction)

    def mouseDoubleClickEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton and self.double_click_command:
            super(ShelfButton, self).mouseDoubleClickEvent(event)
            self.setDown(False)
            self.update()
            if not getattr(self, "is_preview", False) and self.shelf_manager:
                self.shelf_manager.execute_command(self.double_click_command, self.source_type)
            return
        super(ShelfButton, self).mouseDoubleClickEvent(event)

    def _show_context_menu(self, pos):
        parent_win = self.window() if self.window() else self
        menu = QtWidgets.QMenu(parent_win)
        menu_items = self.button_data.get("menuItems", [])
        opt_actions = []

        for item in menu_items:
            label = item.get("label", "Unnamed")
            cmd = item.get("command", "")
            item_source_type = item.get("sourceType")
            if not item_source_type:
                _, detected_type = extract_command_and_type(cmd)
                item_source_type = detected_type if detected_type == "python" else self.source_type
            action = menu.addAction(label)
            if getattr(self, "is_preview", False):
                action.triggered.connect(lambda checked=False, l=label: log_debug(f"[Preview] Triggered popup item: {l}"))
            elif self.shelf_manager:
                action.triggered.connect(lambda checked=False, c=cmd, t=item_source_type: self.shelf_manager.execute_command(c, t))

            opt_cmd = item.get("optionBoxCommand", "")
            if opt_cmd:
                opt_type = item.get("optionBoxSourceType")
                if not opt_type:
                    _, d_type = extract_command_and_type(opt_cmd)
                    opt_type = d_type if d_type == "python" else self.source_type
                opt_actions.append((label, opt_cmd, opt_type))

        if opt_actions:
            opt_menu = menu.addMenu(get_maya_icon("menuIconOptions.png"), "Options")
            for o_lbl, o_cmd, o_type in opt_actions:
                o_action = opt_menu.addAction(get_maya_icon("menuIconOptions.png"), f"{o_lbl} Options")
                if getattr(self, "is_preview", False):
                    o_action.triggered.connect(lambda checked=False, l=o_lbl: log_debug(f"[Preview] Triggered option box: {l}"))
                elif self.shelf_manager:
                    o_action.triggered.connect(lambda checked=False, c=o_cmd, t=o_type: self.shelf_manager.execute_command(c, t))

        if not getattr(self, "is_preview", False):
            if menu_items:
                menu.addSeparator()

            edit_action = menu.addAction(get_maya_icon("edit.png"), "Edit Button...")
            if self.shelf_manager:
                edit_action.triggered.connect(lambda: self.shelf_manager.open_button_editor(self.shelf_index, self.button_index))

            add_sep_action = menu.addAction("Add Separator")
            if self.shelf_manager:
                add_sep_action.triggered.connect(lambda: self.shelf_manager.add_separator(self.shelf_index, self.button_index + 1))

            menu.addSeparator()

            del_action = menu.addAction("Delete Button")
            if self.shelf_manager:
                del_action.triggered.connect(lambda: self.shelf_manager.confirm_and_delete_button(self.shelf_index, self.button_index))

        menu.exec_(self.mapToGlobal(pos))


# ----------------------------------------------------------------------
# Button Editor Components
# ----------------------------------------------------------------------
class ColorPickerButton(QtWidgets.QPushButton):
    """
    Compact button displaying a color swatch preview and hex/RGB label.
    Opens QColorDialog on click.
    Supports normalized RGB [r, g, b] (0.0 to 1.0) or None (transparent/default).
    """
    colorChanged = QtCore.Signal(object)  # Emits list [r, g, b] or None

    def __init__(self, initial_color=None, default_color=None, allow_reset=True, scale=1.0, parent=None):
        super(ColorPickerButton, self).__init__(parent)
        self.scale = scale
        self.allow_reset = allow_reset
        self.default_color = default_color
        self._normalized_rgb = None
        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.clicked.connect(self._pick_color)
        self.set_normalized_rgb(initial_color, emit=False)

    def _show_context_menu(self, pos):
        if not self.allow_reset:
            return
        parent_win = self.window() if self.window() else self
        menu = QtWidgets.QMenu(parent_win)
        reset_action = menu.addAction("Reset / Clear Color")
        reset_action.triggered.connect(lambda: self.set_normalized_rgb(self.default_color, emit=True))
        menu.exec_(self.mapToGlobal(pos))

    def _pick_color(self):
        initial = QtGui.QColor(255, 255, 255)
        if self._normalized_rgb and len(self._normalized_rgb) >= 3:
            r = int(round(self._normalized_rgb[0] * 255))
            g = int(round(self._normalized_rgb[1] * 255))
            b = int(round(self._normalized_rgb[2] * 255))
            initial = QtGui.QColor(r, g, b)

        dialog = QtWidgets.QColorDialog(initial, self)
        dialog.setWindowTitle("Select Color")
        exec_func = getattr(dialog, "exec", getattr(dialog, "exec_", None))
        if exec_func and exec_func() == QtWidgets.QDialog.Accepted:
            picked = dialog.selectedColor()
            if picked.isValid():
                norm_rgb = [
                    round(picked.redF(), 4),
                    round(picked.greenF(), 4),
                    round(picked.blueF(), 4)
                ]
                self.set_normalized_rgb(norm_rgb, emit=True)

    def get_normalized_rgb(self):
        return self._normalized_rgb

    def set_normalized_rgb(self, rgb_list, emit=True):
        if rgb_list and len(rgb_list) >= 3:
            try:
                self._normalized_rgb = [
                    round(max(0.0, min(1.0, float(rgb_list[0]))), 4),
                    round(max(0.0, min(1.0, float(rgb_list[1]))), 4),
                    round(max(0.0, min(1.0, float(rgb_list[2]))), 4)
                ]
            except (ValueError, TypeError):
                self._normalized_rgb = None
        else:
            self._normalized_rgb = None

        self._update_appearance()
        if emit:
            self.colorChanged.emit(self._normalized_rgb)

    def _update_appearance(self):
        sz = max(14, int(round(16 * self.scale)))
        pix = QtGui.QPixmap(sz, sz)

        if self._normalized_rgb:
            r = int(round(self._normalized_rgb[0] * 255))
            g = int(round(self._normalized_rgb[1] * 255))
            b = int(round(self._normalized_rgb[2] * 255))
            pix.fill(QtGui.QColor(r, g, b))
            painter = QtGui.QPainter(pix)
            painter.setPen(QtGui.QPen(QtGui.QColor(90, 90, 90), 1))
            painter.drawRect(0, 0, sz - 1, sz - 1)
            painter.end()
            self.setIcon(QtGui.QIcon(pix))
            self.setIconSize(QtCore.QSize(sz, sz))
            self.setText(f" #{r:02X}{g:02X}{b:02X}")
        else:
            pix.fill(QtGui.QColor(55, 55, 55))
            painter = QtGui.QPainter(pix)
            painter.setPen(QtGui.QPen(QtGui.QColor(160, 60, 60), 2))
            painter.drawLine(2, 2, sz - 3, sz - 3)
            painter.drawLine(2, sz - 3, sz - 3, 2)
            painter.end()
            self.setIcon(QtGui.QIcon(pix))
            self.setIconSize(QtCore.QSize(sz, sz))
            self.setText(" None / Default")


class CodeEditorWidget(QtWidgets.QPlainTextEdit):
    """
    Monospace script editor with 4-space tab indentation.
    """
    def __init__(self, scale=1.0, parent=None):
        super(CodeEditorWidget, self).__init__(parent)
        self.scale = scale
        font = QtGui.QFont("Consolas")
        font.setStyleHint(QtGui.QFont.Monospace)
        font.setPointSize(max(9, int(round(10 * self.scale))))
        self.setFont(font)

        metrics = QtGui.QFontMetricsF(font)
        space_w = metrics.horizontalAdvance(" ") if hasattr(metrics, "horizontalAdvance") else metrics.width(" ")
        tab_dist = max(16, int(round(space_w * 4)))
        if hasattr(self, "setTabStopDistance"):
            self.setTabStopDistance(tab_dist)
        else:
            self.setTabStopWidth(tab_dist)

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Tab and not (event.modifiers() & QtCore.Qt.ControlModifier):
            self.insertPlainText("    ")
            return
        super(CodeEditorWidget, self).keyPressEvent(event)


class PopupMenuEditorTab(QtWidgets.QWidget):
    """
    Editor tab for RMB popup menu items with Add, Delete, Up, Down,
    label, command, sourceType, optionBoxCommand, and optionBoxSourceType.
    """
    itemsChanged = QtCore.Signal()

    def __init__(self, initial_items=None, scale=1.0, parent=None):
        super(PopupMenuEditorTab, self).__init__(parent)
        self.scale = scale
        self.items_data = []
        if initial_items and isinstance(initial_items, list):
            self.items_data = [dict(item) for item in initial_items if isinstance(item, dict)]

        self._current_row = -1
        self._loading = False
        self._setup_ui()
        self._refresh_list(select_row=0 if self.items_data else -1)

    def _setup_ui(self):
        root_layout = QtWidgets.QHBoxLayout(self)
        root_pad = max(6, int(round(8 * self.scale)))
        root_layout.setContentsMargins(root_pad, root_pad, root_pad, root_pad)
        root_layout.setSpacing(root_pad)

        # Left panel: list and controls
        left_container = QtWidgets.QWidget(self)
        left_layout = QtWidgets.QVBoxLayout(left_container)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(max(4, int(round(6 * self.scale))))

        list_lbl = QtWidgets.QLabel("Menu Items (RMB):", left_container)
        list_lbl.setStyleSheet("font-weight: bold;")
        left_layout.addWidget(list_lbl)

        self.list_widget = QtWidgets.QListWidget(left_container)
        self.list_widget.currentRowChanged.connect(self._on_row_changed)
        left_layout.addWidget(self.list_widget)

        btn_grid = QtWidgets.QGridLayout()
        btn_grid.setSpacing(max(3, int(round(4 * self.scale))))

        self.add_btn = QtWidgets.QPushButton("+ Add Item", left_container)
        self.add_btn.clicked.connect(self._on_add_item)
        self.del_btn = QtWidgets.QPushButton("- Delete", left_container)
        self.del_btn.clicked.connect(self._on_delete_item)
        self.up_btn = QtWidgets.QPushButton("▲ Up", left_container)
        self.up_btn.clicked.connect(self._on_move_up)
        self.down_btn = QtWidgets.QPushButton("▼ Down", left_container)
        self.down_btn.clicked.connect(self._on_move_down)

        btn_grid.addWidget(self.add_btn, 0, 0)
        btn_grid.addWidget(self.del_btn, 0, 1)
        btn_grid.addWidget(self.up_btn, 1, 0)
        btn_grid.addWidget(self.down_btn, 1, 1)
        left_layout.addLayout(btn_grid)

        root_layout.addWidget(left_container, 1)

        # Right panel: detail editor
        self.detail_group = QtWidgets.QGroupBox("Selected Item Properties", self)
        detail_layout = QtWidgets.QVBoxLayout(self.detail_group)
        detail_pad = max(6, int(round(8 * self.scale)))
        detail_layout.setContentsMargins(detail_pad, detail_pad, detail_pad, detail_pad)
        detail_layout.setSpacing(max(6, int(round(8 * self.scale))))

        # Item Label & Language form
        form_layout = QtWidgets.QFormLayout()
        form_layout.setSpacing(max(4, int(round(6 * self.scale))))

        self.item_label_edit = QtWidgets.QLineEdit(self.detail_group)
        self.item_label_edit.setPlaceholderText("Menu item label")
        self.item_label_edit.textChanged.connect(self._on_field_changed)
        form_layout.addRow("Label:", self.item_label_edit)

        self.item_lang_combo = QtWidgets.QComboBox(self.detail_group)
        self.item_lang_combo.addItems(["python", "mel"])
        self.item_lang_combo.currentIndexChanged.connect(self._on_field_changed)
        form_layout.addRow("Language:", self.item_lang_combo)

        detail_layout.addLayout(form_layout)

        # Command code editor
        cmd_lbl = QtWidgets.QLabel("Command (Script):", self.detail_group)
        detail_layout.addWidget(cmd_lbl)

        self.item_cmd_edit = CodeEditorWidget(scale=self.scale, parent=self.detail_group)
        self.item_cmd_edit.textChanged.connect(self._on_field_changed)
        self.item_cmd_edit.setMinimumHeight(max(70, int(round(90 * self.scale))))
        detail_layout.addWidget(self.item_cmd_edit, 1)

        # Option Box Group
        self.opt_box_group = QtWidgets.QGroupBox("Option Box (Settings Window)", self.detail_group)
        opt_layout = QtWidgets.QVBoxLayout(self.opt_box_group)
        opt_layout.setContentsMargins(detail_pad, detail_pad, detail_pad, detail_pad)
        opt_layout.setSpacing(max(4, int(round(6 * self.scale))))

        self.opt_enable_chk = QtWidgets.QCheckBox("Enable Option Box Command (-mio)", self.opt_box_group)
        self.opt_enable_chk.toggled.connect(self._on_opt_enable_toggled)
        opt_layout.addWidget(self.opt_enable_chk)

        opt_form = QtWidgets.QFormLayout()
        self.opt_lang_combo = QtWidgets.QComboBox(self.opt_box_group)
        self.opt_lang_combo.addItems(["python", "mel"])
        self.opt_lang_combo.currentIndexChanged.connect(self._on_field_changed)
        opt_form.addRow("Opt Lang:", self.opt_lang_combo)
        opt_layout.addLayout(opt_form)

        self.opt_cmd_edit = CodeEditorWidget(scale=self.scale, parent=self.opt_box_group)
        self.opt_cmd_edit.textChanged.connect(self._on_field_changed)
        self.opt_cmd_edit.setMinimumHeight(max(50, int(round(70 * self.scale))))
        opt_layout.addWidget(self.opt_cmd_edit, 1)

        detail_layout.addWidget(self.opt_box_group, 1)

        root_layout.addWidget(self.detail_group, 2)

    def _on_opt_enable_toggled(self, checked):
        self.opt_lang_combo.setEnabled(checked)
        self.opt_cmd_edit.setEnabled(checked)
        self._on_field_changed()

    def _on_field_changed(self):
        if self._loading or not (0 <= self._current_row < len(self.items_data)):
            return
        item = self.items_data[self._current_row]
        item["label"] = self.item_label_edit.text().strip()
        item["sourceType"] = self.item_lang_combo.currentText()
        item["command"] = self.item_cmd_edit.toPlainText()

        if self.opt_enable_chk.isChecked():
            item["optionBoxCommand"] = self.opt_cmd_edit.toPlainText()
            item["optionBoxSourceType"] = self.opt_lang_combo.currentText()
        else:
            item.pop("optionBoxCommand", None)
            item.pop("optionBoxSourceType", None)

        # Update current list row label
        list_item = self.list_widget.item(self._current_row)
        if list_item:
            lbl = item.get("label") or "Unnamed"
            st = item.get("sourceType", "python").upper()
            opt_tag = "  [Opt]" if item.get("optionBoxCommand") else ""
            list_item.setText(f"{lbl}  [{st}]{opt_tag}")

        self.itemsChanged.emit()

    def _on_row_changed(self, row):
        if 0 <= row < len(self.items_data):
            self._current_row = row
            self._loading = True
            item = self.items_data[row]
            self.item_label_edit.setText(item.get("label", ""))
            st = item.get("sourceType", "python").lower()
            self.item_lang_combo.setCurrentText("mel" if st == "mel" else "python")
            self.item_cmd_edit.setPlainText(item.get("command", ""))

            opt_cmd = item.get("optionBoxCommand", "")
            has_opt = bool(opt_cmd)
            self.opt_enable_chk.setChecked(has_opt)
            self.opt_lang_combo.setEnabled(has_opt)
            self.opt_cmd_edit.setEnabled(has_opt)
            opt_st = item.get("optionBoxSourceType", "python").lower()
            self.opt_lang_combo.setCurrentText("mel" if opt_st == "mel" else "python")
            self.opt_cmd_edit.setPlainText(opt_cmd)

            self.detail_group.setEnabled(True)
            self._loading = False
        else:
            self._current_row = -1
            self._loading = True
            self.item_label_edit.clear()
            self.item_cmd_edit.clear()
            self.opt_cmd_edit.clear()
            self.opt_enable_chk.setChecked(False)
            self.opt_lang_combo.setEnabled(False)
            self.opt_cmd_edit.setEnabled(False)
            self.detail_group.setEnabled(False)
            self._loading = False

    def _on_add_item(self):
        new_item = {
            "label": f"Menu Item {len(self.items_data) + 1}",
            "command": "",
            "sourceType": "python"
        }
        self.items_data.append(new_item)
        self._refresh_list(select_row=len(self.items_data) - 1)
        self.itemsChanged.emit()

    def _on_delete_item(self):
        if 0 <= self._current_row < len(self.items_data):
            del self.items_data[self._current_row]
            next_row = max(0, min(self._current_row, len(self.items_data) - 1)) if self.items_data else -1
            self._refresh_list(select_row=next_row)
            self.itemsChanged.emit()

    def _on_move_up(self):
        if self._current_row > 0:
            r = self._current_row
            self.items_data[r], self.items_data[r - 1] = self.items_data[r - 1], self.items_data[r]
            self._refresh_list(select_row=r - 1)
            self.itemsChanged.emit()

    def _on_move_down(self):
        if 0 <= self._current_row < len(self.items_data) - 1:
            r = self._current_row
            self.items_data[r], self.items_data[r + 1] = self.items_data[r + 1], self.items_data[r]
            self._refresh_list(select_row=r + 1)
            self.itemsChanged.emit()

    def _refresh_list(self, select_row=-1):
        self._loading = True
        self.list_widget.clear()
        for item in self.items_data:
            lbl = item.get("label") or "Unnamed"
            st = item.get("sourceType", "python").upper()
            opt_tag = "  [Opt]" if item.get("optionBoxCommand") else ""
            self.list_widget.addItem(f"{lbl}  [{st}]{opt_tag}")
        self._loading = False

        if 0 <= select_row < len(self.items_data):
            self.list_widget.setCurrentRow(select_row)
        else:
            self._on_row_changed(-1)

    def get_items_data(self):
        clean_items = []
        for it in self.items_data:
            item_copy = {
                "label": it.get("label", "").strip(),
                "command": it.get("command", ""),
                "sourceType": it.get("sourceType", "python")
            }
            if it.get("optionBoxCommand"):
                item_copy["optionBoxCommand"] = it["optionBoxCommand"]
                item_copy["optionBoxSourceType"] = it.get("optionBoxSourceType", "python")
            clean_items.append(item_copy)
        return clean_items

    def set_items_data(self, items):
        self.items_data = [dict(it) for it in items if isinstance(it, dict)]
        self._refresh_list(select_row=0 if self.items_data else -1)


class ButtonEditorDialog(QtWidgets.QDialog):
    """
    Dedicated Shelf Button Editor Dialog with real-time Live Preview,
    Maya dark theme styling, High-DPI scaling, and 3 tabbed parameter sections:
    1. Appearance & Icon
    2. Commands (LMB Click and Double Click)
    3. Popup Menu Items (RMB Dropdown Commands)
    """
    def __init__(self, shelf_manager, shelf_index, button_index, button_data, scale=1.0, parent=None):
        super(ButtonEditorDialog, self).__init__(parent)
        self.shelf_manager = shelf_manager
        self.shelf_index = shelf_index
        self.button_index = button_index
        self.scale = scale
        self.initial_data = json.loads(json.dumps(button_data))
        self.current_data = json.loads(json.dumps(button_data))
        self._loading = False

        self.setObjectName("ButtonEditorDialog")
        btn_title = button_data.get("label") or button_data.get("imageOverlayLabel") or "Button"
        self.setWindowTitle(f"Edit Button: {btn_title}")
        self.setWindowFlags(QtCore.Qt.Window)

        self._setup_ui()
        self._apply_stylesheet()
        self._load_data(self.current_data)
        self._center_on_screen()

    def _setup_ui(self):
        s = self.scale
        root_pad = max(8, int(round(12 * s)))
        root_spacing = max(6, int(round(10 * s)))

        root_layout = QtWidgets.QVBoxLayout(self)
        root_layout.setContentsMargins(root_pad, root_pad, root_pad, root_pad)
        root_layout.setSpacing(root_spacing)

        # -------------------------------------------------------------
        # 1. LIVE PREVIEW AREA
        # -------------------------------------------------------------
        preview_box = QtWidgets.QGroupBox("Live Preview", self)
        preview_layout = QtWidgets.QVBoxLayout(preview_box)
        preview_layout.setContentsMargins(
            max(8, int(round(12 * s))),
            max(8, int(round(10 * s))),
            max(8, int(round(12 * s))),
            max(8, int(round(10 * s)))
        )
        preview_layout.setSpacing(max(4, int(round(6 * s))))

        # Shelf slot simulation container
        self.slot_tray = QtWidgets.QFrame(preview_box)
        self.slot_tray.setObjectName("preview_slot_tray")
        slot_tray_h = max(44, int(round(52 * s)))
        self.slot_tray.setFixedHeight(slot_tray_h)

        slot_layout = QtWidgets.QHBoxLayout(self.slot_tray)
        slot_layout.setContentsMargins(
            max(8, int(round(12 * s))),
            max(2, int(round(4 * s))),
            max(8, int(round(12 * s))),
            max(2, int(round(4 * s)))
        )
        slot_layout.setSpacing(max(6, int(round(8 * s))))

        self.preview_button = ShelfButton(
            button_data=self.current_data,
            shelf_index=-1,
            button_index=-1,
            shelf_manager=self.shelf_manager,
            scale=self.scale,
            is_preview=True,
            parent=self.slot_tray
        )
        slot_layout.addWidget(self.preview_button)

        preview_hint = QtWidgets.QLabel("(Interactive shelf slot: hover & click to test button states)", self.slot_tray)
        preview_hint.setStyleSheet("color: #777777; font-size: 15px; font-style: italic;")
        slot_layout.addWidget(preview_hint)
        slot_layout.addStretch()

        preview_layout.addWidget(self.slot_tray)

        # Info metadata badges
        badges_layout = QtWidgets.QHBoxLayout()
        badges_layout.setContentsMargins(2, 2, 2, 2)
        badges_layout.setSpacing(max(6, int(round(8 * s))))

        self.badge_size = QtWidgets.QLabel(preview_box)
        self.badge_size.setObjectName("preview_badge")
        self.badge_menu = QtWidgets.QLabel(preview_box)
        self.badge_menu.setObjectName("preview_badge")
        self.badge_lang = QtWidgets.QLabel(preview_box)
        self.badge_lang.setObjectName("preview_badge")
        self.badge_overlay = QtWidgets.QLabel(preview_box)
        self.badge_overlay.setObjectName("preview_badge")

        badges_layout.addWidget(self.badge_size)
        badges_layout.addWidget(self.badge_menu)
        badges_layout.addWidget(self.badge_lang)
        badges_layout.addWidget(self.badge_overlay)
        badges_layout.addStretch()

        preview_layout.addLayout(badges_layout)
        root_layout.addWidget(preview_box)

        # -------------------------------------------------------------
        # 2. TAB WIDGET
        # -------------------------------------------------------------
        self.tab_widget = QtWidgets.QTabWidget(self)
        root_layout.addWidget(self.tab_widget, 1)

        # --- Tab 1: Appearance & Icon ---
        tab1_scroll = QtWidgets.QScrollArea(self.tab_widget)
        tab1_scroll.setWidgetResizable(True)
        tab1_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)

        tab1_widget = QtWidgets.QWidget()
        tab1_form = QtWidgets.QFormLayout(tab1_widget)
        tab1_form_pad = max(8, int(round(12 * s)))
        tab1_form.setContentsMargins(tab1_form_pad, tab1_form_pad, tab1_form_pad, tab1_form_pad)
        tab1_form.setSpacing(max(6, int(round(8 * s))))

        # Icon row: thumbnail + line edit + Browse button
        icon_row = QtWidgets.QHBoxLayout()
        thumb_sz = max(28, int(round(34 * s)))
        self.icon_thumb = QtWidgets.QLabel(tab1_widget)
        self.icon_thumb.setFixedSize(thumb_sz, thumb_sz)
        self.icon_thumb.setAlignment(QtCore.Qt.AlignCenter)
        self.icon_thumb.setStyleSheet("background-color: #2b2b2b; border: 1px solid #444444;")
        icon_row.addWidget(self.icon_thumb)

        self.icon_edit = QtWidgets.QLineEdit(tab1_widget)
        self.icon_edit.setPlaceholderText("Icon file name, absolute path, or Maya resource (e.g. uvChooser.svg)")
        self.icon_edit.textChanged.connect(self._on_parameter_changed)
        icon_row.addWidget(self.icon_edit, 1)

        self.browse_icon_btn = QtWidgets.QPushButton("Browse...", tab1_widget)
        self.browse_icon_btn.clicked.connect(self._on_browse_icon)
        icon_row.addWidget(self.browse_icon_btn)
        tab1_form.addRow("Icon:", icon_row)

        # Overlay Label
        self.overlay_edit = QtWidgets.QLineEdit(tab1_widget)
        self.overlay_edit.setPlaceholderText("Short text overlaid on icon (e.g. ON, OFF, SEL)")
        self.overlay_edit.textChanged.connect(self._on_parameter_changed)
        tab1_form.addRow("Overlay Label:", self.overlay_edit)

        # Overlay Text Color
        text_color_row = QtWidgets.QHBoxLayout()
        self.text_color_btn = ColorPickerButton(default_color=None, scale=self.scale, parent=tab1_widget)
        self.text_color_btn.colorChanged.connect(self._on_parameter_changed)
        text_color_row.addWidget(self.text_color_btn, 1)
        clear_tc_btn = QtWidgets.QToolButton(tab1_widget)
        clear_tc_btn.setText("✕")
        clear_tc_btn.setToolTip("Reset to default white text")
        clear_tc_btn.clicked.connect(lambda: self.text_color_btn.set_normalized_rgb(None))
        text_color_row.addWidget(clear_tc_btn)
        tab1_form.addRow("Overlay Text Color:", text_color_row)

        # Label Background Color
        bg_color_row = QtWidgets.QHBoxLayout()
        self.label_bg_btn = ColorPickerButton(default_color=None, scale=self.scale, parent=tab1_widget)
        self.label_bg_btn.colorChanged.connect(self._on_parameter_changed)
        bg_color_row.addWidget(self.label_bg_btn, 1)
        clear_bg_btn = QtWidgets.QToolButton(tab1_widget)
        clear_bg_btn.setText("✕")
        clear_bg_btn.setToolTip("Clear background (outline mode)")
        clear_bg_btn.clicked.connect(lambda: self.label_bg_btn.set_normalized_rgb(None))
        bg_color_row.addWidget(clear_bg_btn)
        tab1_form.addRow("Label Back Color:", bg_color_row)

        # Label Background Alpha
        alpha_row = QtWidgets.QHBoxLayout()
        self.alpha_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal, tab1_widget)
        self.alpha_slider.setRange(0, 100)
        self.alpha_slider.setValue(90)
        self.alpha_slider.valueChanged.connect(self._on_alpha_slider_changed)
        alpha_row.addWidget(self.alpha_slider, 1)
        self.alpha_lbl = QtWidgets.QLabel("90%", tab1_widget)
        self.alpha_lbl.setFixedWidth(max(34, int(round(40 * s))))
        alpha_row.addWidget(self.alpha_lbl)
        tab1_form.addRow("Label Back Alpha:", alpha_row)

        # Custom Button Background
        btn_bg_row = QtWidgets.QHBoxLayout()
        self.enable_bg_chk = QtWidgets.QCheckBox("Enable custom button background", tab1_widget)
        self.enable_bg_chk.toggled.connect(self._on_enable_bg_toggled)
        btn_bg_row.addWidget(self.enable_bg_chk)
        self.btn_bg_btn = ColorPickerButton(default_color=[0.22, 0.22, 0.22], scale=self.scale, parent=tab1_widget)
        self.btn_bg_btn.colorChanged.connect(self._on_parameter_changed)
        btn_bg_row.addWidget(self.btn_bg_btn, 1)
        tab1_form.addRow("Button Background:", btn_bg_row)

        # Button Width
        width_col = QtWidgets.QVBoxLayout()
        self.radio_width_std = QtWidgets.QRadioButton("Standard Shelf Width (35 px / square)", tab1_widget)
        self.radio_width_std.setChecked(True)
        self.radio_width_std.toggled.connect(self._on_width_mode_changed)
        width_col.addWidget(self.radio_width_std)

        custom_w_row = QtWidgets.QHBoxLayout()
        self.radio_width_custom = QtWidgets.QRadioButton("Custom Width:", tab1_widget)
        self.radio_width_custom.toggled.connect(self._on_width_mode_changed)
        custom_w_row.addWidget(self.radio_width_custom)

        self.custom_width_spin = QtWidgets.QSpinBox(tab1_widget)
        self.custom_width_spin.setRange(12, 1200)
        self.custom_width_spin.setValue(35)
        self.custom_width_spin.setSuffix(" px")
        self.custom_width_spin.setEnabled(False)
        self.custom_width_spin.valueChanged.connect(self._on_parameter_changed)
        custom_w_row.addWidget(self.custom_width_spin, 1)
        width_col.addLayout(custom_w_row)
        tab1_form.addRow("Button Width:", width_col)

        # Internal Label / Name
        self.label_edit = QtWidgets.QLineEdit(tab1_widget)
        self.label_edit.setPlaceholderText("Internal identifier or label (e.g. TDH_ON)")
        self.label_edit.textChanged.connect(self._on_parameter_changed)
        tab1_form.addRow("Label / Name:", self.label_edit)

        # Annotation / Tooltip
        self.annotation_edit = QtWidgets.QLineEdit(tab1_widget)
        self.annotation_edit.setPlaceholderText("Tooltip text shown when hovering over the button")
        self.annotation_edit.textChanged.connect(self._on_parameter_changed)
        tab1_form.addRow("Tooltip (Annotation):", self.annotation_edit)

        tab1_scroll.setWidget(tab1_widget)
        self.tab_widget.addTab(tab1_scroll, "Appearance & Icon")

        # --- Tab 2: Commands ---
        tab2_widget = QtWidgets.QWidget()
        tab2_layout = QtWidgets.QVBoxLayout(tab2_widget)
        tab2_layout.setContentsMargins(tab1_form_pad, tab1_form_pad, tab1_form_pad, tab1_form_pad)
        tab2_layout.setSpacing(max(6, int(round(8 * s))))

        cmd_header = QtWidgets.QHBoxLayout()
        cmd_title = QtWidgets.QLabel("Command (Left Mouse Button Click):", tab2_widget)
        cmd_title.setStyleSheet("font-weight: bold;")
        cmd_header.addWidget(cmd_title)
        cmd_header.addStretch()

        lang_lbl = QtWidgets.QLabel("Language:", tab2_widget)
        cmd_header.addWidget(lang_lbl)
        self.cmd_lang_combo = QtWidgets.QComboBox(tab2_widget)
        self.cmd_lang_combo.addItems(["python", "mel"])
        self.cmd_lang_combo.currentIndexChanged.connect(self._on_parameter_changed)
        cmd_header.addWidget(self.cmd_lang_combo)
        tab2_layout.addLayout(cmd_header)

        self.cmd_editor = CodeEditorWidget(scale=self.scale, parent=tab2_widget)
        self.cmd_editor.setPlaceholderText("# Enter Python or MEL script executed on LMB click...")
        self.cmd_editor.textChanged.connect(self._on_parameter_changed)
        self.cmd_editor.setMinimumHeight(max(110, int(round(140 * s))))
        tab2_layout.addWidget(self.cmd_editor, 2)

        dc_title = QtWidgets.QLabel("Double-Click Command (optional):", tab2_widget)
        dc_title.setStyleSheet("font-weight: bold;")
        tab2_layout.addWidget(dc_title)

        self.double_click_editor = CodeEditorWidget(scale=self.scale, parent=tab2_widget)
        self.double_click_editor.setPlaceholderText("# Optional script executed on double-click...")
        self.double_click_editor.textChanged.connect(self._on_parameter_changed)
        self.double_click_editor.setMinimumHeight(max(60, int(round(80 * s))))
        tab2_layout.addWidget(self.double_click_editor, 1)

        self.tab_widget.addTab(tab2_widget, "Commands")

        # --- Tab 3: Popup Menu Items ---
        self.popup_menu_tab = PopupMenuEditorTab(
            initial_items=self.current_data.get("menuItems", []),
            scale=self.scale,
            parent=self.tab_widget
        )
        self.popup_menu_tab.itemsChanged.connect(self._on_parameter_changed)
        self.tab_widget.addTab(self.popup_menu_tab, "Popup Menu Items")

        # -------------------------------------------------------------
        # 3. BOTTOM BUTTONS BAR
        # -------------------------------------------------------------
        bottom_layout = QtWidgets.QHBoxLayout()
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(max(6, int(round(8 * s))))

        self.reset_btn = QtWidgets.QPushButton("Reset", self)
        self.reset_btn.setObjectName("reset_btn")
        self.reset_btn.setToolTip("Revert all parameters to initial values when dialog was opened")
        self.reset_btn.clicked.connect(self._on_reset_clicked)
        bottom_layout.addWidget(self.reset_btn)

        bottom_layout.addStretch()

        self.cancel_btn = QtWidgets.QPushButton("Cancel", self)
        self.cancel_btn.clicked.connect(self.reject)
        bottom_layout.addWidget(self.cancel_btn)

        self.save_btn = QtWidgets.QPushButton("Save", self)
        self.save_btn.setObjectName("save_btn")
        self.save_btn.setDefault(True)
        self.save_btn.clicked.connect(self._on_save_clicked)
        bottom_layout.addWidget(self.save_btn)

        root_layout.addLayout(bottom_layout)

    def _apply_stylesheet(self):
        s = self.scale
        font_sz = max(9, int(round(11 * s)))
        base_font_sz = 13
        if self.shelf_manager and hasattr(self.shelf_manager, "settings"):
            base_font_sz = self.shelf_manager.settings.get("FONT_SIZE", 13)
        try:
            base_font_sz = int(base_font_sz)
        except (ValueError, TypeError):
            base_font_sz = 13
        menu_font_sz = max(9, int(round(base_font_sz * s)))
        chk_sz = max(12, int(round(14 * s)))
        btn_pad_v = max(3, int(round(5 * s)))
        btn_pad_h = max(8, int(round(12 * s)))
        radius_sm = max(2, int(round(3 * s)))
        radius_md = max(3, int(round(4 * s)))
        menu_pad = max(2, int(round(4 * s)))
        menu_item_pad_v = max(2, int(round(4 * s)))
        menu_item_pad_h = max(10, int(round(16 * s)))

        btn_r_setting = 1
        if self.shelf_manager and hasattr(self.shelf_manager, "settings"):
            val = self.shelf_manager.settings.get("BUTTON_RADIUS")
            if val is None:
                val = self.shelf_manager.settings.get("BUTTON_CORNER_RADIUS", 1)
            try:
                btn_r_setting = max(0, int(val))
            except (ValueError, TypeError):
                btn_r_setting = 1
        btn_radius = int(round(btn_r_setting * s))

        self.setStyleSheet(f"""
            QDialog {{
                background-color: #373737;
                color: #e0e0e0;
                font-size: {font_sz}px;
            }}
            QGroupBox {{
                font-weight: bold;
                background-color: transparent;
                border: 1px solid #4a4a4a;
                margin-top: 10px;
                padding-top: 10px;
                color: #b8b8b8;
                font-size: {font_sz}px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 10px;
                padding: 0 4px;
                background-color: #373737;
                color: #cccccc;
            }}
            QFrame#preview_slot_tray {{
                background-color: #444444;
                border: 1px dashed #5a5a5a;
            }}
            QLabel#preview_badge {{
                background-color: #444444;
                color: #88c0d0;
                border: 1px solid #505050;
                padding: 2px 6px;
                font-size: {max(8, int(round(9.5 * s)))}px;
                font-weight: bold;
            }}
            QTabWidget::pane {{
                border: 1px solid #4e4e4e;
                background-color: #444444;
                top: -1px;
            }}
            QTabBar::tab {{
                background: #373737;
                color: #aaaaaa;
                padding: {btn_pad_v + 1}px {btn_pad_h}px;
                border: 1px solid #484848;
                border-bottom: none;
                margin-right: 2px;
                font-size: {font_sz}px;
            }}
            QTabBar::tab:selected {{
                background: #444444;
                color: #ffffff;
                border: 1px solid #4e4e4e;
                border-bottom: 1px solid #444444;
                font-weight: bold;
            }}
            QTabBar::tab:hover:!selected {{
                background: #404040;
                color: #dddddd;
            }}
            QLabel {{
                color: #cccccc;
                font-size: {font_sz}px;
            }}
            QLineEdit, QPlainTextEdit {{
                background-color: #2b2b2b;
                color: #ffffff;
                border: 1px solid #444444;
                padding: 3px 6px;
                font-size: {font_sz}px;
                selection-background-color: #5285a6;
            }}
            QLineEdit:focus, QPlainTextEdit:focus {{
                border: 1px solid #5285a6;
            }}
            QSpinBox, QComboBox {{
                background-color: #2b2b2b;
                color: #ffffff;
                border: 1px solid #444444;
                padding: 3px 6px;
                font-size: {font_sz}px;
            }}
            QSpinBox:focus, QComboBox:focus {{
                border: 1px solid #5285a6;
            }}
            QComboBox::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: {max(14, int(round(16 * s)))}px;
                border-left: 1px solid #444444;
            }}
            QComboBox::down-arrow {{
                width: 0;
                height: 0;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid #cccccc;
            }}
            QComboBox QAbstractItemView {{
                background-color: #525252;
                color: #ffffff;
                selection-background-color: #5285a6;
                selection-color: #ffffff;
                border: 1px solid #444444;
                font-size: {menu_font_sz}px;
            }}
            QCheckBox, QRadioButton {{
                color: #cccccc;
                font-size: {font_sz}px;
                spacing: 6px;
            }}
            QCheckBox::indicator, QRadioButton::indicator {{
                width: {chk_sz}px;
                height: {chk_sz}px;
            }}
            QPushButton {{
                background-color: #444444;
                color: #e0e0e0;
                border: 1px solid #505050;
                padding: {btn_pad_v}px {btn_pad_h}px;
                font-size: {font_sz}px;
            }}
            QPushButton:hover {{
                background-color: #525252;
                border-color: #606060;
            }}
            QPushButton:pressed {{
                background-color: #2e2e2e;
                border-color: #404040;
            }}
            QPushButton#save_btn {{
                background-color: #5285a6;
                color: #ffffff;
                font-weight: bold;
                border: 1px solid #629ec4;
            }}
            QPushButton#save_btn:hover {{
                background-color: #629ec4;
            }}
            QPushButton#reset_btn {{
                background-color: #444444;
                color: #ffb74d;
                border: 1px solid #505050;
            }}
            QPushButton#reset_btn:hover {{
                background-color: #525252;
                color: #ffa726;
            }}
            QToolButton {{
                background-color: #444444;
                color: #cccccc;
                border: 1px solid #505050;
                padding: 2px 6px;
            }}
            QToolButton:hover {{
                background-color: #525252;
            }}
            QListWidget {{
                background-color: #2b2b2b;
                color: #e0e0e0;
                border: 1px solid #444444;
                font-size: {font_sz}px;
            }}
            QListWidget::item {{
                padding: 4px 6px;
                border-bottom: 1px solid #373737;
            }}
            QListWidget::item:hover {{
                background-color: #373737;
            }}
            QListWidget::item:selected {{
                background-color: #5285a6;
                color: #ffffff;
            }}
            QSlider::groove:horizontal {{
                height: 6px;
                background: #2b2b2b;
                border: 1px solid #444444;
            }}
            QSlider::sub-page:horizontal {{
                background: #5285a6;
            }}
            QSlider::handle:horizontal {{
                background: #888888;
                border: 1px solid #aaaaaa;
                width: 14px;
                margin-top: -4px;
                margin-bottom: -4px;
            }}
            QSlider::handle:horizontal:hover {{
                background: #5285a6;
                border-color: #629ec4;
            }}
            QScrollArea {{
                background: transparent;
                border: none;
            }}
            ShelfButton {{
                background-color: transparent;
                border: 1px solid transparent;
                border-radius: {btn_radius}px;
                padding: 0px;
                margin: 0px;
            }}
            ShelfButton:hover {{
                background-color: #444444;
                border: 1px solid #606060;
                border-radius: {btn_radius}px;
            }}
            ShelfButton:pressed {{
                background-color: #2b2b2b;
                border: 1px solid #373737;
                border-radius: {btn_radius}px;
                padding: 1px 0px 0px 1px;
            }}
            QMenu {{
                background-color: #525252;
                color: #e0e0e0;
                border: 1px solid #444444;
                padding: {menu_pad}px;
                font-size: {menu_font_sz}px;
            }}
            QMenu::item {{
                padding: {menu_item_pad_v}px {menu_item_pad_h}px;
            }}
            QMenu::item:selected {{
                background-color: #5285a6;
                color: #ffffff;
            }}
            QMenu::separator {{
                height: 1px;
                background-color: #444444;
                margin: 2px 4px;
            }}
            QMenu::item:disabled {{
                color: #777777;
            }}
        """)

    def _center_on_screen(self):
        w = max(620, int(round(660 * self.scale)))
        h = max(680, int(round(720 * self.scale)))
        self.resize(w, h)
        parent = self.parent()
        if parent:
            geo = parent.frameGeometry()
            x = geo.x() + (geo.width() - w) // 2
            y = geo.y() + (geo.height() - h) // 2
            self.move(max(0, x), max(0, y))
        else:
            screen = QtWidgets.QApplication.primaryScreen()
            if screen:
                geo = screen.availableGeometry()
                x = geo.x() + (geo.width() - w) // 2
                y = geo.y() + (geo.height() - h) // 2
                self.move(max(0, x), max(0, y))

    def _on_browse_icon(self):
        current_icon = self.icon_edit.text().strip()
        start_dir = ""
        if current_icon and os.path.isabs(current_icon):
            start_dir = os.path.dirname(current_icon)
        elif cmds and hasattr(cmds, "internalVar"):
            try:
                start_dir = cmds.internalVar(userBitmapsDir=True) or ""
            except Exception:
                start_dir = ""

        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select Shelf Button Icon",
            start_dir,
            "Image Files (*.png *.svg *.xpm *.jpg *.jpeg *.bmp);;All Files (*.*)"
        )
        if file_path:
            self.icon_edit.setText(file_path)

    def _on_alpha_slider_changed(self, value):
        self.alpha_lbl.setText(f"{value}%")
        self._on_parameter_changed()

    def _on_enable_bg_toggled(self, checked):
        self.btn_bg_btn.setEnabled(checked)
        self._on_parameter_changed()

    def _on_width_mode_changed(self):
        is_custom = self.radio_width_custom.isChecked()
        self.custom_width_spin.setEnabled(is_custom)
        self._on_parameter_changed()

    def _load_data(self, data):
        self._loading = True

        self.icon_edit.setText(data.get("image", "commandButton.png"))
        self.overlay_edit.setText(data.get("imageOverlayLabel", ""))

        # Text color
        tc = data.get("labelColor") or data.get("overlayLabelColor")
        self.text_color_btn.set_normalized_rgb(tc, emit=False)

        # Label background
        lbg = data.get("labelBackground")
        if not lbg and "overlayLabelBackColor" in data:
            olb = data["overlayLabelBackColor"]
            if olb and len(olb) >= 3:
                lbg = olb[:3]
        self.label_bg_btn.set_normalized_rgb(lbg, emit=False)

        # Alpha
        alpha = data.get("backgroundTransparency")
        if alpha is None and "overlayLabelBackColor" in data:
            olb = data["overlayLabelBackColor"]
            if olb and len(olb) >= 4:
                alpha = olb[3]
        if alpha is None:
            alpha = 0.9
        try:
            slider_val = max(0, min(100, int(round(float(alpha) * 100))))
        except (ValueError, TypeError):
            slider_val = 90
        self.alpha_slider.setValue(slider_val)
        self.alpha_lbl.setText(f"{slider_val}%")

        # Custom button background
        has_bg = bool(data.get("enableBackground", False))
        self.enable_bg_chk.setChecked(has_bg)
        bbg = data.get("buttonBackground") or data.get("backgroundColor")
        self.btn_bg_btn.set_normalized_rgb(bbg, emit=False)
        self.btn_bg_btn.setEnabled(has_bg)

        # Width
        is_custom = (data.get("flexibleWidthType") == 2)
        w = data.get("width") or data.get("flexibleWidthValue") or 35
        try:
            w_int = int(w)
        except (ValueError, TypeError):
            w_int = 35

        if is_custom:
            self.radio_width_custom.setChecked(True)
            self.custom_width_spin.setValue(w_int)
            self.custom_width_spin.setEnabled(True)
        else:
            self.radio_width_std.setChecked(True)
            self.custom_width_spin.setValue(w_int if w_int != 35 else 35)
            self.custom_width_spin.setEnabled(False)

        # Label & Tooltip
        self.label_edit.setText(data.get("label", ""))
        self.annotation_edit.setText(data.get("annotation", ""))

        # Commands
        st = data.get("sourceType", "mel").lower()
        self.cmd_lang_combo.setCurrentText("python" if st == "python" else "mel")
        self.cmd_editor.setPlainText(data.get("command", ""))
        self.double_click_editor.setPlainText(data.get("doubleClickCommand", ""))

        # Menu items
        self.popup_menu_tab.set_items_data(data.get("menuItems", []))

        self._loading = False
        self._on_parameter_changed()

    def _collect_current_data(self):
        data = dict(self.current_data)
        data["image"] = self.icon_edit.text().strip() or "commandButton.png"
        if "image1" in data or "image" in data:
            data["image1"] = data["image"]
        data["imageOverlayLabel"] = self.overlay_edit.text()

        # Text color
        tc = self.text_color_btn.get_normalized_rgb()
        if tc is not None:
            data["labelColor"] = tc
            data["overlayLabelColor"] = tc
        else:
            data.pop("labelColor", None)
            data.pop("overlayLabelColor", None)

        # Label background
        lbg = self.label_bg_btn.get_normalized_rgb()
        alpha = round(self.alpha_slider.value() / 100.0, 3)
        if lbg is not None:
            data["labelBackground"] = lbg
            data["backgroundTransparency"] = alpha
            data["overlayLabelBackColor"] = [lbg[0], lbg[1], lbg[2], alpha]
        else:
            data.pop("labelBackground", None)
            data.pop("backgroundTransparency", None)
            data.pop("overlayLabelBackColor", None)

        # Button background
        if self.enable_bg_chk.isChecked():
            data["enableBackground"] = True
            bbg = self.btn_bg_btn.get_normalized_rgb() or [0.22, 0.22, 0.22]
            data["buttonBackground"] = bbg
            data["backgroundColor"] = bbg
        else:
            data["enableBackground"] = False
            data.pop("buttonBackground", None)
            data.pop("backgroundColor", None)

        # Width
        if self.radio_width_custom.isChecked():
            w_val = int(self.custom_width_spin.value())
            data["flexibleWidthType"] = 2
            data["flexibleWidthValue"] = w_val
            data["width"] = w_val
        else:
            data["flexibleWidthType"] = 1
            data["width"] = 35
            data.pop("flexibleWidthValue", None)

        data["label"] = self.label_edit.text().strip()
        data["annotation"] = self.annotation_edit.text().strip()
        data["sourceType"] = self.cmd_lang_combo.currentText()
        data["command"] = self.cmd_editor.toPlainText()

        dc = self.double_click_editor.toPlainText().strip()
        if dc:
            data["doubleClickCommand"] = dc
        else:
            data.pop("doubleClickCommand", None)

        menu_items = self.popup_menu_tab.get_items_data()
        if menu_items:
            data["menuItems"] = menu_items
        else:
            data.pop("menuItems", None)

        return data

    def _on_parameter_changed(self):
        if self._loading:
            return
        self.current_data = self._collect_current_data()
        self.preview_button.update_data(self.current_data)

        # Update thumbnail
        if self.preview_button._pixmap and not self.preview_button._pixmap.isNull():
            thumb_sz = max(24, int(round(32 * self.scale)))
            self.icon_thumb.setPixmap(
                self.preview_button._pixmap.scaled(
                    thumb_sz, thumb_sz,
                    QtCore.Qt.KeepAspectRatio,
                    QtCore.Qt.SmoothTransformation
                )
            )
        else:
            self.icon_thumb.clear()

        # Update preview badges
        w = self.preview_button.width()
        h = self.preview_button.height()
        self.badge_size.setText(f"Size: {w} × {h} px")

        item_count = len(self.popup_menu_tab.items_data)
        if self.preview_button.has_custom_menu:
            self.badge_menu.setText(f"Dropdown: Yes ({item_count} items)")
        else:
            self.badge_menu.setText("Dropdown: None")

        lang = self.cmd_lang_combo.currentText().upper()
        self.badge_lang.setText(f"Lang: {lang}")

        ov = self.overlay_edit.text()
        self.badge_overlay.setText(f"Overlay: \"{ov}\"" if ov else "Overlay: (None)")

        # Update window title
        btn_title = self.label_edit.text().strip() or self.overlay_edit.text().strip() or "Button"
        self.setWindowTitle(f"Edit Button: {btn_title}")

    def _on_reset_clicked(self):
        self._load_data(self.initial_data)

    def _on_save_clicked(self):
        final_data = self._collect_current_data()
        success = self.shelf_manager.save_button_data(self.shelf_index, self.button_index, final_data)
        if success:
            self.accept()
        else:
            cmds.warning("spShelf: Failed to save button data.")


class SeparatorWidget(QtWidgets.QFrame):
    """Separator line or dotted indicator for shelves with MMB drag-and-drop support."""
    def __init__(self, horizontal=False, dotted=False, shelf_index=0, item_index=0, shelf_manager=None, scale=1.0, parent=None):
        super(SeparatorWidget, self).__init__(parent)
        self.shelf_index = shelf_index
        self.item_index = item_index
        self.shelf_manager = shelf_manager
        self.horizontal = horizontal
        self.dotted = dotted
        self.scale = scale
        self._mmb_pressed = False
        self._mmb_drag_start_pos = QtCore.QPoint()

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
        self.setStyleSheet("SeparatorWidget { background: transparent; border: none; }")

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

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MiddleButton:
            self._mmb_pressed = True
            pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
            self._mmb_drag_start_pos = pos
            return
        super(SeparatorWidget, self).mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if getattr(self, "_mmb_pressed", False) and (event.buttons() & QtCore.Qt.MiddleButton):
            pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
            dist = (pos - self._mmb_drag_start_pos).manhattanLength()
            if dist >= QtWidgets.QApplication.startDragDistance():
                self._mmb_pressed = False
                self._start_drag(pos)
                return
        super(SeparatorWidget, self).mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.MiddleButton:
            self._mmb_pressed = False
            return
        super(SeparatorWidget, self).mouseReleaseEvent(event)

    def _start_drag(self, pos):
        drag = QtGui.QDrag(self)
        mime_data = QtCore.QMimeData()
        payload = {
            "source_shelf_idx": self.shelf_index,
            "source_item_idx": self.item_index
        }
        mime_data.setData("application/x-spshelf-item", QtCore.QByteArray(json.dumps(payload).encode("utf-8")))
        drag.setMimeData(mime_data)

        pixmap = self.grab()
        if not pixmap.isNull():
            transparent_pix = QtGui.QPixmap(pixmap.size())
            transparent_pix.fill(QtCore.Qt.transparent)
            painter = QtGui.QPainter(transparent_pix)
            painter.setOpacity(0.7)
            painter.drawPixmap(0, 0, pixmap)
            painter.end()
            drag.setPixmap(transparent_pix)
            hot_x = max(0, min(pixmap.width() - 1, pos.x()))
            hot_y = max(0, min(pixmap.height() - 1, pos.y()))
            drag.setHotSpot(QtCore.QPoint(hot_x, hot_y))

        drag_exec = getattr(drag, "exec", getattr(drag, "exec_", None))
        if drag_exec:
            drag_exec(QtCore.Qt.MoveAction)

    def _show_context_menu(self, pos):
        if not self.shelf_manager:
            return
        parent_win = self.window() if self.window() else self
        menu = QtWidgets.QMenu(parent_win)
        add_sep_action = menu.addAction("Add Separator")
        add_sep_action.triggered.connect(lambda: self.shelf_manager.add_separator(self.shelf_index, self.item_index + 1))
        menu.addSeparator()
        del_action = menu.addAction("Delete Separator")
        del_action.triggered.connect(lambda: self.shelf_manager.confirm_and_delete_button(self.shelf_index, self.item_index))
        menu.exec_(self.mapToGlobal(pos))


class SettingsIslandButton(QtWidgets.QToolButton):
    """
    Compact 'island' settings button located at the top-right of the window.
    - Half the size of regular shelf buttons.
    - Smooth rounded-island geometry.
    - High-DPI gear icon rendering bypassing Maya QStyle raster clamping.
    - Supports normal, hover, pressed, and checked (active rollout) states.
    """
    def __init__(self, shelf_window=None, scale=1.0, parent=None):
        super(SettingsIslandButton, self).__init__(parent)
        self.shelf_window = shelf_window
        self.scale = scale
        self.setCheckable(True)
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setToolTip("Settings")
        self._is_hovered = False
        self._pixmap = None
        self._load_icon()
        self.update_scale(scale)

    def update_scale(self, scale):
        self.scale = scale
        btn_sz = max(16, int(round(20 * self.scale)))
        self.setFixedSize(btn_sz, btn_sz)
        self._load_icon()
        self.update()

    def _load_icon(self):
        self._pixmap = get_gear_pixmap(self.scale)

    def enterEvent(self, event):
        self._is_hovered = True
        self.update()
        super(SettingsIslandButton, self).enterEvent(event)

    def leaveEvent(self, event):
        self._is_hovered = False
        self.update()
        super(SettingsIslandButton, self).leaveEvent(event)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)

        is_checked = self.isChecked()
        is_down = self.isDown()
        is_hover = self._is_hovered

        if is_checked:
            # Active (rollout open) -> Maya Blue Accent
            bg_color = QtGui.QColor("#5285a6") if is_hover else QtGui.QColor("#427090")
            border_color = QtGui.QColor("#629ec4")
        elif is_down:
            bg_color = QtGui.QColor("#2b2b2b")
            border_color = QtGui.QColor("#373737")
        elif is_hover:
            bg_color = QtGui.QColor("#525252")
            border_color = QtGui.QColor("#606060")
        else:
            # Normal island
            bg_color = QtGui.QColor("#444444")
            border_color = QtGui.QColor("#505050")

        rect = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        # Draw square island background & border
        painter.setPen(QtGui.QPen(border_color, max(1.0, 1.0 * self.scale)))
        painter.setBrush(QtGui.QBrush(bg_color))
        painter.drawRect(rect)

        # Draw gear icon centered
        target_icon_sz = max(10, int(round(14 * self.scale)))
        if self._pixmap and not self._pixmap.isNull():
            icon_rect = QtCore.QRect(0, 0, target_icon_sz, target_icon_sz)
            icon_rect.moveCenter(self.rect().center())
            if is_down:
                icon_rect.adjust(1, 1, 1, 1)

            scaled_pix = self._pixmap.scaled(
                QtCore.QSize(target_icon_sz, target_icon_sz),
                QtCore.Qt.KeepAspectRatio,
                QtCore.Qt.SmoothTransformation
            )
            painter.drawPixmap(icon_rect, scaled_pix)
        else:
            # Procedural gear icon fallback
            painter.setPen(QtGui.QPen(QtGui.QColor(220, 220, 220), max(1.0, 1.2 * self.scale)))
            painter.setBrush(QtCore.Qt.NoBrush)
            r = target_icon_sz / 2.0
            cx = self.rect().width() / 2.0 + (1.0 if is_down else 0.0)
            cy = self.rect().height() / 2.0 + (1.0 if is_down else 0.0)
            painter.drawEllipse(QtCore.QPointF(cx, cy), r * 0.55, r * 0.55)
            for deg in range(0, 360, 60):
                rad = math.radians(deg)
                x1 = cx + math.cos(rad) * (r * 0.45)
                y1 = cy + math.sin(rad) * (r * 0.45)
                x2 = cx + math.cos(rad) * (r * 0.85)
                y2 = cy + math.sin(rad) * (r * 0.85)
                painter.drawLine(QtCore.QPointF(x1, y1), QtCore.QPointF(x2, y2))


class ShelfToggleIslandButton(QtWidgets.QToolButton):
    """
    Compact 'island' button located to the left of the settings button.
    - Sized identically to SettingsIslandButton with smooth rounded-island geometry.
    - High-DPI miniature shelf icon with procedural fallback.
    - Toggles Maya shelf visibility via `mel: ToggleShelf;`.
    - Real-time Maya shelf visibility sync with active teal accent when shelf is visible.
    """
    def __init__(self, shelf_window=None, scale=1.0, parent=None):
        super(ShelfToggleIslandButton, self).__init__(parent)
        self.shelf_window = shelf_window
        self.scale = scale
        self.setCheckable(True)
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setToolTip("Toggle Maya Shelf (mel: ToggleShelf;)")
        self._is_hovered = False
        self._pixmap = None
        self._load_icon()
        self.update_scale(scale)

    def update_scale(self, scale):
        self.scale = scale
        btn_sz = max(16, int(round(20 * self.scale)))
        self.setFixedSize(btn_sz, btn_sz)
        self._load_icon()
        self.update()

    def _load_icon(self):
        self._pixmap = get_shelf_pixmap(self.scale)

    def enterEvent(self, event):
        self._is_hovered = True
        self.update_shelf_state()
        self.update()
        super(ShelfToggleIslandButton, self).enterEvent(event)

    def leaveEvent(self, event):
        self._is_hovered = False
        self.update()
        super(ShelfToggleIslandButton, self).leaveEvent(event)

    def update_shelf_state(self):
        try:
            vis = bool(mel.eval('isUIComponentVisible("Shelf")'))
            self.setChecked(vis)
            status = "Visible" if vis else "Hidden"
            self.setToolTip(f"Toggle Maya Shelf: {status} (mel: ToggleShelf;)")
        except Exception:
            pass

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)

        is_checked = self.isChecked()
        is_down = self.isDown()
        is_hover = self._is_hovered

        if is_checked:
            # Active (Maya shelf visible) -> Maya Blue Accent
            bg_color = QtGui.QColor("#5285a6") if is_hover else QtGui.QColor("#427090")
            border_color = QtGui.QColor("#629ec4")
        elif is_down:
            bg_color = QtGui.QColor("#2b2b2b")
            border_color = QtGui.QColor("#373737")
        elif is_hover:
            bg_color = QtGui.QColor("#525252")
            border_color = QtGui.QColor("#606060")
        else:
            # Normal island
            bg_color = QtGui.QColor("#444444")
            border_color = QtGui.QColor("#505050")

        rect = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        # Draw square island background & border
        painter.setPen(QtGui.QPen(border_color, max(1.0, 1.0 * self.scale)))
        painter.setBrush(QtGui.QBrush(bg_color))
        painter.drawRect(rect)

        # Draw shelf icon centered
        target_icon_sz = max(10, int(round(14 * self.scale)))
        if self._pixmap and not self._pixmap.isNull():
            icon_rect = QtCore.QRect(0, 0, target_icon_sz, target_icon_sz)
            icon_rect.moveCenter(self.rect().center())
            if is_down:
                icon_rect.adjust(1, 1, 1, 1)

            scaled_pix = self._pixmap.scaled(
                QtCore.QSize(target_icon_sz, target_icon_sz),
                QtCore.Qt.KeepAspectRatio,
                QtCore.Qt.SmoothTransformation
            )
            painter.drawPixmap(icon_rect, scaled_pix)
        else:
            # Procedural Maya shelf miniature icon fallback
            s = self.scale
            cx = self.rect().width() / 2.0 + (1.0 if is_down else 0.0)
            cy = self.rect().height() / 2.0 + (1.0 if is_down else 0.0)

            tab_active_col = QtGui.QColor("#ffffff") if is_checked else QtGui.QColor("#00c5a5")
            tab_inactive_col = QtGui.QColor("#004239") if is_checked else QtGui.QColor("#606060")
            line_col = QtGui.QColor("#80cfc5") if is_checked else QtGui.QColor("#777777")
            btn_col = QtGui.QColor("#ffffff") if is_checked else QtGui.QColor("#dcdcdc")

            painter.setPen(QtCore.Qt.NoPen)
            # Active tab
            painter.setBrush(QtGui.QBrush(tab_active_col))
            painter.drawRoundedRect(QtCore.QRectF(cx - 5.5 * s, cy - 5.0 * s, 5.0 * s, 2.5 * s), 0.5 * s, 0.5 * s)
            # Inactive tab
            painter.setBrush(QtGui.QBrush(tab_inactive_col))
            painter.drawRoundedRect(QtCore.QRectF(cx + 0.5 * s, cy - 4.5 * s, 5.0 * s, 2.0 * s), 0.5 * s, 0.5 * s)
            # Shelf line under tabs
            painter.setPen(QtGui.QPen(line_col, max(0.8, 1.0 * s)))
            painter.drawLine(QtCore.QPointF(cx - 5.5 * s, cy - 2.0 * s), QtCore.QPointF(cx + 5.5 * s, cy - 2.0 * s))
            # 3 shelf buttons underneath
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(QtGui.QBrush(btn_col))
            btn_w = 3.0 * s
            btn_h = 3.0 * s
            corner = max(0.4, 0.5 * s)
            painter.drawRoundedRect(QtCore.QRectF(cx - 5.5 * s, cy, btn_w, btn_h), corner, corner)
            painter.drawRoundedRect(QtCore.QRectF(cx - 1.5 * s, cy, btn_w, btn_h), corner, corner)
            painter.drawRoundedRect(QtCore.QRectF(cx + 2.5 * s, cy, btn_w, btn_h), corner, corner)


def find_maya_shelf_button(widget):
    """Recursively checks widget hierarchy to locate a native Maya shelfButton control name."""
    w = widget
    while w is not None:
        try:
            name = w.objectName()
            if name and cmds.shelfButton(name, exists=True):
                return name
        except Exception:
            pass
        w = w.parent() if hasattr(w, "parent") else None
    return None


def extract_maya_button_data(event):
    """
    Extracts complete button configuration from an external Maya drag event:
    1. Direct Maya shelfButton inspection via event.source() Qt widget hierarchy.
    2. Maya application/x-maya-data payload inspection.
    3. Fallback: text/plain inspection for control names or raw script code.
    Returns a dict compatible with spShelf button schema, or None.
    """
    ctrl_name = None

    # 1. Try finding shelfButton via event.source()
    src = event.source()
    if src:
        ctrl_name = find_maya_shelf_button(src)

    # 2. Try application/x-maya-data MIME payload
    mime = event.mimeData()
    if not ctrl_name and mime.hasFormat("application/x-maya-data"):
        try:
            raw_bytes = bytes(mime.data("application/x-maya-data"))
            tokens = [s.strip() for s in raw_bytes.decode("utf-8", errors="ignore").replace("\x00", "\n").split("\n") if s.strip()]
            for token in tokens:
                try:
                    if cmds.shelfButton(token, exists=True):
                        ctrl_name = token
                        break
                except Exception:
                    pass
        except Exception as e:
            log_debug(f"extract_maya_button_data: error reading application/x-maya-data: {e}")

    # 3. Try text/plain for control name
    if not ctrl_name and mime.hasText():
        txt = mime.text().strip()
        try:
            if cmds.shelfButton(txt, exists=True):
                ctrl_name = txt
        except Exception:
            pass

    # If we found a valid Maya shelfButton control, query all its attributes
    if ctrl_name:
        log_debug(f"extract_maya_button_data: found Maya shelfButton control '{ctrl_name}'")
        try:
            cmd = cmds.shelfButton(ctrl_name, query=True, command=True) or ""
        except Exception:
            cmd = ""
        try:
            source_type = cmds.shelfButton(ctrl_name, query=True, sourceType=True) or "mel"
        except Exception:
            source_type = "mel"
        try:
            image = cmds.shelfButton(ctrl_name, query=True, image=True) or "commandButton.png"
        except Exception:
            image = "commandButton.png"
        try:
            overlay = cmds.shelfButton(ctrl_name, query=True, imageOverlayLabel=True) or ""
        except Exception:
            overlay = ""
        try:
            label = cmds.shelfButton(ctrl_name, query=True, label=True) or ""
        except Exception:
            label = ""
        try:
            ann = cmds.shelfButton(ctrl_name, query=True, annotation=True) or ""
        except Exception:
            ann = ""
        try:
            dbl_cmd = cmds.shelfButton(ctrl_name, query=True, doubleClickCommand=True) or ""
        except Exception:
            dbl_cmd = ""

        # Query popup menu items (RMB sub-commands)
        menu_items = []
        try:
            popups = cmds.shelfButton(ctrl_name, query=True, popupMenuArray=True) or []
            for p in popups:
                items = cmds.popupMenu(p, query=True, itemArray=True) or []
                for item in items:
                    try:
                        is_opt_box = False
                        try:
                            is_opt_box = cmds.menuItem(item, query=True, optionBox=True)
                        except Exception:
                            pass

                        m_cmd = cmds.menuItem(item, query=True, command=True) or ""
                        m_label = cmds.menuItem(item, query=True, label=True) or "Item"

                        # Skip Maya's default built-in shelf button RMB menu items (Open, Edit, Edit Popup, Delete)
                        if is_default_maya_menu_item(m_cmd, m_label):
                            continue

                        if is_opt_box and menu_items and m_cmd:
                            clean_opt, opt_type = extract_command_and_type(m_cmd)
                            menu_items[-1]["optionBoxCommand"] = clean_opt
                            menu_items[-1]["optionBoxSourceType"] = opt_type
                            continue

                        if m_cmd:
                            m_stp = "mel"
                            try:
                                m_stp = cmds.menuItem(item, query=True, sourceType=True) or "mel"
                            except Exception:
                                pass
                            clean_cmd, detected_type = extract_command_and_type(m_cmd)
                            final_stp = detected_type if detected_type == "python" else m_stp
                            menu_items.append({
                                "label": m_label,
                                "command": clean_cmd,
                                "sourceType": final_stp
                            })
                    except Exception:
                        pass
        except Exception:
            pass

        # Query label color (overlayLabelColor)
        overlay_label_color = None
        try:
            raw_olc = cmds.shelfButton(ctrl_name, query=True, overlayLabelColor=True)
            if raw_olc and len(raw_olc) >= 3:
                overlay_label_color = [round(float(c), 4) for c in raw_olc[:3]]
        except Exception as e:
            log_debug(f"extract_maya_button_data: error querying overlayLabelColor: {e}")

        # Query label background & background transparency (overlayLabelBackColor)
        overlay_label_back_color = None
        label_background = None
        bg_transparency = None
        try:
            raw_olb = cmds.shelfButton(ctrl_name, query=True, overlayLabelBackColor=True)
            if raw_olb and len(raw_olb) >= 3:
                overlay_label_back_color = [round(float(c), 4) for c in raw_olb]
                label_background = [round(float(c), 4) for c in raw_olb[:3]]
                if len(raw_olb) >= 4:
                    bg_transparency = round(float(raw_olb[3]), 4)
        except Exception as e:
            log_debug(f"extract_maya_button_data: error querying overlayLabelBackColor: {e}")

        # Query button background if set (enableBackground & backgroundColor)
        button_bg = None
        try:
            enable_bg = bool(cmds.shelfButton(ctrl_name, query=True, enableBackground=True))
            if enable_bg:
                raw_bg = cmds.shelfButton(ctrl_name, query=True, backgroundColor=True)
                if raw_bg and len(raw_bg) >= 3:
                    button_bg = [round(float(c), 4) for c in raw_bg[:3]]
        except Exception as e:
            log_debug(f"extract_maya_button_data: error querying backgroundColor/enableBackground: {e}")

        # Query button width if set (unscale by Maya's native UI DPI scaling)
        maya_dpi = get_maya_dpi_scale()
        button_width = None
        try:
            raw_w = cmds.shelfButton(ctrl_name, query=True, width=True)
            if raw_w and float(raw_w) > 0:
                button_width = int(round(float(raw_w) / maya_dpi))
        except Exception as e:
            log_debug(f"extract_maya_button_data: error querying width: {e}")

        flexible_width_type = None
        flexible_width_value = None
        try:
            fwt = cmds.shelfButton(ctrl_name, query=True, flexibleWidthType=True)
            if fwt is not None:
                flexible_width_type = int(fwt)
        except Exception:
            pass
        try:
            fwv = cmds.shelfButton(ctrl_name, query=True, flexibleWidthValue=True)
            if fwv is not None:
                flexible_width_value = int(round(float(fwv) / maya_dpi))
        except Exception:
            pass

        btn_dict = {
            "label": label or overlay or "MayaButton",
            "annotation": ann or label or overlay,
            "image": image,
            "imageOverlayLabel": overlay,
            "command": cmd,
            "sourceType": source_type,
            "doubleClickCommand": dbl_cmd
        }
        if button_width is not None:
            btn_dict["width"] = button_width
        if flexible_width_type is not None:
            btn_dict["flexibleWidthType"] = flexible_width_type
        if flexible_width_value is not None:
            btn_dict["flexibleWidthValue"] = flexible_width_value
        if overlay_label_color is not None:
            btn_dict["overlayLabelColor"] = overlay_label_color
            btn_dict["labelColor"] = overlay_label_color
        if overlay_label_back_color is not None:
            btn_dict["overlayLabelBackColor"] = overlay_label_back_color
        if label_background is not None:
            btn_dict["labelBackground"] = label_background
        if bg_transparency is not None:
            btn_dict["backgroundTransparency"] = bg_transparency
        if button_bg is not None:
            btn_dict["backgroundColor"] = button_bg
            btn_dict["buttonBackground"] = button_bg
            btn_dict["enableBackground"] = True

        if menu_items:
            btn_dict["menuItems"] = menu_items
        return btn_dict

    # 4. Fallback: text dropped from Maya Script Editor
    if mime.hasText():
        raw_text = mime.text().strip()
        if raw_text:
            log_debug(f"extract_maya_button_data: creating button from dropped script text ({len(raw_text)} chars)")
            if raw_text.startswith("import ") or raw_text.startswith("from ") or "\ndef " in raw_text or "cmds." in raw_text or "print(" in raw_text:
                stype = "python"
                icon = "pythonFamily.png"
            else:
                stype = "mel"
                icon = "commandButton.png"

            first_line = raw_text.splitlines()[0].strip()
            short_label = first_line[:6].strip()

            return {
                "label": short_label or "Script",
                "annotation": raw_text[:80],
                "image": icon,
                "imageOverlayLabel": short_label[:4].upper() if len(short_label) <= 4 else "",
                "command": raw_text,
                "sourceType": stype,
                "doubleClickCommand": ""
            }

    return None


def is_acceptable_shelf_drag(event):
    """Validates if a drag event is from spShelf itself or an external Maya shelf/script."""
    mime = event.mimeData()
    if mime.hasFormat("application/x-spshelf-item"):
        return True
    if mime.hasFormat("application/x-maya-data"):
        return True
    src = event.source()
    if src:
        if find_maya_shelf_button(src) is not None:
            return True
    if mime.hasText() and mime.text().strip():
        return True
    return False


class ShelfHeaderButton(QtWidgets.QToolButton):
    """
    Shelf section header button with drag-and-drop acceptance:
    - Allows dropping buttons directly onto the header to append them to the shelf.
    - Hovering over a collapsed header for 400ms automatically expands the shelf.
    """
    def __init__(self, section=None, parent=None):
        super(ShelfHeaderButton, self).__init__(parent)
        self.section = section
        self.setAcceptDrops(True)
        self._hover_expand_timer = QtCore.QTimer(self)
        self._hover_expand_timer.setSingleShot(True)
        self._hover_expand_timer.setInterval(400)
        self._hover_expand_timer.timeout.connect(self._on_hover_expand)

    def _on_hover_expand(self):
        if self.section and self.section._is_collapsed:
            self.section.set_collapsed(False)
            if self.section.on_collapse_changed:
                self.section.on_collapse_changed(False)

    def dragEnterEvent(self, event):
        if is_acceptable_shelf_drag(event) and self.section and self.section.shelf_index is not None:
            event.acceptProposedAction()
            if self.section._is_collapsed:
                self._hover_expand_timer.start()
        else:
            super(ShelfHeaderButton, self).dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if is_acceptable_shelf_drag(event) and self.section and self.section.shelf_index is not None:
            event.acceptProposedAction()
        else:
            super(ShelfHeaderButton, self).dragMoveEvent(event)

    def dragLeaveEvent(self, event):
        self._hover_expand_timer.stop()
        super(ShelfHeaderButton, self).dragLeaveEvent(event)

    def dropEvent(self, event):
        self._hover_expand_timer.stop()
        if self.section and self.section.shelf_index is not None:
            dst_shelf = self.section.shelf_index
            target_win = self.section.shelf_window

            # 1. Internal spShelf drag
            if event.mimeData().hasFormat("application/x-spshelf-item"):
                try:
                    raw_bytes = bytes(event.mimeData().data("application/x-spshelf-item"))
                    payload = json.loads(raw_bytes.decode("utf-8"))
                    src_shelf = payload.get("source_shelf_idx")
                    src_idx = payload.get("source_item_idx")
                    if target_win and target_win.manager:
                        dst_buttons = target_win.manager.shelves[dst_shelf].get("buttons", [])
                        dst_idx = len(dst_buttons)
                        target_win.manager.move_shelf_item(src_shelf, src_idx, dst_shelf, dst_idx)
                        event.acceptProposedAction()
                        return
                except Exception as e:
                    log_debug(f"ShelfHeaderButton.dropEvent internal error: {e}")

            # 2. External Maya shelf button or script text drop
            btn_data = extract_maya_button_data(event)
            if btn_data and target_win and target_win.manager:
                dst_buttons = target_win.manager.shelves[dst_shelf].get("buttons", [])
                dst_idx = len(dst_buttons)
                target_win.manager.insert_external_button(dst_shelf, dst_idx, btn_data)
                event.acceptProposedAction()
                return

        super(ShelfHeaderButton, self).dropEvent(event)


class CollapsibleSection(QtWidgets.QWidget):
    """Collapsible container representing a single Maya shelf or Settings panel."""
    def __init__(self, title, collapsed=False, label_visible=True, on_collapse_changed=None, shelf_window=None, scale=1.0, shelf_index=None, parent=None):
        super(CollapsibleSection, self).__init__(parent)
        self.shelf_index = shelf_index
        self.on_collapse_changed = on_collapse_changed
        self.shelf_window = shelf_window
        self._is_collapsed = collapsed
        self.scale = scale or (shelf_window.scale if shelf_window else 1.0)

        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Header bar with drag-and-drop acceptance
        self.header_btn = ShelfHeaderButton(section=self, parent=self)
        self.header_btn.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.header_btn.setText(f" {title}")
        self.header_btn.setCheckable(True)
        self.header_btn.setChecked(not collapsed)
        self.header_btn.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        
        self.update_font_size()
        self.header_btn.clicked.connect(self._toggle_collapse)

        # Content container
        self.content_widget = QtWidgets.QWidget(self)
        self.content_layout = QtWidgets.QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(0)

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

    def _update_margins(self, visible):
        if visible:
            margin_bottom = max(1, int(round(2 * self.scale)))
            self.layout().setContentsMargins(0, 0, 0, margin_bottom)
            self.content_layout.setContentsMargins(0, max(0, int(round(1 * self.scale))), 0, 0)
        else:
            self.layout().setContentsMargins(0, 0, 0, 0)
            self.content_layout.setContentsMargins(0, 0, 0, 0)

    def set_label_visible(self, visible):
        if not visible and self._is_collapsed:
            self.set_collapsed(False)
        self.header_btn.setVisible(visible)
        self._update_margins(visible)

    def set_collapsed(self, collapsed):
        self._is_collapsed = collapsed
        self.header_btn.setChecked(not collapsed)
        self.content_widget.setVisible(not collapsed)
        self._update_arrow()
        target_win = self.shelf_window or self.window()
        if hasattr(target_win, "adjust_size_to_content"):
            target_win.adjust_size_to_content()

    def update_font_size(self, base_font_sz=None):
        if base_font_sz is None:
            base_font_sz = 13
            if self.shelf_window and hasattr(self.shelf_window, "manager") and self.shelf_window.manager:
                base_font_sz = self.shelf_window.manager.settings.get("FONT_SIZE", 13)
        try:
            base_font_sz = int(base_font_sz)
        except (ValueError, TypeError):
            base_font_sz = 13

        font_sz = max(9, int(round(base_font_sz * self.scale)))
        header_h = max(20, int(round(max(22, base_font_sz + 8) * self.scale)))
        self.header_btn.setFixedHeight(header_h)
        pad_l = max(3, int(round(4 * self.scale)))

        self.header_btn.setStyleSheet(f"""
            QToolButton {{
                background-color: #444444;
                border: 1px solid #373737;
                color: #e0e0e0;
                font-weight: bold;
                font-size: {font_sz}px;
                text-align: left;
                padding-left: {pad_l}px;
            }}
            QToolButton:hover {{
                background-color: #525252;
                border-color: #5a5a5a;
            }}
        """)


class ShelfGridWidget(QtWidgets.QWidget):
    """
    Container for shelf items with support for Middle Mouse Button Drag & Drop.
    Calculates dynamic drop insertion slot and renders high-contrast accent drop indicator.
    Uses independent horizontal row layouts to ensure separators maintain their compact size
    without expanding to button dimensions across multi-row shelves.
    """
    def __init__(self, shelf_index, shelf_window, manager, scale=1.0, col_count=4, parent=None):
        super(ShelfGridWidget, self).__init__(parent)
        self.shelf_index = shelf_index
        self.shelf_window = shelf_window
        self.manager = manager
        self.scale = scale
        self.col_count = col_count
        self.items = []
        self._drop_indicator = None

        self.setAcceptDrops(True)
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.grid_pad = max(1, int(round(2 * self.scale)))
        base_row_spacing = self.manager.settings.get("ROW_SPACING", 1)
        self.row_gap = max(0, int(round(base_row_spacing * self.scale)))
        self.main_layout.setContentsMargins(self.grid_pad, 0, self.grid_pad, 0)
        self.main_layout.setSpacing(self.row_gap)
        self.main_layout.setAlignment(QtCore.Qt.AlignTop)

        self.row_layouts = {}

    def sizeHint(self):
        if not self.items:
            btn_sz = max(24, int(round(38 * self.scale)))
            min_w = max(120, int(round(160 * self.scale)))
            return QtCore.QSize(min_w, btn_sz)
        return super(ShelfGridWidget, self).sizeHint()

    def minimumSizeHint(self):
        if not self.items:
            btn_sz = max(24, int(round(38 * self.scale)))
            min_w = max(120, int(round(160 * self.scale)))
            return QtCore.QSize(min_w, btn_sz)
        return super(ShelfGridWidget, self).minimumSizeHint()

    def horizontalSpacing(self):
        return self.grid_pad

    def verticalSpacing(self):
        return self.row_gap

    def add_shelf_item(self, widget, row, col=0, row_span=1, col_span=1, alignment=None):
        self.items.append(widget)
        is_horiz = getattr(widget, "horizontal", False)

        if is_horiz:
            self.main_layout.addWidget(widget)
        else:
            if row not in self.row_layouts:
                row_layout = QtWidgets.QHBoxLayout()
                row_layout.setContentsMargins(0, 0, 0, 0)
                row_layout.setSpacing(self.grid_pad)
                row_layout.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
                self.main_layout.addLayout(row_layout)
                self.row_layouts[row] = row_layout
            self.row_layouts[row].addWidget(widget)

    def _calculate_target_slot(self, pos):
        """
        Determines the target insertion index and indicator geometry from the cursor position.
        Returns (target_index, indicator_rect, is_horizontal).
        """
        shelf_buttons = self.manager.shelves[self.shelf_index].get("buttons", [])
        total_count = len(shelf_buttons)

        btn_sz = max(24, int(round(38 * self.scale)))
        thickness = max(2, int(round(3 * self.scale)))

        if not self.items:
            pad = max(2, int(round(2 * self.scale)))
            rect = QtCore.QRect(pad, pad, thickness, btn_sz)
            return 0, rect, False

        px, py = pos.x(), pos.y()
        closest_w = None
        min_dist = float("inf")

        for w in self.items:
            geo = w.geometry()
            cx = geo.center().x()
            cy = geo.center().y()
            dist = (px - cx) ** 2 + (py - cy) ** 2
            if dist < min_dist:
                min_dist = dist
                closest_w = w

        if not closest_w:
            return total_count, None, False

        geo = closest_w.geometry()
        item_idx = getattr(closest_w, "item_index", 0)
        is_horiz_sep = getattr(closest_w, "horizontal", False)

        if is_horiz_sep:
            if py < geo.center().y():
                target_idx = item_idx
                y = max(0, geo.top() - thickness // 2)
            else:
                target_idx = item_idx + 1
                y = min(self.height() - thickness, geo.bottom() - thickness // 2)
            rect = QtCore.QRect(geo.left(), y, geo.width(), thickness)
            return target_idx, rect, True
        else:
            spacing = self.grid_pad
            if px < geo.center().x():
                target_idx = item_idx
                x = geo.left() - (spacing + thickness) // 2
            else:
                target_idx = item_idx + 1
                x = geo.right() + spacing // 2
            x = max(0, min(self.width() - thickness, x))
            rect = QtCore.QRect(x, geo.top(), thickness, geo.height())
            return target_idx, rect, False

    def dragEnterEvent(self, event):
        if is_acceptable_shelf_drag(event):
            event.acceptProposedAction()
        else:
            super(ShelfGridWidget, self).dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if is_acceptable_shelf_drag(event):
            pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
            target_idx, rect, is_horiz = self._calculate_target_slot(pos)
            self._drop_indicator = {
                "target_index": target_idx,
                "rect": rect,
                "horizontal": is_horiz
            }
            self.update()
            event.acceptProposedAction()
        else:
            super(ShelfGridWidget, self).dragMoveEvent(event)

    def dragLeaveEvent(self, event):
        self._drop_indicator = None
        self.update()
        super(ShelfGridWidget, self).dragLeaveEvent(event)

    def dropEvent(self, event):
        indicator = self._drop_indicator
        self._drop_indicator = None
        self.update()

        # 1. Internal spShelf drag
        if event.mimeData().hasFormat("application/x-spshelf-item"):
            try:
                raw = bytes(event.mimeData().data("application/x-spshelf-item"))
                payload = json.loads(raw.decode("utf-8"))
                src_shelf = payload.get("source_shelf_idx")
                src_idx = payload.get("source_item_idx")

                if indicator and "target_index" in indicator:
                    dst_idx = indicator["target_index"]
                else:
                    pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
                    dst_idx, _, _ = self._calculate_target_slot(pos)

                self.manager.move_shelf_item(src_shelf, src_idx, self.shelf_index, dst_idx)
                event.acceptProposedAction()
                return
            except Exception as e:
                log_debug(f"ShelfGridWidget dropEvent internal error: {e}")

        # 2. External Maya shelf button or script text drop
        btn_data = extract_maya_button_data(event)
        if btn_data:
            if indicator and "target_index" in indicator:
                dst_idx = indicator["target_index"]
            else:
                pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
                dst_idx, _, _ = self._calculate_target_slot(pos)

            self.manager.insert_external_button(self.shelf_index, dst_idx, btn_data)
            event.acceptProposedAction()
            return

        super(ShelfGridWidget, self).dropEvent(event)

    def paintEvent(self, event):
        super(ShelfGridWidget, self).paintEvent(event)
        if not self.items:
            painter = QtGui.QPainter(self)
            painter.setRenderHint(QtGui.QPainter.Antialiasing)
            btn_sz = max(24, int(round(38 * self.scale)))
            pad = max(2, int(round(2 * self.scale)))
            w = max(10, self.width() - pad * 2)
            h = max(btn_sz - pad * 2, self.height() - pad * 2)
            rect = QtCore.QRect(pad, pad, w, h)
            radius = max(2, int(round(3 * self.scale)))

            # Draw dashed slot
            pen = QtGui.QPen(QtGui.QColor(255, 255, 255, 45))
            pen.setStyle(QtCore.Qt.DashLine)
            pen.setWidth(1)
            painter.setPen(pen)
            painter.setBrush(QtGui.QBrush(QtGui.QColor(255, 255, 255, 8)))
            painter.drawRoundedRect(rect, radius, radius)

            # Draw placeholder label
            shelf_name = ""
            if 0 <= self.shelf_index < len(self.manager.shelves):
                shelf_name = self.manager.shelves[self.shelf_index].get("name", "")

            font = painter.font()
            if hasattr(font, "setPointSizeF"):
                font.setPointSizeF(6.5 * self.scale)
            else:
                font.setPointSize(max(5, int(round(6.5 * self.scale))))
            painter.setFont(font)
            painter.setPen(QtGui.QColor(200, 200, 200, 120))

            fm = QtGui.QFontMetrics(font)
            measure_w = fm.horizontalAdvance if hasattr(fm, "horizontalAdvance") else fm.width

            text = f"Empty Shelf ({shelf_name}) - Drop items here" if shelf_name else "Empty Shelf - Drop items here"
            avail_w = max(10, rect.width() - pad * 2)

            if measure_w(text) > avail_w:
                text = "Empty Shelf - Drop items here"
            if measure_w(text) > avail_w:
                text = "Drop items here"

            elided_text = fm.elidedText(text, QtCore.Qt.ElideRight, avail_w)
            painter.drawText(rect, QtCore.Qt.AlignCenter, elided_text)
            painter.end()

        if self._drop_indicator and self._drop_indicator.get("rect"):
            painter = QtGui.QPainter(self)
            painter.setRenderHint(QtGui.QPainter.Antialiasing)

            rect = self._drop_indicator["rect"]
            is_horiz = self._drop_indicator.get("horizontal", False)

            accent_color = QtGui.QColor("#00e5ff")
            glow_color = QtGui.QColor(0, 229, 255, 80)

            # Draw outer glow
            glow_pad = max(1, int(round(1.5 * self.scale)))
            glow_rect = rect.adjusted(-glow_pad, -glow_pad, glow_pad, glow_pad)
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(QtGui.QBrush(glow_color))
            painter.drawRoundedRect(glow_rect, glow_pad, glow_pad)

            # Draw core line
            painter.setBrush(QtGui.QBrush(accent_color))
            radius = max(1, int(round(1 * self.scale)))
            painter.drawRoundedRect(rect, radius, radius)

            # Draw accent dots at endpoints
            dot_r = max(2, int(round(2.5 * self.scale)))
            painter.setBrush(QtGui.QBrush(QtGui.QColor("#ffffff")))
            if is_horiz:
                painter.drawEllipse(QtCore.QPointF(rect.left(), rect.center().y()), dot_r, dot_r)
                painter.drawEllipse(QtCore.QPointF(rect.right(), rect.center().y()), dot_r, dot_r)
            else:
                painter.drawEllipse(QtCore.QPointF(rect.center().x(), rect.top()), dot_r, dot_r)
                painter.drawEllipse(QtCore.QPointF(rect.center().x(), rect.bottom()), dot_r, dot_r)

            painter.end()


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
            self.setWindowFlags(QtCore.Qt.Tool | QtCore.Qt.FramelessWindowHint)
        else:
            self.setWindowFlags(QtCore.Qt.Tool)

    def _apply_stylesheet(self):
        s = self.scale
        font_sz = max(9, int(round(11 * s)))
        base_font_sz = 13
        if self.manager and hasattr(self.manager, "settings"):
            base_font_sz = self.manager.settings.get("FONT_SIZE", 13)
        try:
            base_font_sz = int(base_font_sz)
        except (ValueError, TypeError):
            base_font_sz = 13
        menu_font_sz = max(9, int(round(base_font_sz * s)))
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

        btn_r_setting = 1
        if self.manager and hasattr(self.manager, "settings"):
            val = self.manager.settings.get("BUTTON_RADIUS")
            if val is None:
                val = self.manager.settings.get("BUTTON_CORNER_RADIUS", 1)
            try:
                btn_r_setting = max(0, int(val))
            except (ValueError, TypeError):
                btn_r_setting = 1
        btn_radius = int(round(btn_r_setting * s))

        self.setStyleSheet(f"""
            QWidget#sp_shelf_window_qt {{
                background-color: #373737;
                border: 1px solid #444444;
            }}
            QScrollArea {{
                background: transparent;
                border: none;
            }}
            ShelfButton {{
                background-color: transparent;
                border: 1px solid transparent;
                border-radius: {btn_radius}px;
                padding: 0px;
                margin: 0px;
            }}
            ShelfButton:hover {{
                background-color: #444444;
                border: 1px solid #606060;
                border-radius: {btn_radius}px;
            }}
            ShelfButton:pressed {{
                background-color: #2b2b2b;
                border: 1px solid #373737;
                border-radius: {btn_radius}px;
                padding: 1px 0px 0px 1px;
            }}
            ShelfButton:focus {{
                outline: none;
            }}
            QToolButton {{
                background-color: transparent;
                border: 1px solid transparent;
                padding: 0px;
                margin: 0px;
            }}
            QToolButton:hover {{
                background-color: #444444;
                border: 1px solid #606060;
            }}
            QToolButton:pressed {{
                background-color: #2b2b2b;
                border: 1px solid #373737;
                padding: 1px 0px 0px 1px;
            }}
            QToolButton:focus {{
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
                background-color: #2b2b2b;
                color: #ffffff;
                border: 1px solid #444444;
                padding: {input_pad_v}px {input_pad_h}px;
                font-size: {font_sz}px;
            }}
            QSpinBox:hover {{
                border-color: #606060;
            }}
            QSpinBox:focus {{
                border-color: #5285a6;
            }}
            QComboBox {{
                background-color: #2b2b2b;
                color: #ffffff;
                border: 1px solid #444444;
                padding: {input_pad_v}px {input_pad_h}px;
                font-size: {font_sz}px;
            }}
            QComboBox:hover {{
                border-color: #606060;
            }}
            QComboBox:focus {{
                border-color: #5285a6;
            }}
            QComboBox::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: {combo_drop_w}px;
                border-left: 1px solid #444444;
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
                background-color: #525252;
                color: #ffffff;
                selection-background-color: #5285a6;
                selection-color: #ffffff;
                border: 1px solid #444444;
                font-size: {menu_font_sz}px;
            }}
            QPushButton {{
                background-color: #444444;
                color: #e0e0e0;
                border: 1px solid #505050;
                padding: {btn_pad_v}px {btn_pad_h}px;
                font-size: {font_sz}px;
            }}
            QPushButton:hover {{
                background-color: #525252;
                border-color: #606060;
            }}
            QPushButton:pressed {{
                background-color: #2e2e2e;
                border-color: #404040;
            }}
            QScrollBar:vertical {{
                background: #2b2b2b;
                width: {scrollbar_w}px;
                margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: #505050;
                min-height: {scrollbar_min_h}px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: #606060;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QMenu {{
                background-color: #525252;
                color: #e0e0e0;
                border: 1px solid #444444;
                padding: {menu_pad}px;
                font-size: {menu_font_sz}px;
            }}
            QMenu::item {{
                padding: {menu_item_pad_v}px {menu_item_pad_h}px;
            }}
            QMenu::item:selected {{
                background-color: #5285a6;
                color: #ffffff;
            }}
            QMenu::separator {{
                height: 1px;
                background-color: #444444;
                margin: 2px 4px;
            }}
            QMenu::item:disabled {{
                color: #777777;
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
        base_row_spacing = self.manager.settings.get("ROW_SPACING", 1)
        row_gap = max(0, int(round(base_row_spacing * self.scale)))
        self.container_layout.setSpacing(row_gap)

        self.scroll_area.setWidget(self.container)
        root_layout.addWidget(self.scroll_area)

        # True floating island settings button directly above shelf buttons
        self.settings_btn = SettingsIslandButton(shelf_window=self, scale=self.scale, parent=self)
        self.settings_btn.clicked.connect(self._toggle_settings)
        self.settings_btn.show()

        # Floating island shelf toggle button (mel: ToggleShelf;) to the left of settings
        self.shelf_toggle_btn = ShelfToggleIslandButton(shelf_window=self, scale=self.scale, parent=self)
        self.shelf_toggle_btn.clicked.connect(self._toggle_shelf)
        self.shelf_toggle_btn.show()

        self.rebuild_content()

    def _update_settings_btn_pos(self):
        """Pins the floating island settings button and shelf toggle button to the top-right."""
        if not hasattr(self, "settings_btn") or not self.settings_btn:
            return
        btn_sz = self.settings_btn.width()
        root_pad = max(2, int(round(4 * self.scale)))
        pad_x = root_pad + max(2, int(round(3 * self.scale)))
        btn_gap = max(2, int(round(3 * self.scale)))

        # Check if top shelf has a visible header label
        has_visible_header = False
        if self.manager.shelves:
            first_shelf = self.manager.shelves[0]
            global_label_vis = self.manager.settings.get("SHOW_FRAME_LABEL", True)
            has_visible_header = first_shelf.get("label_visible", global_label_vis)

        if has_visible_header:
            header_h = max(20, int(round(22 * self.scale)))
            y = root_pad + (header_h - btn_sz) // 2
        else:
            y = root_pad + max(1, int(round(2 * self.scale)))

        x = max(0, self.width() - btn_sz - pad_x)
        self.settings_btn.move(x, y)
        self.settings_btn.raise_()

        if hasattr(self, "shelf_toggle_btn") and self.shelf_toggle_btn:
            x_toggle = x - btn_sz - btn_gap
            self.shelf_toggle_btn.move(x_toggle, y)
            self.shelf_toggle_btn.raise_()

    def resizeEvent(self, event):
        super(SpShelfWindow, self).resizeEvent(event)
        self._update_settings_btn_pos()

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
        base_row_spacing = self.manager.settings.get("ROW_SPACING", 1)
        row_gap = max(0, int(round(base_row_spacing * self.scale)))
        self.container_layout.setSpacing(row_gap)

        self.settings_btn.update_scale(self.scale)
        if hasattr(self, "shelf_toggle_btn") and self.shelf_toggle_btn:
            self.shelf_toggle_btn.update_scale(self.scale)
        self._apply_stylesheet()
        self.rebuild_content()
        self._update_settings_btn_pos()

    @staticmethod
    def _clear_layout(layout):
        """Recursively clears all child widgets and sub-layouts from a layout."""
        if not layout:
            return
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
            child_layout = item.layout()
            if child_layout:
                SpShelfWindow._clear_layout(child_layout)

    def rebuild_content(self):
        """Clears and re-populates shelves and settings widgets."""
        cur_vscroll = 0
        if hasattr(self, "scroll_area") and self.scroll_area and self.scroll_area.verticalScrollBar():
            cur_vscroll = self.scroll_area.verticalScrollBar().value()

        # Clear existing items
        self.shelf_sections = []
        self._clear_layout(self.container_layout)

        base_row_spacing = self.manager.settings.get("ROW_SPACING", 1)
        row_gap = max(0, int(round(base_row_spacing * self.scale)))

        self.shelves_layout = QtWidgets.QVBoxLayout()
        self.shelves_layout.setContentsMargins(0, 0, 0, 0)
        self.shelves_layout.setSpacing(row_gap)
        self.container_layout.addLayout(self.shelves_layout)

        # Build Shelves inside self.shelves_layout
        self.rebuild_shelves(adjust_size=False)

        # Settings Section
        self._build_settings_section()
        settings_collapsed = self.manager.settings.get("SETTINGS_COLLAPSED", True)
        if not self.manager.shelves:
            settings_collapsed = False
        self.settings_section.setVisible(not settings_collapsed)
        if not settings_collapsed:
            self.settings_section.set_collapsed(False)
        self.settings_btn.setChecked(not settings_collapsed)
        self._update_shelf_toggle_btn_state()

        self.container_layout.addStretch()

        self.adjust_size_to_content()
        if cur_vscroll > 0 and hasattr(self, "scroll_area") and self.scroll_area:
            QtCore.QTimer.singleShot(15, lambda: self.scroll_area.verticalScrollBar().setValue(cur_vscroll))

    def rebuild_shelves(self, adjust_size=True):
        """Clears and re-populates only the shelf sections without touching settings_section."""
        cur_vscroll = 0
        if hasattr(self, "scroll_area") and self.scroll_area and self.scroll_area.verticalScrollBar():
            cur_vscroll = self.scroll_area.verticalScrollBar().value()

        if not hasattr(self, "shelves_layout") or self.shelves_layout is None:
            self.rebuild_content()
            return

        self.shelf_sections = []
        self._clear_layout(self.shelves_layout)

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
                shelf_index=shelf_idx,
                parent=self.container
            )
            self.shelf_sections.append(section)

            # Shelf and Header context menu
            section.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
            section.customContextMenuRequested.connect(
                lambda pos, idx=shelf_idx, sec=section: self._show_shelf_header_menu(pos, idx, sec, sec)
            )

            section.header_btn.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
            section.header_btn.customContextMenuRequested.connect(
                lambda pos, idx=shelf_idx, sec=section: self._show_shelf_header_menu(pos, idx, sec, sec.header_btn)
            )

            # Grid layout container with MMB Drag & Drop support
            grid_widget = ShelfGridWidget(
                shelf_index=shelf_idx,
                shelf_window=self,
                manager=self.manager,
                scale=self.scale,
                col_count=col_count,
                parent=section.content_widget
            )
            grid_widget.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
            grid_widget.customContextMenuRequested.connect(
                lambda pos, idx=shelf_idx, sec=section, gw=grid_widget: self._show_shelf_header_menu(pos, idx, sec, gw)
            )

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
                        grid_widget.add_shelf_item(sep, cur_row, 0)
                        cur_row += 1
                        cur_col = 0
                    else:
                        grid_widget.add_shelf_item(sep, cur_row, cur_col)
                else:
                    btn = ShelfButton(
                        button_data=b,
                        shelf_index=shelf_idx,
                        button_index=btn_idx,
                        shelf_manager=self.manager,
                        scale=self.scale,
                        parent=grid_widget
                    )
                    if cur_col >= col_count:
                        cur_col = 0
                        cur_row += 1
                    grid_widget.add_shelf_item(btn, cur_row, cur_col)
                    cur_col += 1

            if not shelf.get("buttons"):
                btn_sz = max(24, int(round(38 * self.scale)))
                grid_widget.setMinimumHeight(btn_sz)

            section.content_layout.addWidget(grid_widget)
            self.shelves_layout.addWidget(section)

        self._update_shelf_toggle_btn_state()

        if adjust_size:
            self.adjust_size_to_content()
            if cur_vscroll > 0 and hasattr(self, "scroll_area") and self.scroll_area:
                QtCore.QTimer.singleShot(15, lambda: self.scroll_area.verticalScrollBar().setValue(cur_vscroll))

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
        self._update_settings_btn_pos()
        log_debug(f"_do_adjust_size: END. Result win size={self.width()}x{self.height()}")

    def _show_shelf_header_menu(self, pos, shelf_index, section, parent_widget=None):
        target = parent_widget or section.header_btn
        parent_win = self.window() if hasattr(self, "window") and self.window() else self
        menu = QtWidgets.QMenu(parent_win)

        target_idx = None
        if isinstance(target, ShelfGridWidget):
            try:
                target_idx, _, _ = target._calculate_target_slot(pos)
            except Exception:
                target_idx = None

        add_sep_action = menu.addAction("Add Separator")
        add_sep_action.triggered.connect(lambda: self.manager.add_separator(shelf_index, target_idx))

        add_shelf_action = menu.addAction("Add Empty Shelf")
        add_shelf_action.triggered.connect(lambda: self.manager.add_empty_shelf())

        menu.addSeparator()

        move_up_action = menu.addAction("Move Shelf Up")
        move_up_action.setEnabled(shelf_index > 0)
        move_up_action.triggered.connect(lambda: self.manager.move_shelf(shelf_index, shelf_index - 1))

        move_down_action = menu.addAction("Move Shelf Down")
        move_down_action.setEnabled(shelf_index < len(self.manager.shelves) - 1)
        move_down_action.triggered.connect(lambda: self.manager.move_shelf(shelf_index, shelf_index + 1))

        menu.addSeparator()

        rename_action = menu.addAction("Rename Shelf")
        rename_action.triggered.connect(lambda: self.manager.rename_shelf(shelf_index))

        vis = self.manager.shelves[shelf_index].get("label_visible", True)
        label_action = menu.addAction("Hide Label" if vis else "Show Label")
        label_action.triggered.connect(lambda: self.manager.toggle_single_shelf_label(shelf_index, not vis))

        del_action = menu.addAction("Delete Shelf")
        del_action.triggered.connect(lambda: self.manager.delete_shelf(shelf_index))

        menu.exec_(target.mapToGlobal(pos))

    def _toggle_settings(self):
        new_open = not self.settings_section.isVisible()
        log_debug(f"_toggle_settings: new_open={new_open}")
        self.settings_section.setVisible(new_open)
        if new_open:
            self.settings_section.set_collapsed(False)
        self.settings_btn.setChecked(new_open)
        self.manager.on_settings_collapse("SETTINGS_COLLAPSED", not new_open)
        self.adjust_size_to_content()
        if new_open:
            QtCore.QTimer.singleShot(20, lambda: self.scroll_area.ensureWidgetVisible(self.settings_section))

    def _toggle_shelf(self):
        log_debug("_toggle_shelf: executing ToggleShelf;")
        try:
            mel.eval("ToggleShelf;")
        except Exception as e:
            log_debug(f"_toggle_shelf error: {e}")
        self._update_shelf_toggle_btn_state()
        QtCore.QTimer.singleShot(50, self._update_shelf_toggle_btn_state)

    def _update_shelf_toggle_btn_state(self):
        if hasattr(self, "shelf_toggle_btn") and self.shelf_toggle_btn:
            self.shelf_toggle_btn.update_shelf_state()

    def showEvent(self, event):
        super(SpShelfWindow, self).showEvent(event)
        self._update_shelf_toggle_btn_state()
        self._update_settings_btn_pos()

    def _on_settings_collapse_changed(self, collapsed):
        log_debug(f"_on_settings_collapse_changed: collapsed={collapsed}")
        self.manager.on_settings_collapse("SETTINGS_COLLAPSED", collapsed)
        if collapsed:
            self.settings_section.setVisible(False)
            self.settings_btn.setChecked(False)
        else:
            self.settings_section.setVisible(True)
            self.settings_btn.setChecked(True)
        self.adjust_size_to_content()

    def _build_settings_section(self):
        settings_collapsed = self.manager.settings.get("SETTINGS_COLLAPSED", True)
        if not self.manager.shelves:
            settings_collapsed = False

        self.settings_section = CollapsibleSection(
            title="Settings",
            collapsed=settings_collapsed,
            label_visible=True,
            on_collapse_changed=self._on_settings_collapse_changed,
            shelf_window=self,
            scale=self.scale,
            parent=self.container
        )
        settings_section = self.settings_section
        settings_pad = max(2, int(round(4 * self.scale)))
        settings_section.content_layout.setContentsMargins(settings_pad, settings_pad, settings_pad, settings_pad)
        settings_section.content_layout.setSpacing(settings_pad)
        settings_section.layout().setContentsMargins(0, max(2, int(round(4 * self.scale))), 0, 0)

        layout = settings_section.content_layout
        btn_h = max(24, int(round(26 * self.scale)))
        font_sz = max(9, int(round(11 * self.scale)))

        # Add current shelf button
        add_shelf_btn = QtWidgets.QPushButton("Add Current Shelf", settings_section)
        add_shelf_btn.setStyleSheet(f"background-color: #5285a6; color: #ffffff; font-weight: bold; min-height: {btn_h}px;")
        add_shelf_btn.setFixedHeight(btn_h)
        add_shelf_btn.clicked.connect(self.manager.add_current_shelf)
        layout.addWidget(add_shelf_btn)

        # Add empty shelf button
        add_empty_shelf_btn = QtWidgets.QPushButton("Add Empty Shelf", settings_section)
        add_empty_shelf_btn.setStyleSheet(f"background-color: #5285a6; color: #ffffff; font-weight: bold; min-height: {btn_h}px;")
        add_empty_shelf_btn.setFixedHeight(btn_h)
        add_empty_shelf_btn.clicked.connect(lambda: self.manager.add_empty_shelf())
        layout.addWidget(add_empty_shelf_btn)

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
        self.col_spin.setRange(1, 30)
        self.col_spin.setValue(self.manager.settings.get("COLUMN_COUNT", 4))
        col_layout.addWidget(col_lbl)
        col_layout.addWidget(self.col_spin)
        layout.addLayout(col_layout)

        # Row spacing row
        row_spacing_layout = QtWidgets.QHBoxLayout()
        row_spacing_lbl = QtWidgets.QLabel("Row spacing:", settings_section)
        row_spacing_lbl.setStyleSheet(f"color: #cccccc; font-size: {font_sz}px;")
        self.row_spacing_spin = QtWidgets.QSpinBox(settings_section)
        self.row_spacing_spin.setFixedHeight(btn_h)
        self.row_spacing_spin.setRange(0, 30)
        self.row_spacing_spin.setSuffix(" px")
        self.row_spacing_spin.setValue(self.manager.settings.get("ROW_SPACING", 1))
        row_spacing_layout.addWidget(row_spacing_lbl)
        row_spacing_layout.addWidget(self.row_spacing_spin)
        layout.addLayout(row_spacing_layout)

        # Button corner radius row
        btn_radius_layout = QtWidgets.QHBoxLayout()
        btn_radius_lbl = QtWidgets.QLabel("Button radius:", settings_section)
        btn_radius_lbl.setStyleSheet(f"color: #cccccc; font-size: {font_sz}px;")
        self.btn_radius_spin = QtWidgets.QSpinBox(settings_section)
        self.btn_radius_spin.setFixedHeight(btn_h)
        self.btn_radius_spin.setRange(0, 30)
        self.btn_radius_spin.setSuffix(" px")
        btn_rad_val = self.manager.settings.get("BUTTON_RADIUS")
        if btn_rad_val is None:
            btn_rad_val = self.manager.settings.get("BUTTON_CORNER_RADIUS", 1)
        self.btn_radius_spin.setValue(int(btn_rad_val))
        self.btn_radius_spin.valueChanged.connect(self._on_btn_radius_live_changed)
        btn_radius_layout.addWidget(btn_radius_lbl)
        btn_radius_layout.addWidget(self.btn_radius_spin)
        layout.addLayout(btn_radius_layout)

        # Base font size row
        font_size_layout = QtWidgets.QHBoxLayout()
        font_size_lbl = QtWidgets.QLabel("Font size:", settings_section)
        font_size_lbl.setStyleSheet(f"color: #cccccc; font-size: {font_sz}px;")
        self.font_size_spin = QtWidgets.QSpinBox(settings_section)
        self.font_size_spin.setFixedHeight(btn_h)
        self.font_size_spin.setRange(8, 30)
        self.font_size_spin.setSuffix(" px")
        font_size_val = self.manager.settings.get("FONT_SIZE", 13)
        self.font_size_spin.setValue(int(font_size_val))
        self.font_size_spin.valueChanged.connect(self._on_font_size_live_changed)
        font_size_layout.addWidget(font_size_lbl)
        font_size_layout.addWidget(self.font_size_spin)
        layout.addLayout(font_size_layout)

        # Checkboxes
        self.cb_close_repeat = QtWidgets.QCheckBox("Close on Key Release", settings_section)
        self.cb_close_repeat.setChecked(self.manager.settings.get("CLOSE_ON_REPEAT_FLAG", False))
        self.cb_close_repeat.toggled.connect(self._on_toggle_close_repeat)

        self.cb_under_cursor = QtWidgets.QCheckBox("Open under Cursor", settings_section)
        self.cb_under_cursor.setChecked(self.manager.settings.get("SHOW_WINDOW_UNDER_CURSOR", True))
        self.cb_under_cursor.toggled.connect(self._on_toggle_under_cursor)

        self.cb_show_label = QtWidgets.QCheckBox("Show Frame Label", settings_section)
        self.cb_show_label.setChecked(self.manager.settings.get("SHOW_FRAME_LABEL", True))
        self.cb_show_label.toggled.connect(self._on_toggle_show_frame_label)

        self.cb_hide_title = QtWidgets.QCheckBox("Hide Title Bar", settings_section)
        self.cb_hide_title.setChecked(self.manager.settings.get("HIDE_TITLE_BAR", False))
        self.cb_hide_title.toggled.connect(self._on_toggle_hide_title)

        self.cb_show_sep = QtWidgets.QCheckBox("Show Separators", settings_section)
        self.cb_show_sep.setChecked(self.manager.settings.get("SHOW_SEPARATORS", True))
        self.cb_show_sep.toggled.connect(self._on_toggle_show_sep)

        self.cb_horiz_sep = QtWidgets.QCheckBox("Horizontal Separators", settings_section)
        self.cb_horiz_sep.setChecked(self.manager.settings.get("HORIZONTAL_SEPARATORS", False))
        self.cb_horiz_sep.toggled.connect(self._on_toggle_horiz_sep)

        self.cb_dotted_sep = QtWidgets.QCheckBox("Dotted Style", settings_section)
        self.cb_dotted_sep.setChecked(self.manager.settings.get("DOTTED_SEPARATORS", False))
        self.cb_dotted_sep.toggled.connect(self._on_toggle_dotted_sep)

        for cb in [self.cb_close_repeat, self.cb_under_cursor, self.cb_show_label,
                   self.cb_hide_title, self.cb_show_sep, self.cb_horiz_sep, self.cb_dotted_sep]:
            layout.addWidget(cb)

        # Save Settings button
        save_btn = QtWidgets.QPushButton("Save Settings", settings_section)
        save_btn.setStyleSheet(f"background-color: #5285a6; color: #ffffff; font-weight: bold; min-height: {btn_h}px;")
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

    def _on_toggle_close_repeat(self, checked):
        log_debug(f"_on_toggle_close_repeat: checked={checked}")
        self.manager.settings["CLOSE_ON_REPEAT_FLAG"] = checked
        self.manager.save_user_data()

    def _on_toggle_under_cursor(self, checked):
        log_debug(f"_on_toggle_under_cursor: checked={checked}")
        self.manager.settings["SHOW_WINDOW_UNDER_CURSOR"] = checked
        self.manager.save_user_data()

    def _on_toggle_show_frame_label(self, checked):
        log_debug(f"_on_toggle_show_frame_label: checked={checked}")
        self.manager.toggle_frame_labels(checked)

    def _on_toggle_hide_title(self, checked):
        log_debug(f"_on_toggle_hide_title: checked={checked}")
        self.manager.settings["HIDE_TITLE_BAR"] = checked
        self.manager.save_user_data()
        cur_pos = self.pos()
        self._configure_window_flags()
        self.show()
        self.move(cur_pos)
        self.adjust_size_to_content()
        self._update_settings_btn_pos()

    def _on_toggle_show_sep(self, checked):
        log_debug(f"_on_toggle_show_sep: checked={checked}")
        self.manager.settings["SHOW_SEPARATORS"] = checked
        self.manager.save_user_data()
        self.rebuild_shelves()

    def _on_toggle_horiz_sep(self, checked):
        log_debug(f"_on_toggle_horiz_sep: checked={checked}")
        self.manager.settings["HORIZONTAL_SEPARATORS"] = checked
        self.manager.save_user_data()
        self.rebuild_shelves()

    def _on_toggle_dotted_sep(self, checked):
        log_debug(f"_on_toggle_dotted_sep: checked={checked}")
        self.manager.settings["DOTTED_SEPARATORS"] = checked
        self.manager.save_user_data()
        self.rebuild_shelves()

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
        self._update_settings_btn_pos()

    def _on_btn_radius_live_changed(self, val):
        """Live updates button corner radius across shelf buttons and repaints window."""
        self.manager.settings["BUTTON_RADIUS"] = val
        self._apply_stylesheet()
        self.update()

    def _on_font_size_live_changed(self, val):
        """Live updates base font size across menus and shelf headers."""
        self.manager.settings["FONT_SIZE"] = val
        self._apply_stylesheet()
        for sec in self.shelf_sections:
            if hasattr(sec, "update_font_size"):
                sec.update_font_size(val)
        if hasattr(self, "settings_section") and hasattr(self.settings_section, "update_font_size"):
            self.settings_section.update_font_size(val)
        self.adjust_size_to_content()
        self.update()

    def _save_settings_from_ui(self):
        self.manager.settings["COLUMN_COUNT"] = self.col_spin.value()
        self.manager.settings["ROW_SPACING"] = self.row_spacing_spin.value()
        self.manager.settings["BUTTON_RADIUS"] = self.btn_radius_spin.value()
        self.manager.settings["FONT_SIZE"] = self.font_size_spin.value()
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

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            pos = event.globalPosition().toPoint() if hasattr(event, "globalPosition") else event.globalPos()
            self._drag_pos = pos - self.frameGeometry().topLeft()
            event.accept()
        else:
            super(SpShelfWindow, self).mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() == QtCore.Qt.LeftButton and getattr(self, "_drag_pos", None) is not None:
            pos = event.globalPosition().toPoint() if hasattr(event, "globalPosition") else event.globalPos()
            self.move(pos - self._drag_pos)
            event.accept()
        else:
            super(SpShelfWindow, self).mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        super(SpShelfWindow, self).mouseReleaseEvent(event)


# ----------------------------------------------------------------------
# Manager Controller
# ----------------------------------------------------------------------
class SpShelf:
    DEFAULT_SETTINGS = {
        "COLUMN_COUNT": 5,
        "ROW_SPACING": 1,
        "BUTTON_RADIUS": 3,
        "FONT_SIZE": 13,
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
        self._button_editor = None

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

                # Auto-sanitize and heal any commands / menuItems that may be corrupted or wrapped
                for shelf in self.shelves:
                    clean_buttons = []
                    for btn in shelf.get("buttons", []):
                        if not isinstance(btn, dict):
                            continue
                        if btn.get("type") == "separator":
                            clean_buttons.append(btn)
                            continue
                        # Skip orphaned/corrupted empty buttons that have no button properties
                        has_identity = any([
                            btn.get("image"),
                            btn.get("image1"),
                            btn.get("command"),
                            btn.get("label"),
                            btn.get("imageOverlayLabel"),
                            btn.get("annotation"),
                            btn.get("menuItems"),
                        ])
                        if not has_identity:
                            continue
                        if "command" in btn and btn["command"]:
                            _, clean_c, c_type = sanitize_command(btn["command"], btn.get("label", ""))
                            btn["command"] = clean_c
                            if c_type == "python":
                                btn["sourceType"] = "python"
                        if "doubleClickCommand" in btn and btn["doubleClickCommand"]:
                            _, clean_dc, _ = sanitize_command(btn["doubleClickCommand"])
                            btn["doubleClickCommand"] = clean_dc
                        filtered_mis = []
                        for mi in btn.get("menuItems", []):
                            m_cmd = mi.get("command", "")
                            m_lbl = mi.get("label", "")
                            if is_default_maya_menu_item(m_cmd, m_lbl):
                                continue
                            if m_cmd:
                                fixed_lbl, clean_m_cmd, m_type = sanitize_command(m_cmd, m_lbl)
                                mi["label"] = fixed_lbl
                                mi["command"] = clean_m_cmd
                                mi["sourceType"] = m_type
                            if "optionBoxCommand" in mi and mi["optionBoxCommand"]:
                                _, clean_opt, opt_type = sanitize_command(mi["optionBoxCommand"])
                                mi["optionBoxCommand"] = clean_opt
                                mi["optionBoxSourceType"] = opt_type
                            filtered_mis.append(mi)
                        if filtered_mis:
                            btn["menuItems"] = filtered_mis
                        elif "menuItems" in btn:
                            del btn["menuItems"]
                        clean_buttons.append(btn)
                    shelf["buttons"] = clean_buttons
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
            # Auto-detect if command is wrapped in MEL's python(...) syntax or corrupted
            _, clean_cmd, detected_type = sanitize_command(command)
            if detected_type == "python":
                command = clean_cmd
                source_type = "python"
            else:
                command = clean_cmd

            try:
                command = command.encode('utf-8').decode('unicode_escape')
            except Exception:
                pass

            if source_type.lower() == "python":
                log_debug(f"Executing Python command:\n{command}")
                exec(command, globals())
            else:
                log_debug(f"Executing MEL command:\n{command}")
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
                    self.window_widget.adjust_size_to_content()

    def rename_shelf(self, shelf_index):
        """
        Prompts the user to rename an existing shelf.
        """
        if not (0 <= shelf_index < len(self.shelves)):
            return
        cur_name = self.shelves[shelf_index].get("name", "")
        try:
            res = cmds.promptDialog(
                title="Rename Shelf",
                message="Enter Shelf Name:",
                text=cur_name,
                button=["OK", "Cancel"],
                defaultButton="OK",
                cancelButton="Cancel",
                dismissString="Cancel"
            )
            if res != "OK":
                return
            new_name = cmds.promptDialog(query=True, text=True).strip()
            if new_name and new_name != cur_name:
                self.shelves[shelf_index]["name"] = new_name
                self.save_user_data()
                if self.window_widget:
                    self.window_widget.rebuild_content()
                    self.window_widget.adjust_size_to_content()
        except Exception as e:
            log_debug(f"rename_shelf error: {e}")

    def move_shelf(self, source_idx, target_idx):
        """
        Reorders shelves by moving the shelf at source_idx to target_idx.
        Saves updated shelf order to JSON and rebuilds the UI.
        """
        total = len(self.shelves)
        if not (0 <= source_idx < total):
            return
        if not (0 <= target_idx < total):
            return
        if source_idx == target_idx:
            return

        shelf = self.shelves.pop(source_idx)
        self.shelves.insert(target_idx, shelf)
        self.save_user_data()
        if self.window_widget:
            self.window_widget.rebuild_content()

    def add_separator(self, shelf_idx, target_idx=None):
        """
        Adds a separator to the specified shelf.
        If target_idx is provided, inserts at target_idx; otherwise appends to the end of the shelf.
        Ensures SHOW_SEPARATORS is enabled and uncollapses the shelf if collapsed.
        """
        if not (0 <= shelf_idx < len(self.shelves)):
            return
        shelf = self.shelves[shelf_idx]
        buttons = shelf.setdefault("buttons", [])
        if target_idx is None or target_idx < 0 or target_idx > len(buttons):
            target_idx = len(buttons)

        buttons.insert(target_idx, {"type": "separator"})

        if not self.settings.get("SHOW_SEPARATORS", True):
            self.settings["SHOW_SEPARATORS"] = True

        if shelf.get("collapsed", False):
            shelf["collapsed"] = False

        self.save_user_data()
        if self.window_widget:
            self.window_widget.rebuild_content()

    def move_shelf_item(self, source_shelf_idx, source_item_idx, target_shelf_idx, target_item_idx):
        """
        Moves an item (button or separator) from source shelf to target shelf.
        Supports both intra-shelf reordering and inter-shelf transfers with immediate JSON persistence.
        """
        log_debug(f"move_shelf_item: src=({source_shelf_idx}, {source_item_idx}) -> dst=({target_shelf_idx}, {target_item_idx})")
        if not (0 <= source_shelf_idx < len(self.shelves)):
            return
        if not (0 <= target_shelf_idx < len(self.shelves)):
            return

        src_shelf = self.shelves[source_shelf_idx]
        src_buttons = src_shelf.setdefault("buttons", [])
        if not (0 <= source_item_idx < len(src_buttons)):
            return

        dst_shelf = self.shelves[target_shelf_idx]
        dst_buttons = dst_shelf.setdefault("buttons", [])

        target_item_idx = max(0, min(target_item_idx, len(dst_buttons)))

        if source_shelf_idx == target_shelf_idx:
            # Intra-shelf reordering: dropping back to the exact same position is a no-op
            if target_item_idx == source_item_idx or target_item_idx == source_item_idx + 1:
                return

            item = src_buttons.pop(source_item_idx)
            if source_item_idx < target_item_idx:
                target_item_idx -= 1
            src_buttons.insert(target_item_idx, item)
        else:
            # Inter-shelf transfer
            item = src_buttons.pop(source_item_idx)
            dst_buttons.insert(target_item_idx, item)

        self.save_user_data()
        if self.window_widget:
            self.window_widget.rebuild_content()

    def insert_external_button(self, shelf_idx, target_idx, button_data):
        """
        Inserts a new button (e.g. copied from Maya native shelf or script editor)
        into the specified shelf at target_idx, saves to JSON, and updates the UI.
        """
        log_debug(f"insert_external_button: shelf={shelf_idx}, target_idx={target_idx}, data={button_data.get('label')}")
        if not (0 <= shelf_idx < len(self.shelves)):
            return

        shelf = self.shelves[shelf_idx]
        buttons = shelf.setdefault("buttons", [])
        target_idx = max(0, min(target_idx, len(buttons)))

        buttons.insert(target_idx, button_data)
        self.save_user_data()

        if self.window_widget:
            self.window_widget.rebuild_content()

    def open_button_editor(self, shelf_idx, button_idx):
        """
        Opens the button editor dialog for the specified shelf button.
        """
        log_debug(f"open_button_editor: shelf={shelf_idx}, button={button_idx}")
        if not (0 <= shelf_idx < len(self.shelves)):
            cmds.warning(f"spShelf: Invalid shelf index {shelf_idx}")
            return
        shelf = self.shelves[shelf_idx]
        buttons = shelf.get("buttons", [])
        if not (0 <= button_idx < len(buttons)):
            cmds.warning(f"spShelf: Invalid button index {button_idx}")
            return

        button_data = buttons[button_idx]
        if not isinstance(button_data, dict) or button_data.get("type") == "separator":
            cmds.warning("spShelf: Cannot edit separators with button editor.")
            return

        # Close existing editor if open
        if hasattr(self, "_button_editor") and self._button_editor is not None:
            try:
                self._button_editor.close()
                self._button_editor.deleteLater()
            except Exception:
                pass
            self._button_editor = None

        self._button_editor = ButtonEditorDialog(
            shelf_manager=self,
            shelf_index=shelf_idx,
            button_index=button_idx,
            button_data=button_data,
            scale=self.get_ui_scale(),
            parent=get_maya_main_window()
        )
        self._button_editor.show()
        self._button_editor.raise_()
        self._button_editor.activateWindow()

    def save_button_data(self, shelf_idx, button_idx, updated_button_data):
        """
        Updates the button data at the specified shelf index and button index,
        saves to JSON file, and rebuilds the UI.
        """
        log_debug(f"save_button_data: shelf={shelf_idx}, button={button_idx}, label={updated_button_data.get('label')}")
        if not (0 <= shelf_idx < len(self.shelves)):
            return False
        shelf = self.shelves[shelf_idx]
        buttons = shelf.setdefault("buttons", [])
        if not (0 <= button_idx < len(buttons)):
            return False

        buttons[button_idx] = updated_button_data
        self.save_user_data()

        if self.window_widget:
            self.window_widget.rebuild_content()
            self.window_widget.adjust_size_to_content()
        return True

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

        def _finalize_item(item):
            if not item:
                return None
            if item.get("type") == "separator":
                return item
            # Valid button must have at least an image, command, label, annotation, or menuItems
            has_identity = any([
                item.get("image"),
                item.get("image1"),
                item.get("command"),
                item.get("label"),
                item.get("imageOverlayLabel"),
                item.get("annotation"),
                item.get("menuItems"),
            ])
            if not has_identity:
                return None
            enable_bg = item.pop("_enableBackground", None)
            parsed_bg = item.pop("_parsedBackgroundColor", None)
            if enable_bg is True and parsed_bg is not None:
                item["backgroundColor"] = parsed_bg
                item["buttonBackground"] = parsed_bg
                item["enableBackground"] = True
            elif enable_bg is None and parsed_bg is not None:
                item["backgroundColor"] = parsed_bg
                item["buttonBackground"] = parsed_bg
                item["enableBackground"] = True
            cmd = item.get("command", "")
            if cmd:
                clean_cmd, detected_type = extract_command_and_type(cmd)
                if detected_type == "python":
                    item["command"] = clean_cmd
                    item["sourceType"] = "python"
            return item

        button_data = {}
        current_command = None
        for line in lines:
            line = line.strip()
            if line.startswith("shelfButton"):
                if current_command == "shelfButton":
                    fin = _finalize_item(button_data)
                    if fin:
                        buttons.append(fin)
                button_data = {}
                current_command = "shelfButton"
            elif line.startswith("separator"):
                if current_command == "shelfButton":
                    fin = _finalize_item(button_data)
                    if fin:
                        buttons.append(fin)
                buttons.append({"type": "separator"})
                button_data = {}
                current_command = "separator"
            elif line.startswith(";") or line == ";":
                if current_command == "shelfButton":
                    fin = _finalize_item(button_data)
                    if fin:
                        buttons.append(fin)
                    button_data = {}
                current_command = None
            elif current_command == "shelfButton":
                if line.startswith("-overlayLabelColor"):
                    try:
                        tokens = line.rstrip(";").split()
                        vals = [round(float(x), 4) for x in tokens[1:]]
                        if len(vals) >= 3:
                            button_data["overlayLabelColor"] = vals[:3]
                            button_data["labelColor"] = vals[:3]
                    except Exception:
                        pass
                elif line.startswith("-overlayLabelBackColor"):
                    try:
                        tokens = line.rstrip(";").split()
                        vals = [round(float(x), 4) for x in tokens[1:]]
                        if len(vals) >= 3:
                            button_data["overlayLabelBackColor"] = vals
                            button_data["labelBackground"] = vals[:3]
                            if len(vals) >= 4:
                                button_data["backgroundTransparency"] = vals[3]
                    except Exception:
                        pass
                elif line.startswith("-enableBackground"):
                    try:
                        tokens = line.rstrip(";").split()
                        button_data["_enableBackground"] = bool(int(tokens[1]))
                    except Exception:
                        pass
                elif line.startswith("-backgroundColor"):
                    try:
                        tokens = line.rstrip(";").split()
                        vals = [round(float(x), 4) for x in tokens[1:]]
                        if len(vals) >= 3:
                            button_data["_parsedBackgroundColor"] = vals[:3]
                    except Exception:
                        pass
                elif re.search(r'-m(?:io?|enuItem(?:WithOptionBox)?)\s+"', line):
                    # 1. First parse any -mio / -menuItemWithOptionBox matches
                    for m in re.finditer(r'-m(?:io|enuItemWithOptionBox)\s+"((?:\\.|[^"\\])*)"\s*\(\s*"((?:\\.|[^"\\])*)"\s*\)\s*\(\s*"((?:\\.|[^"\\])*)"\s*\)', line):
                        raw_label = m.group(1)
                        raw_cmd = m.group(2)
                        raw_opt = m.group(3)
                        label = raw_label.replace(r'\"', '"').replace(r'\\', '\\')
                        clean_cmd, cmd_type = extract_command_and_type(raw_cmd.replace(r'\"', '"').replace(r'\\', '\\'))
                        if is_default_maya_menu_item(clean_cmd, label):
                            continue
                        clean_opt, opt_type = extract_command_and_type(raw_opt.replace(r'\"', '"').replace(r'\\', '\\'))
                        button_data.setdefault("menuItems", []).append({
                            "label": label,
                            "command": clean_cmd,
                            "sourceType": cmd_type,
                            "optionBoxCommand": clean_opt,
                            "optionBoxSourceType": opt_type
                        })
                    # 2. Parse standard -mi / -menuItem matches
                    for m in re.finditer(r'-m(?:i|enuItem)\s+"((?:\\.|[^"\\])*)"\s*\(\s*"((?:\\.|[^"\\])*)"\s*\)', line):
                        raw_label = m.group(1)
                        raw_cmd = m.group(2)
                        label = raw_label.replace(r'\"', '"').replace(r'\\', '\\')
                        unescaped_cmd = raw_cmd.replace(r'\"', '"').replace(r'\\', '\\')
                        clean_cmd, cmd_type = extract_command_and_type(unescaped_cmd)
                        if is_default_maya_menu_item(clean_cmd, label):
                            continue
                        button_data.setdefault("menuItems", []).append({
                            "label": label,
                            "command": clean_cmd,
                            "sourceType": cmd_type
                        })
                elif (line.startswith("-width") or line.startswith("-w ")) and not line.startswith("-marginWidth"):
                    try:
                        tokens = line.rstrip(";").split()
                        if len(tokens) >= 2:
                            w_val = int(float(tokens[1]))
                            if w_val > 0:
                                button_data["width"] = w_val
                    except Exception:
                        pass
                elif line.startswith("-flexibleWidthType"):
                    try:
                        tokens = line.rstrip(";").split()
                        if len(tokens) >= 2:
                            button_data["flexibleWidthType"] = int(tokens[1])
                    except Exception:
                        pass
                elif line.startswith("-flexibleWidthValue"):
                    try:
                        tokens = line.rstrip(";").split()
                        if len(tokens) >= 2:
                            button_data["flexibleWidthValue"] = int(tokens[1])
                    except Exception:
                        pass
                elif any(line.startswith(k) for k in ["-label", "-image", "-annotation", "-command", "-sourceType", "-doubleClickCommand", "-style"]):
                    parts = line.split("\"", 1)
                    if len(parts) > 1:
                        key = line.split()[0][1:]
                        button_data[key] = parts[1].rsplit("\"", 1)[0]

        if current_command == "shelfButton":
            fin = _finalize_item(button_data)
            if fin:
                buttons.append(fin)

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

    def add_empty_shelf(self, shelf_name=None):
        """
        Creates a new empty shelf and appends it to the shelf list.
        Prompts the user for a shelf name via Maya promptDialog if not provided.
        """
        log_debug("add_empty_shelf invoked")
        default_name = "Shelf_1"
        if not shelf_name:
            existing_names = [s.get("name", "") for s in self.shelves]
            counter = len(self.shelves) + 1
            default_name = f"Shelf_{counter}"
            while default_name in existing_names or f"Shelf {counter}" in existing_names:
                counter += 1
                default_name = f"Shelf_{counter}"

            try:
                res = cmds.promptDialog(
                    title="New Empty Shelf",
                    message="Enter Shelf Name:",
                    text=default_name,
                    button=["OK", "Cancel"],
                    defaultButton="OK",
                    cancelButton="Cancel",
                    dismissString="Cancel"
                )
                if res != "OK":
                    return
                shelf_name = cmds.promptDialog(query=True, text=True)
            except Exception as e:
                log_debug(f"cmds.promptDialog error: {e}")
                shelf_name = default_name

        shelf_name = (shelf_name or "").strip()
        if not shelf_name:
            shelf_name = default_name

        global_vis = self.settings.get("SHOW_FRAME_LABEL", True)
        self.shelves.append({
            "name": shelf_name,
            "buttons": [],
            "collapsed": False,
            "label_visible": global_vis
        })
        self.save_user_data()
        if self.window_widget:
            self.window_widget.rebuild_content()
            self.window_widget.adjust_size_to_content()
        cmds.warning(f"Empty shelf '{shelf_name}' added successfully.")

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