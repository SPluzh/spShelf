import maya.cmds as cmds
import maya.mel as mel
import os
import json
try:
    from PySide6.QtGui import QCursor
except ImportError:
    from PySide2.QtGui import QCursor

USER_DATA_FILE = os.path.join(cmds.internalVar(userAppDir=True), cmds.about(version=True), 'scripts', 'sp_shelf_data.json')

sp_shelf_window = "sp_shelf_window_main"

DEFAULT_WINDOW = {"width": 200, "height": 200}
DEFAULT_SETTINGS = {"COLUMN_COUNT": 4, "SCREEN_HEIGHT": 1600, "CLOSE_ON_REPEAT_FLAG": False, "SHOW_WINDOW_UNDER_CURSOR": True, "SHOW_FRAME_LABEL": True, "TOOLBOX_WINDOW_STYLE": False}

def load_user_data():
    global CLOSE_ON_REPEAT_FLAG
    if os.path.exists(USER_DATA_FILE):
        try:
            with open(USER_DATA_FILE, 'r') as f:
                data = json.load(f)
            #CLOSE_ON_REPEAT_FLAG = data.get("settings", {}).get("CLOSE_ON_REPEAT_FLAG", False)
            return (data.get("shelves", []),
                    data.get("window", DEFAULT_WINDOW),
                    data.get("settings", DEFAULT_SETTINGS))
        except (json.JSONDecodeError, ValueError):
            cmds.warning(f"Resetting corrupted JSON file: {USER_DATA_FILE}")
            save_user_data([], DEFAULT_WINDOW, DEFAULT_SETTINGS)
    return [], DEFAULT_WINDOW, DEFAULT_SETTINGS

def save_user_data(shelves, window_data, settings):
    global CLOSE_ON_REPEAT_FLAG
    settings["CLOSE_ON_REPEAT_FLAG"] = CLOSE_ON_REPEAT_FLAG
    with open(USER_DATA_FILE, 'w') as f:
        json.dump({"shelves": shelves, "window": window_data, "settings": settings}, f, indent=4, ensure_ascii=False)

def parse_shelf_file(shelf_file_path):
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

def execute_command(command, source_type="mel"):
    if not isinstance(command, str) or not command.strip():
        cmds.warning("Invalid or empty command provided.")
        return
    try:
        command = command.encode('utf-8').decode('unicode_escape')
        if source_type == "python":
            print(f"Executing Python command:\n{command}")
            exec(command, globals())
        else:
            print(f"Executing MEL command:\n{command}")
            mel.eval(command)
    except Exception as e:
        cmds.warning(f"Failed to execute command: {command}. Error: {e}")

def add_current_shelf():
    shelf = cmds.shelfTabLayout("ShelfLayout", query=True, selectTab=True)
    shelf_file = os.path.join(cmds.internalVar(userShelfDir=True), f"shelf_{shelf}.mel")

    if not os.path.exists(shelf_file):
        cmds.warning(f"Shelf file not found: {shelf_file}")
        return

    shelves, window_data, settings = load_user_data()
    shelves.append({"name": shelf, "buttons": parse_shelf_file(shelf_file)})
    save_user_data(shelves, window_data, settings)
    cmds.evalDeferred(lambda: sp_shelf_ui(reopen=True))
    #cmds.confirmDialog(title="Shelf Added", message=f"Shelf '{shelf}' added to JSON.", button=["OK"])

