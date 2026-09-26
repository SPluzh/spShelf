# Changelog

All notable changes to this project will be documented in this file.

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
