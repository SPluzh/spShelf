# Changelog

All notable changes to this project will be documented in this file.

## [2.1.8]
- **Button Styling / Attribute Preservation**: Added full extraction and rendering of custom button and label colors when adding buttons:
    - **Label Color**: Reads and applies `overlayLabelColor` (RGB) to the button's overlay text.
    - **Label Background & Transparency**: Reads `overlayLabelBackColor` (RGBA) and renders a styled rounded pill/box behind the overlay label with exact background color and alpha transparency.
    - **Button Background**: Detects if a custom button background is enabled (`enableBackground`) and extracts `backgroundColor` (RGB), rendering an interactive tinted background with hover and pressed states.
    - **MEL Shelf Parser & Drag-and-Drop**: Supports both drag-and-drop from native Maya shelves (`extract_maya_button_data`) and shelf file imports (`parse_shelf_file`).

## [2.1.7]
- **UX/Context Menu**: Added "Move Shelf Up" and "Move Shelf Down" actions to shelf context menus:
    - Easily reorder shelves directly from shelf headers, empty shelf background, or section frame context menus.
    - Dynamically disables options when a shelf is already at the very top or bottom.
    - Immediately updates the UI layout and saves the new order to JSON (`move_shelf`).
- **Settings/UI**: Increased maximum column count (buttons per row) from 20 to 30 in the Settings panel (`col_spin.setRange(1, 30)`).
- **Window Management/Fix**: Removed `WindowStaysOnTopHint` from `SpShelfWindow`:
    - Fixes Maya native confirmation dialogs (`cmds.confirmDialog`) appearing underneath the shelf window when deleting buttons, separators, or shelves.
    - Prevents the shelf window from staying on top of external applications when switching away from Maya.

## [2.1.6]
- **UX/Context Menu**: Added "Add Separator" action to shelf context menus:
    - **Shelf Header & Background**: Right-clicking shelf headers or empty shelf grid space provides an "Add Separator" option to append or insert separators at the cursor target position.
    - **Shelf Buttons & Separators**: Right-clicking shelf buttons or existing separators provides an "Add Separator" action to insert a new separator immediately after the selected item.
    - **Auto-Visibility & Expand**: Automatically activates "Show Separators" if disabled so new separators are immediately visible, and uncollapses the target shelf if collapsed.

## [2.1.5]
- **UX/Interactivity**: Implemented drag-and-drop support from Autodesk Maya's native shelves into `spShelf`:
    - **Native Shelf Drag Acceptance**: Dragging buttons with Middle Mouse Button (**MMB**) from any standard Maya shelf (Modeling, Curves, Animation, Custom, etc.) into `spShelf` seamlessly copies them into the target shelf.
    - **Full Attribute Extraction**: Automatically inspects and preserves all button properties: execution command, `sourceType` (MEL/Python), icon path/resource, overlay label, annotation tooltip, and double-click commands.
    - **Context Menu Support**: Recursively inspects and imports RMB popup menu items (`menuItems`) associated with the Maya shelf button.
    - **Script Editor Drag-to-Shelf**: Dragging selected Python or MEL code from Maya's Script Editor directly into `spShelf` automatically creates a new shelf button with auto-detected interpreter type.
    - **Safe Copy Mode**: Leaves original Maya shelf buttons untouched to prevent accidental modification of default Maya shelves.

## [2.1.4]
- **UX/Interactivity**: Implemented native Maya-style Middle Mouse Button (**MMB**) drag-and-drop reordering:
    - **Intra-shelf reordering**: Dragging buttons or separators within the same shelf dynamically rearranges their positions.
    - **Inter-shelf transfer**: Dragging items across different shelves transfers them seamlessly to the target shelf.
    - **Visual Drop Indicator**: Real-time high-contrast cyan glow insertion marker (`#00e5ff`) with rounded endpoints indicating the exact slot where the item will land.
    - **Ghost Preview**: Semi-transparent (70% opacity) button/separator snapshot under cursor during drag session (`QDrag`).
    - **Collapsed Shelf Drop & Auto-Expand**: Dropping directly onto a shelf header button appends the item to that shelf, while hovering over a collapsed header for 400ms automatically expands the shelf to allow precision placement.
    - **Data Persistence**: Immediate JSON persistence via `move_shelf_item()` and non-jumping scroll preservation across rebuilds.
    - **Version Compatibility**: Full cross-version compatibility supporting PySide2 (Maya 2020–2024) and PySide6 (Maya 2025+).

## [2.1.3]
- **UI/UX**: Added a floating island button to toggle Maya's native shelves (`mel: ToggleShelf;`) positioned immediately to the left of the settings button:
    - Sized and styled identically to the settings island button (compact ~20px with DPI scaling, rounded geometry, smooth hover/pressed states).
    - Real-time synchronization with Maya's shelf visibility via `isUIComponentVisible("Shelf")`: displays Maya teal accent when shelves are visible, and dark gray when shelves are hidden.
    - Integrated multi-resolution shelf icon resolution (`shelfTab.png`, `shelf.png`, etc.) with a clean procedural high-DPI miniature shelf fallback.
    - Dynamic tooltip indicating current shelf state (`Toggle Maya Shelf: Visible/Hidden (mel: ToggleShelf;)`).