def display_shelf_buttons(shelf, parent_layout):
    global COLUMN_COUNT
    grid_layout = cmds.gridLayout(parent=parent_layout, cellWidthHeight=(40, 40), autoGrow=True)

    for button_index, b in enumerate(shelf["buttons"]):
        label = b.get("imageOverlayLabel", "")
        icon = b.get("image", "commandButton.png")
        annotation = b.get("annotation", "")
        command = b.get("command", "")
        source_type = b.get("sourceType", "mel")
        double_click_command = b.get("doubleClickCommand", "")

        # Создание кнопки
        btn = cmds.iconTextButton(commandRepeatable=True,
            imageOverlayLabel=label, image1=icon, parent=grid_layout,
            annotation=annotation,
            command=lambda c=command, t=source_type: execute_command(c, t),
            doubleClickCommand=lambda c=double_click_command, t=source_type: execute_command(c, t)
        )

        # Контекстное меню для кнопки
        popup = cmds.popupMenu(parent=btn, button=3)

        # Добавление пунктов меню для пользовательских команд
        for item in b.get("menuItems", []):
            item_label = item.get("label", "Unnamed")
            item_command = item.get("command", "")
            cmds.menuItem(
                label=item_label, parent=popup,
                command=lambda _, c=item_command, t=source_type: execute_command(c, t)
            )

        # Добавление разделителя
        cmds.menuItem(divider=True, parent=popup)

        # Пункт "Delete Button"
        cmds.menuItem(
            label="Delete Button", parent=popup,
            command=lambda _, i=button_index: confirm_and_delete_button(shelf, i, grid_layout)
        )

    # Функция для обновления колонок
    def update_columns():
        if cmds.window(sp_shelf_window, exists=True):
            cmds.gridLayout(grid_layout, edit=True, numberOfColumns=COLUMN_COUNT)

    update_columns()

def confirm_and_delete_button(shelf, button_index, grid_layout):
    """
    Запрашивает подтверждение и удаляет кнопку с интерфейса и из данных JSON.
    """
    confirm = cmds.confirmDialog(
        title="Confirm Deletion",
        message="Are you sure you want to delete this button?",
        button=["Yes", "No"],
        defaultButton="No",
        cancelButton="No",
        dismissString="No"
    )

    if confirm == "Yes":
        delete_button(shelf, button_index, grid_layout)
    else:
        cmds.warning("Button deletion canceled.")

def delete_button(shelf, button_index, grid_layout):
    """
    Удаляет кнопку с интерфейса и из данных JSON.
    """
    global USER_DATA_FILE

    # Удаление кнопки из данных
    if 0 <= button_index < len(shelf["buttons"]):
        del shelf["buttons"][button_index]

        # Загрузка данных из JSON
        shelves, window_data, settings = load_user_data()

        # Обновление данных для соответствующей полки
        for s in shelves:
            if s["name"] == shelf["name"]:
                s["buttons"] = shelf["buttons"]
                break

        # Сохранение данных обратно в JSON
        save_user_data(shelves, window_data, settings)

        # Перерисовка интерфейса
        cmds.evalDeferred(lambda: sp_shelf_ui(reopen=True))
        #cmds.deleteUI(grid_layout, layout=True)
        #display_shelf_buttons(shelf, parent_layout=cmds.columnLayout(parent=grid_layout))

        cmds.warning(f"Button deleted from shelf '{shelf['name']}' and JSON.")
    else:
        cmds.warning("Button index out of range.")

