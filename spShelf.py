# spShelf v1.1.0
# v1.0.0 - First version
# v1.0.1 - Added a 0.2-second delay before closing the window.
# v1.1.0 - Refactored to Class-based structure, removed globals.
#          Added auto-resizing, live settings toggles, and per-shelf label visibility.
#          Implemented persistence for shelf collapse states and immediate saving.

import maya.cmds as cmds
import maya.mel as mel
import os
import json
import time

try:
    from PySide6.QtGui import QCursor
except ImportError:
    try:
        from PySide2.QtGui import QCursor
    except ImportError:
        QCursor = None

class SpShelf:
    WINDOW_NAME = "sp_shelf_window_main"
    DEFAULT_WINDOW = {"width": 200, "height": 200}
    DEFAULT_SETTINGS = {
        "COLUMN_COUNT": 4, 
        "SCREEN_HEIGHT": 1600, 
        "CLOSE_ON_REPEAT_FLAG": False, 
        "SHOW_WINDOW_UNDER_CURSOR": True, 
        "SHOW_FRAME_LABEL": True, 
        "TOOLBOX_WINDOW_STYLE": False,
        "SETTINGS_COLLAPSED": True,
        "DELETE_COLLAPSED": True
    }

    def __init__(self):
        self.user_app_dir = cmds.internalVar(userAppDir=True)
        self.user_version = cmds.about(version=True)
        self.user_data_file = os.path.join(self.user_app_dir, self.user_version, 'scripts', 'sp_shelf_data.json')
        
        # UI Elements references
        self.column_input = None
        self.screen_height_input = None
        self.close_on_repeat_toggle = None
        self.show_window_under_cursor_toggle = None
        self.show_frame_label_toggle = None
        self.toolbox_style_window_toggle = None
        
        self.shelves = []
        self.window_data = self.DEFAULT_WINDOW.copy()
        self.settings = self.DEFAULT_SETTINGS.copy()
        
        self.load_user_data()

    def load_user_data(self):
        if os.path.exists(self.user_data_file):
            try:
                with open(self.user_data_file, 'r') as f:
                    data = json.load(f)
                self.shelves = data.get("shelves", [])
                self.window_data = data.get("window", self.DEFAULT_WINDOW)
                self.settings = data.get("settings", self.DEFAULT_SETTINGS)
                # Ensure all default settings exist
                for k, v in self.DEFAULT_SETTINGS.items():
                    if k not in self.settings:
                        self.settings[k] = v
            except (json.JSONDecodeError, ValueError):
                cmds.warning(f"Resetting corrupted JSON file: {self.user_data_file}")
                self.save_user_data()
        else:
            # File doesn't exist, use defaults
            self.shelves = []
            self.window_data = self.DEFAULT_WINDOW.copy()
            self.settings = self.DEFAULT_SETTINGS.copy()

    def save_user_data(self):
        data = {
            "shelves": self.shelves,
            "window": self.window_data,
            "settings": self.settings
        }
        with open(self.user_data_file, 'w') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

    def parse_shelf_file(self, shelf_file_path):
        buttons = []
        if not os.path.exists(shelf_file_path):
            cmds.warning(f"Shelf file not found: {shelf_file_path}")
            return buttons

        with open(shelf_file_path, 'r') as f:
            lines = f.readlines()

        button_data = {}
        for line in lines:
            line = line.strip()
            if line.startswith("shelfButton"):
                if button_data:
                    buttons.append(button_data)
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

    def execute_command(self, command, source_type="mel"):
        if not isinstance(command, str) or not command.strip():
            cmds.warning("Invalid or empty command provided.")
            return
        try:
            # Decode for safety if needed, mirroring original logic
            try:
                command = command.encode('utf-8').decode('unicode_escape')
            except Exception:
                pass # Fallback if already decoded or issue

            if source_type == "python":
                print(f"Executing Python command:\n{command}")
                exec(command, globals())
            else:
                print(f"Executing MEL command:\n{command}")
                mel.eval(command)
        except Exception as e:
            cmds.warning(f"Failed to execute command: {command}. Error: {e}")

    def on_shelf_collapse(self, shelf_index, collapsed):
        if 0 <= shelf_index < len(self.shelves):
            self.shelves[shelf_index]["collapsed"] = collapsed
            self.save_user_data()
        self.resize_window()

    def on_settings_collapse(self, key, collapsed):
        self.settings[key] = collapsed
        self.save_user_data()
        self.resize_window()

    def resize_window(self):
        # Force window to recalculate size to fit children
        # setting height to 1 ensures it shrinks to minimum required height
        if cmds.window(self.WINDOW_NAME, exists=True):
            cmds.window(self.WINDOW_NAME, edit=True, height=1, resizeToFitChildren=True)

    def toggle_frame_labels(self, visible):
        # Callback from checkbox, visible is boolean
        self.settings["SHOW_FRAME_LABEL"] = visible
        
        # Update all shelves to match global setting
        for i, shelf in enumerate(self.shelves):
            shelf["label_visible"] = visible
            
        for frame in self.shelf_frames:
            if cmds.frameLayout(frame, exists=True):
                cmds.frameLayout(frame, edit=True, labelVisible=visible)
        
        # Save settings immediately
        self.save_user_data()
        
        # Also force resize as labels take up space
        self.resize_window()

    def toggle_single_shelf_label(self, shelf_index, visible):
        if 0 <= shelf_index < len(self.shelves):
            self.shelves[shelf_index]["label_visible"] = visible
            
            # If hiding label, force expand the shelf first so it's not lost
            if not visible:
                self.shelves[shelf_index]["collapsed"] = False
            
            self.save_user_data()
            
            # Update UI if exists
            if shelf_index < len(self.shelf_frames):
                frame = self.shelf_frames[shelf_index]
                if cmds.frameLayout(frame, exists=True):
                    if not visible:
                        cmds.frameLayout(frame, edit=True, collapse=False)
                    cmds.frameLayout(frame, edit=True, labelVisible=visible)
            
            self.resize_window()

    def add_current_shelf(self):
        shelf = cmds.shelfTabLayout("ShelfLayout", query=True, selectTab=True)
        shelf_file = os.path.join(cmds.internalVar(userShelfDir=True), f"shelf_{shelf}.mel")

        if not os.path.exists(shelf_file):
            cmds.warning(f"Shelf file not found: {shelf_file}")
            return

        self.load_user_data() # Refresh data
        # New shelf defaults to valid settings or global default?
        # Let's default to global setting
        global_vis = self.settings.get("SHOW_FRAME_LABEL", True)
        self.shelves.append({"name": shelf, "buttons": self.parse_shelf_file(shelf_file), "collapsed": False, "label_visible": global_vis})
        self.save_user_data()
        cmds.evalDeferred(lambda: self.show(reopen=True))

    def delete_button(self, shelf_idx, button_idx):
        if 0 <= shelf_idx < len(self.shelves):
            shelf = self.shelves[shelf_idx]
            if 0 <= button_idx < len(shelf["buttons"]):
                del shelf["buttons"][button_idx]
                self.save_user_data()
                cmds.evalDeferred(lambda: self.show(reopen=True))
                cmds.warning(f"Button deleted from shelf '{shelf['name']}'.")
            else:
                cmds.warning("Button index out of range.")
        else:
            cmds.warning("Shelf index out of range.")

    def confirm_and_delete_button(self, shelf_idx, button_idx):
        confirm = cmds.confirmDialog(
            title="Confirm Deletion",
            message="Are you sure you want to delete this button?",
            button=["Yes", "No"],
            defaultButton="No",
            cancelButton="No",
            dismissString="No"
        )
        if confirm == "Yes":
            self.delete_button(shelf_idx, button_idx)
        else:
            cmds.warning("Button deletion canceled.")

    def display_shelf_buttons(self, shelf_idx, parent_layout):
        shelf = self.shelves[shelf_idx]
        grid_layout = cmds.gridLayout(parent=parent_layout, cellWidthHeight=(40, 40), autoGrow=True, numberOfColumns=self.settings["COLUMN_COUNT"])

        for button_index, b in enumerate(shelf["buttons"]):
            label = b.get("imageOverlayLabel", "")
            icon = b.get("image", "commandButton.png")
            annotation = b.get("annotation", "")
            command = b.get("command", "")
            source_type = b.get("sourceType", "mel")
            double_click_command = b.get("doubleClickCommand", "")

            # Create button
            btn = cmds.iconTextButton(commandRepeatable=True,
                imageOverlayLabel=label, image1=icon, parent=grid_layout,
                annotation=annotation,
                command=lambda c=command, t=source_type: self.execute_command(c, t),
                doubleClickCommand=lambda c=double_click_command, t=source_type: self.execute_command(c, t)
            )

            # Context menu
            popup = cmds.popupMenu(parent=btn, button=3)

            for item in b.get("menuItems", []):
                item_label = item.get("label", "Unnamed")
                item_command = item.get("command", "")
                cmds.menuItem(
                    label=item_label, parent=popup,
                    command=lambda _, c=item_command, t=source_type: self.execute_command(c, t)
                )

            cmds.menuItem(divider=True, parent=popup)
            cmds.menuItem(
                label="Delete Button", parent=popup,
                command=lambda _, s_idx=shelf_idx, b_idx=button_index: self.confirm_and_delete_button(s_idx, b_idx)
            )

    def save_settings_ui(self, *args):
        self.settings["COLUMN_COUNT"] = cmds.intField(self.column_input, query=True, value=True)
        self.settings["SCREEN_HEIGHT"] = cmds.intField(self.screen_height_input, query=True, value=True)
        self.settings["CLOSE_ON_REPEAT_FLAG"] = cmds.checkBox(self.close_on_repeat_toggle, query=True, value=True)
        self.settings["SHOW_WINDOW_UNDER_CURSOR"] = cmds.checkBox(self.show_window_under_cursor_toggle, query=True, value=True)
        self.settings["SHOW_FRAME_LABEL"] = cmds.checkBox(self.show_frame_label_toggle, query=True, value=True)
        self.settings["TOOLBOX_WINDOW_STYLE"] = cmds.checkBox(self.toolbox_style_window_toggle, query=True, value=True)
        
        self.save_user_data()
        cmds.evalDeferred(lambda: self.show(reopen=True))

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
            # We save settings too effectively as we usually save everything together
            self.save_user_data()
            cmds.warning("All shelves have been deleted.")
            cmds.evalDeferred(lambda: self.show(reopen=True))
        else:
            cmds.warning("Deletion canceled.")

    def show(self, close_on_repeat=False, reopen=False):
        self.load_user_data() # Ensure fresh data
        
        if reopen:
            if cmds.window(self.WINDOW_NAME, exists=True):
                cmds.deleteUI(self.WINDOW_NAME, window=True)

        if close_on_repeat:
            if self.settings["CLOSE_ON_REPEAT_FLAG"]:
                if cmds.window(self.WINDOW_NAME, exists=True):
                    time.sleep(0.2)
                    cmds.evalDeferred(lambda: cmds.deleteUI(self.WINDOW_NAME, window=True))
                return
            else:
                return

        # If not close_on_repeat but flag is false, check logic from original:
        # if CLOSE_ON_REPEAT_FLAG == False: close window if exists?
        # Original: if CLOSE_ON_REPEAT_FLAG == False : if cmds.window(sp_shelf_window, exists=True): cmds.deleteUI...
        # Wait, the logic for toggle behavior:
        # If the user presses hotkey and CLOSE_ON_REPEAT is OFF, it toggles window visibility (Standard toggle).
        # If CLOSE_ON_REPEAT is ON, it shows on press, hides on release (handled by separate calls usually).
        # Assuming the caller uses `sp_shelf_ui()` for press and `sp_shelf_ui(close_on_repeat=True)` for release?
        # The original code had:
        # if close_on_repeat and CLOSE_ON_REPEAT_FLAG: ... return
        # if close_on_repeat: return (Implicit else)
        # if CLOSE_ON_REPEAT_FLAG == False: if window exists, delete it and return (Toggle behavior)
        
        if not close_on_repeat:
            if not self.settings["CLOSE_ON_REPEAT_FLAG"]:
                if cmds.window(self.WINDOW_NAME, exists=True):
                    cmds.deleteUI(self.WINDOW_NAME, window=True)
                    return

        # Ensure we do not use saved Maya preferences for this window
        if cmds.windowPref(self.WINDOW_NAME, exists=True):
            cmds.windowPref(self.WINDOW_NAME, remove=True)

        # Create Window
        if cmds.window(self.WINDOW_NAME, exists=True):
            # If it exists (e.g. hold mode), just show it
            cmds.showWindow(self.WINDOW_NAME)
        else:
            self.create_window()
            
    def create_window(self):
        # retain=False prevents Maya from keeping the window in memory/hidden state after close
        cmds.window(self.WINDOW_NAME, title="spShelf", sizeable=True, minimizeButton=False, maximizeButton=False,
                    height=self.window_data['height'], width=self.window_data['width'], 
                    toolbox=self.settings["TOOLBOX_WINDOW_STYLE"], retain=False)

        main_layout = cmds.columnLayout(adjustableColumn=True, parent=self.WINDOW_NAME)

        self.shelf_frames = []

        # Draw Shelves
        for i, shelf in enumerate(self.shelves):
            frame_lbl = shelf['name'] # Always set the label text, visibility controls display
            # Make sure labelVisible is correctly handled
            # Default to global setting if not present in individual
            global_vis = self.settings.get("SHOW_FRAME_LABEL", True)
            label_visible = shelf.get("label_visible", global_vis)
            
            is_collapsed = shelf.get("collapsed", False)
            
            shelf_frame = cmds.frameLayout(label=frame_lbl, collapsable=True, collapse=is_collapsed, 
                                           parent=main_layout, marginWidth=0, marginHeight=0, 
                                           labelVisible=label_visible,
                                           collapseCommand=lambda idx=i: self.on_shelf_collapse(idx, True),
                                           expandCommand=lambda idx=i: self.on_shelf_collapse(idx, False))
            
            # Popup menu for controlling label visibility
            popup = cmds.popupMenu(parent=shelf_frame)
            cmds.menuItem(label="Show/Hide Label", parent=popup, 
                          command=lambda _, idx=i: self.toggle_single_shelf_label(idx, not self.shelves[idx].get("label_visible", True)))

            self.shelf_frames.append(shelf_frame)
            self.display_shelf_buttons(i, shelf_frame)

        # Settings Frame
        # Default state handling for older json
        settings_collapsed = self.settings.get("SETTINGS_COLLAPSED", True)

        settings_frame = cmds.frameLayout(label="Settings", collapsable=True, collapse=settings_collapsed, 
                                          parent=main_layout, marginWidth=5, marginHeight=5,
                                          collapseCommand=lambda: self.on_settings_collapse("SETTINGS_COLLAPSED", True),
                                          expandCommand=lambda: self.on_settings_collapse("SETTINGS_COLLAPSED", False))
        # Note: collapse=True (default closed) or use a count logic? Original used `collapse=SHALVES_COUNT` which is weird (bool expected, or maybe it relied on non-zero int being true?)
        # Original: collapse=SHALVES_COUNT. If count is 0 (False), it's open. If >0 (True), it's closed.
        # So settings are hidden if shelves exist? Stick to that logic.
        # is_collapsed = (shelves_count > 0)
        # cmds.frameLayout(settings_frame, edit=True, collapse=is_collapsed)

        cmds.button(backgroundColor=(0, 0.5, 0.4), height=30, label="Add Current Shelf", 
                    command=lambda _: self.add_current_shelf(), parent=settings_frame)

        # Settings Fields
        settings_layout = cmds.rowLayout(numberOfColumns=2, adjustableColumn=2, columnAlign2=("left", "left"), parent=settings_frame)
        self.column_input = cmds.intField(width=40, value=self.settings["COLUMN_COUNT"], parent=settings_layout)
        cmds.text(label="Columns count", parent=settings_layout, align="left")

        settings_layout_2 = cmds.rowLayout(numberOfColumns=2, adjustableColumn=2, columnAlign2=("right", "left"), parent=settings_frame)
        self.screen_height_input = cmds.intField(width=40, value=self.settings["SCREEN_HEIGHT"], parent=settings_layout_2)
        cmds.text(label="Screen Height", parent=settings_layout_2, align="left")

        # Checkboxes
        toggle_layout = cmds.columnLayout(adjustableColumn=True, parent=settings_frame)
        self.close_on_repeat_toggle = cmds.checkBox(value=self.settings["CLOSE_ON_REPEAT_FLAG"], parent=toggle_layout, label="Close on Key Release")
        self.show_window_under_cursor_toggle = cmds.checkBox(value=self.settings["SHOW_WINDOW_UNDER_CURSOR"], parent=toggle_layout, label="Open under Cursor")
        
        self.show_frame_label_toggle = cmds.checkBox(value=self.settings["SHOW_FRAME_LABEL"], parent=toggle_layout, label="Show Frame Label",
                                                     changeCommand=lambda x: self.toggle_frame_labels(x))
                                                     
        self.toolbox_style_window_toggle = cmds.checkBox(value=self.settings["TOOLBOX_WINDOW_STYLE"], parent=toggle_layout, label="Compact Title Bar")

        # Save Button
        cmds.button(backgroundColor=(0.2, 0.6, 0.8), height=30, label="Save Settings",
                    command=self.save_settings_ui, parent=settings_frame)

        # Delete All Shelves
        delete_collapsed = self.settings.get("DELETE_COLLAPSED", True)
        
        delete_layout = cmds.frameLayout(label="Delete All Shelves", collapsable=True, collapse=delete_collapsed, parent=settings_frame,
                                         collapseCommand=lambda: self.on_settings_collapse("DELETE_COLLAPSED", True),
                                         expandCommand=lambda: self.on_settings_collapse("DELETE_COLLAPSED", False))
        cmds.button(backgroundColor=(0.8, 0.3, 0.3), height=20, label="Delete All Shelves",
                    command=lambda _: self.delete_all_shelves(), parent=delete_layout)

        # Force initial resize to respect collapsed states
        self.resize_window()

        # Positioning
        self.position_window()
        
        cmds.showWindow(self.WINDOW_NAME)

    def position_window(self):
        if not self.settings["SHOW_WINDOW_UNDER_CURSOR"] or QCursor is None:
            return

        x = QCursor.pos().x()
        y = QCursor.pos().y()

        # We need to show window first to get dimensions usually, or guess
        # Maya's showWindow is async-ish, but let's try querying
        # If window just created, might need evalDeferred for accurate size, or use stored size
        window_width = self.window_data['width']
        window_height = self.window_data['height']
        
        # Try to get actual size if valid
        if cmds.window(self.WINDOW_NAME, exists=True):
             # These queries might return 0 if not yet visible
             w = cmds.window(self.WINDOW_NAME, query=True, width=True)
             h = cmds.window(self.WINDOW_NAME, query=True, height=True)
             if w > 10: window_width = w
             if h > 10: window_height = h
        
        screen_height = self.settings["SCREEN_HEIGHT"]
        
        window_y = max(0, y - (window_height / 2))
        window_x = max(0, x - (window_width / 2))

        if window_y > (screen_height - window_height):
            window_y = screen_height - window_height
            
        cmds.window(self.WINDOW_NAME, edit=True, tlc=(int(window_y), int(window_x)))

# Global instance for backward compatibility and easy calls
_shelf_instance = SpShelf()

def sp_shelf_ui(close_on_repeat=False, reopen=False):
    """
    Main entry point for the script.
    """
    _shelf_instance.show(close_on_repeat=close_on_repeat, reopen=reopen)