## [2.1.2]
- **UI/UX**: Implemented the settings button as a true floating island overlay (HUD badge) positioned directly above the top shelf buttons:
    - Zero window height overhead: removed the separate window header bar, making the window as compact and clean as possible.
    - Sized to half of regular shelf buttons (~20px with DPI scaling) with rounded island geometry and smooth hover/pressed highlights.
    - Seamless alignment: when shelf labels are visible, it floats right inside the upper shelf header; when labels are hidden, it floats in the top-right corner directly over the buttons.
    - Active Maya teal accent indicator when the settings rollout is open.
    - Integrated multi-resolution High-DPI gear icons (`gear_14.png`, `gear_19.png`, `gear_24.png`, `gear_28.png`, `gear_38.png`) with automatic scale selection.
- **UI**: Cleaned up the window appearance by hiding the bottom Settings rollout when collapsed, eliminating bulky bottom bars and keeping the shelf view minimal and focused.
- **UX**: Toggling the floating settings button smoothly unfolds or closes the settings rollout panel with dynamic window height resizing and boundary clamping.
- **UX**: Added frameless window dragging support by clicking and dragging on empty window areas or shelf headers.

## [2.1.1]
- **Fix**: Fixed shelf buttons remaining in dark/pressed state after being clicked. Properly dispatched mouse release and double-click events to base Qt handler and ensured `isDown` state resets immediately.
- **UI**: Set shelf button default background to transparent (matching Maya's default shelf buttons) with clean hover and pressed state highlights.
- **Fix/DPI**: Fixed shelf button icons not scaling under DPI / UI Scale. Bypassed Maya's QStyle 32px raster clamping by implementing direct High-DPI QPixmap loading (supporting `_200`, `_150`, `@2x`) and smooth scaled painter rendering stretching across the full button.
- **UI**: Centered button overlay labels horizontally and reduced font size for cleaner presentation and better fit.
- **UI**: Fixed shelf button alignment. Buttons in a row are now strictly left-aligned at all times, preventing them from centering when rows are incomplete or when the window expands.
- **Fix**: Fixed "Show Frame Label" checkbox behavior. Toggling the checkbox now immediately and persistently hides or shows rollout/shelf headers, automatically uncollapses contents when hidden, and resizes the window dynamically.
- **UI**: Centered shelf separators in their grid cells (`AlignHCenter`) and within `SeparatorWidget` (`paintEvent`), rendering them in Maya's default gray (`#606060`) rather than dark sunken edges or sticking to the left edge of the column.
- **UX**: Enabled opening shelf context menu (Show/Hide Label, Delete Shelf) by right-clicking on empty shelf space even when header labels are hidden.
- **UI/Settings**: Added "Row spacing" setting (0–30 px, default 1 px) with DPI scaling, allowing custom vertical gap control between shelf rows and between shelves.

## [2.1.0]
- **DPI & System Scaling**: Added comprehensive High-DPI support:
    - Automatic detection of screen DPI, Qt `devicePixelRatio`, and Maya interface scaling (`cmds.mayaDpiSetting`).
    - Multi-monitor awareness (dynamically updates scale when opened on screens with different DPI).
    - Proportional scaling for buttons, icon sizes, text overlay, font sizes, margins, separators, and dialogs.
- **Settings**: Single unified UI Scale dropdown list with automatic scaling (`Auto`) or manual override (`75%`, `100%`, `125%`, `150%`, `175%`, `200%`, `250%`, `300%`).

## [2.0.0]
- **Architecture**: Full rewrite to native Qt (PySide2/PySide6) for instantaneous opening (0-2ms latency).
- **UI**: Elimination of Windows DWM open/close animations, multi-monitor auto-detection, cached UI singleton.
- **UX**: Added mouse-release cancellation (cancel on drag-off) for shelf buttons.

## [1.1.6]
- **UI/Settings**: Added "Hide Title Bar" checkbox to Settings for a clean, frameless window experience via Maya's `titleBar` flag.

## [1.1.5]
- **Fix**: Fixed shelf file search to correctly iterate all paths in `MAYA_SHELF_PATH` instead of relying on Maya's broken path concatenation.

## [1.1.4]
- **UI**: Comprehensive separator implementation:
    - Added support for standard and dotted styles.
    - Refined dotted style using a custom `cmds.text` fallback for legacy Maya compatibility.
    - Optimized width (8px) using `rowLayout`.
- **Settings**: New UI controls for separator visibility, orientation, and style.
- **UX**: Added deletion functionality to separators via a right-click context menu.
- **Fix**: Resolved indentation and rendering logic errors.

## [1.1.3]
- **UX**: Added right-click context menu to separators (both standard and dotted) for easy deletion.
- **UX**: Improved the deletion confirmation dialog to be more generic and descriptive.

## [1.1.2]
- **UI**: Optimized shelf separator width (reduced from 40px to 8px) by switching to `rowLayout` usage.

## [1.1.1]
- **Refactoring**: Converted `spShelf.py` to a class-based structure (`SpShelf`) to improve maintainability and remove global variables.
- **UI**: Added auto-resizing window behavior when collapsing/expanding shelves or settings.
- **UI**: Implemented "Show Frame Label" live toggle and per-shelf visibility via right-click menu.
- **UX**: Enforced shelf expansion when hiding its label to prevent access issues.
- **Persistence**: Added immediate saving of settings and persistence for shelf/panel collapse states.
- **Fix**: Resolved window resizing issues on startup and disabled window preference retention.
- **Fix**: Corrected typos ("Shalves" -> "Shelves") and improved error handling.