def sp_shelf_ui(close_on_repeat=False, reopen=False):           
    global sp_shelf_window, COLUMN_COUNT, SCREEN_HEIGHT, CLOSE_ON_REPEAT_FLAG, SHOW_FRAME_LABEL
    shelves, window_data, settings = load_user_data()
    SHALVES_COUNT = len(shelves)
    COLUMN_COUNT = settings.get("COLUMN_COUNT", 4)
    SCREEN_HEIGHT = settings.get("SCREEN_HEIGHT", 1600)
    CLOSE_ON_REPEAT_FLAG = settings.get("CLOSE_ON_REPEAT_FLAG", False)
    SHOW_WINDOW_UNDER_CURSOR = settings.get("SHOW_WINDOW_UNDER_CURSOR", True)
    SHOW_FRAME_LABEL = settings.get("SHOW_FRAME_LABEL", True)
    TOOLBOX_WINDOW_STYLE = settings.get("TOOLBOX_WINDOW_STYLE", True)

    if reopen:
        if cmds.window(sp_shelf_window, exists=True):
            cmds.deleteUI(sp_shelf_window, window=True)
        
    if close_on_repeat and CLOSE_ON_REPEAT_FLAG:
        if cmds.window(sp_shelf_window, exists=True):
            #save_window_and_settings(shelves, sp_shelf_window, COLUMN_COUNT, SCREEN_HEIGHT, CLOSE_ON_REPEAT_FLAG, SHOW_WINDOW_UNDER_CURSOR, SHOW_FRAME_LABEL)
            cmds.deleteUI(sp_shelf_window, window=True)
            return
        else:
            return
            
    if close_on_repeat :
        return
        
    if CLOSE_ON_REPEAT_FLAG == False :
        if cmds.window(sp_shelf_window, exists=True):
            #save_window_and_settings(shelves, sp_shelf_window, COLUMN_COUNT, SCREEN_HEIGHT, CLOSE_ON_REPEAT_FLAG, SHOW_WINDOW_UNDER_CURSOR, SHOW_FRAME_LABEL)
            cmds.deleteUI(sp_shelf_window, window=True)
            return


    sp_shelf_window = cmds.window(sp_shelf_window, title="spShelf", sizeable=True, minimizeButton=False, maximizeButton=False,
                                 height=window_data['height'], width=window_data['width'], toolbox=TOOLBOX_WINDOW_STYLE)

    main_layout = cmds.columnLayout(adjustableColumn=True, parent=sp_shelf_window)
    
    if SHOW_FRAME_LABEL:
        for shelf in shelves:
            display_shelf_buttons(shelf, parent_layout=cmds.frameLayout(label=f"{shelf['name']}", collapsable=True, collapse=False, parent=main_layout, marginWidth=0, marginHeight=0))
    else:
        for shelf in shelves:
            display_shelf_buttons(shelf, parent_layout=cmds.frameLayout(label=f"{shelf['name']}", collapsable=True, collapse=False, parent=main_layout, labelVisible=False))
 
    settingsFrame = cmds.frameLayout(label=f"Settings", collapsable=True, collapse=SHALVES_COUNT, parent=main_layout, marginWidth=5, marginHeight=5)

    cmds.button(backgroundColor=(0, 0.5, 0.4), height=30, label="Add Current Shelf", 
                command=lambda _: add_current_shelf(), parent=settingsFrame)          
    
    # Fields for settings

    settings_layout = cmds.rowLayout(numberOfColumns=2, adjustableColumn=2, columnAlign2=("left", "left"), parent=settingsFrame)
    
    
    column_input = cmds.intField(width=40, value=COLUMN_COUNT, parent=settings_layout)
    cmds.text(label="Columns count", parent=settings_layout, align="left")

    settings_layout_2 = cmds.rowLayout(numberOfColumns=2, adjustableColumn=2, columnAlign2=("right", "left"), parent=settingsFrame)
    screen_height_input = cmds.intField(width=40, value=SCREEN_HEIGHT, parent=settings_layout_2)
    cmds.text(label="Screen Height", parent=settings_layout_2, align="left")
    

    #  checkBox
    toggle_layout = cmds.columnLayout(adjustableColumn=True, parent=settingsFrame)
    close_on_repeat_toggle = cmds.checkBox(value=CLOSE_ON_REPEAT_FLAG, parent=toggle_layout, label="Close on Key Release")
    show_window_under_cursor_toggle = cmds.checkBox(value=SHOW_WINDOW_UNDER_CURSOR, parent=toggle_layout, label="Open under Cursor")  
    show_frame_label_toggle = cmds.checkBox(value=SHOW_FRAME_LABEL, parent=toggle_layout, label="Show Frame Label")      
    toolbox_style_window_toggle = cmds.checkBox(value=TOOLBOX_WINDOW_STYLE, parent=toggle_layout, label="Compact Title Bar") 
    
    # Save button
    cmds.button(backgroundColor=(0.2, 0.6, 0.8), height=30, label="Save Settings",
                command=lambda _: save_settings(column_input, screen_height_input, close_on_repeat_toggle, show_window_under_cursor_toggle, show_frame_label_toggle, toolbox_style_window_toggle),
                parent=settingsFrame)      
    
    delete_button_layout = cmds.frameLayout(label=f"Delete All Shalves", collapsable=True, collapse=True, parent=settingsFrame)
    def delete_all_shelves():
        # Open a confirmation dialog
        confirm = cmds.confirmDialog(
            title="Confirm Deletion",
            message="Are you sure you want to delete all shelves?",
            button=["Yes", "No"],
            defaultButton="No",
            cancelButton="No",
            dismissString="No"
        )
        
        # Check the user's response
        if confirm == "Yes":
            save_user_data([], DEFAULT_WINDOW, DEFAULT_SETTINGS)
            save_settings(column_input, screen_height_input, close_on_repeat_toggle, show_window_under_cursor_toggle, show_frame_label_toggle, toolbox_style_window_toggle)
            #save_window_and_settings([], sp_shelf_window, COLUMN_COUNT, SCREEN_HEIGHT, CLOSE_ON_REPEAT_FLAG, SHOW_WINDOW_UNDER_CURSOR, SHOW_FRAME_LABEL, TOOLBOX_WINDOW_STYLE)
            cmds.warning("All shelves have been deleted.")
            #cmds.confirmDialog(title="All Sheves Deleted", message=f"All Sheves Deleted from JSON.", button=["OK"])
            cmds.evalDeferred(lambda: sp_shelf_ui(reopen=True))
        else:
            cmds.warning("Deletion canceled.")
    
    # Button with the delete_all_shelves function
    cmds.button(
        backgroundColor=(0.8, 0.3, 0.3),
        height=20,
        label="Delete All Shelves",
        command=lambda _: delete_all_shelves(),
        parent=delete_button_layout
    )


    x = QCursor.pos().x()
    y = QCursor.pos().y()
    cmds.showWindow(sp_shelf_window)

    windowWidth = cmds.window(sp_shelf_window, query=True, width=True)
    windowHeight = cmds.window(sp_shelf_window, query=True, height=True)
    
    
    windowY = max(0, y - (windowHeight / 2))
    windowX = max(0, x - (windowWidth / 2))

    if (windowY) > (SCREEN_HEIGHT - windowHeight):
        windowY = SCREEN_HEIGHT - windowHeight
    
    if SHOW_WINDOW_UNDER_CURSOR:
        cmds.window(sp_shelf_window, e=True, tlc=(windowY, windowX))

    #cmds.scriptJob(runOnce=True, uiDeleted=(sp_shelf_window, lambda: save_window_and_settings(shelves, sp_shelf_window, COLUMN_COUNT, SCREEN_HEIGHT, CLOSE_ON_REPEAT_FLAG, SHOW_WINDOW_UNDER_CURSOR, SHOW_FRAME_LABEL)))

