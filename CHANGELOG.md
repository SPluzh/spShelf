# Changelog

All notable changes to this project will be documented in this file.

## [2.3.0]
- **UI/UX**: Added a floating island button to toggle Maya's native shelves (`mel: ToggleShelf;`) positioned immediately to the left of the settings button:
    - Sized and styled identically to the settings island button (compact ~20px with DPI scaling, rounded geometry, smooth hover/pressed states).
    - Real-time synchronization with Maya's shelf visibility via `isUIComponentVisible("Shelf")`: displays Maya teal accent when shelves are visible, and dark gray when shelves are hidden.
    - Integrated multi-resolution shelf icon resolution (`shelfTab.png`, `shelf.png`, etc.) with a clean procedural high-DPI miniature shelf fallback.
    - Dynamic tooltip indicating current shelf state (`Toggle Maya Shelf: Visible/Hidden (mel: ToggleShelf;)`).

## [2.2.0]
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
