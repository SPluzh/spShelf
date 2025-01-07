# spShelf - Floating Shelf Window for Maya

A simple script that, when the hotkey is pressed, creates a floating window of 1 or more Maya shelves directly under your cursor. The window hides when the hotkey is released.


https://github.com/user-attachments/assets/9d5e4220-8c22-43bc-8bd7-bdd7737511a2


## Requirements

- Maya 2020 or higher
- Python 3

## Installation

1. Copy `spShelf.py` to your Maya scripts folder (for example: `%USERPROFILE%\Documents\maya\2025\scripts`).
2. Once installed, you can assign hotkeys for the following actions:

   - **Press**: To show the floating shelves, use the following command in your hotkey editor:
     ```python
     from spShelf import sp_shelf_ui
     sp_shelf_ui(close_on_repeat=False)
     ```

   - **Release**: To hide the floating shelves, use the following command in your hotkey editor:
     ```python
     from spShelf import sp_shelf_ui
     sp_shelf_ui(close_on_repeat=True)
     ```

https://github.com/user-attachments/assets/9b196080-0b7c-4695-a98f-417f859a86ff
     

## Usage

After setting the hotkeys, pressing the assigned hotkey will display the shelves, and releasing it will hide them.

## Features

- Floating shelf window that appears under your cursor.
- Supports multiple shelves.
- Customizable settings for number of columns, window height, and more.
- Option to close the window when the hotkey is released.