def save_settings(column_input, screen_height_input, close_on_repeat_toggle, show_window_under_cursor_toggle, show_frame_label_toggle, toolbox_style_window_toggle):
    """Save the settings for COLUMN_COUNT, SCREEN_HEIGHT, and CLOSE_ON_REPEAT_FLAG."""
    global COLUMN_COUNT, SCREEN_HEIGHT, CLOSE_ON_REPEAT_FLAG, CLOSE_ON_REPEAT_FLAG, SHOW_WINDOW_UNDER_CURSOR, SHOW_FRAME_LABEL, TOOLBOX_WINDOW_STYLE

    # Get values from input fields
    COLUMN_COUNT = cmds.intField(column_input, query=True, value=True)
    SCREEN_HEIGHT = cmds.intField(screen_height_input, query=True, value=True)
    CLOSE_ON_REPEAT_FLAG = cmds.checkBox(close_on_repeat_toggle, query=True, value=True)
    SHOW_WINDOW_UNDER_CURSOR = cmds.checkBox(show_window_under_cursor_toggle, query=True, value=True)
    SHOW_FRAME_LABEL = cmds.checkBox(show_frame_label_toggle, query=True, value=True)
    TOOLBOX_WINDOW_STYLE = cmds.checkBox(toolbox_style_window_toggle, query=True, value=True)

    # Update JSON file
    shelves, window_data, _ = load_user_data()
    save_user_data(shelves, window_data, {"COLUMN_COUNT": COLUMN_COUNT, "SCREEN_HEIGHT": SCREEN_HEIGHT, "CLOSE_ON_REPEAT_FLAG": CLOSE_ON_REPEAT_FLAG, "SHOW_WINDOW_UNDER_CURSOR": SHOW_WINDOW_UNDER_CURSOR, "SHOW_FRAME_LABEL": SHOW_FRAME_LABEL, "TOOLBOX_WINDOW_STYLE": TOOLBOX_WINDOW_STYLE})

    #cmds.confirmDialog(title="Settings Saved", message="Settings have been updated.", button=["OK"])
    cmds.evalDeferred(lambda: sp_shelf_ui(reopen=True))