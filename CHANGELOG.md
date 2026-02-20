# 📝 Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 19-02-2026

### Added

- Unified multi-version support (2.79 – 5.0)

  - Single codebase supporting Blender 2.79 and 2.8+
  - No separate branches required
  - Fully feature-complete across all supported versions
  - Tested on Blender 2.79, 2.8, 3.6, 4.1, and 5.0

- `Optimize Keyframes` export option property

  - Removes redundant keyframes during export
  - Reduces file size
  - Compatible with Bake Animation

- `Bake Animation` export option property

  - Exports visual transforms per frame
  - Preserves smoothness from F-Curves
  - Compatible with Optimize Keyframes
  - Produces optimized animations for in-game use

- `Batch MC Animation` export option

  - Exports all available actions in the current project
  - Supports format selection, Optimize Keyframes, and Bake Animation
  - Optional Armature attachment
  - Option to export visible bones only

- Import: `Animated Minecraft Model (.json)`

  - Imports animations, armatures, meshes, and cameras
  - Automatically reconstructs skeletal meshes
  - Supports batch importing multiple `.json` files
  - Allows recovery and rebuilding of lost Blender projects
  - Improved animation reconstruction accuracy

- Auto-updater (experimental)

  - Checks for updates on Blender launch
  - Detects version discrepancies
  - Prompts user to download newer versions

### Changed

- Complete Blender addon architecture restructure

  - Unified previous 2.79 and 2.8+ branches into a single maintained system
  - Internal refactor for cleaner structure and long-term maintainability

- New `.json` export parameter: `FPS`

  - Stores workspace frame rate at export time
  - Enables precise animation reconstruction during import

### Fixed

- Fixed indentation in exported `Attribute` frame data

  - Reduces file size by approximately one third
  - Cleaner and more consistent JSON output

---
---
**All versions below are before the merge of the 2.79 exporter & the 2.8+ exporter. They each contain different changes**

## 2.8+ CHANGELOG


### [2.0.1]

* Exclude any deform bones, like IKs, from being exported.
* Added bone append logic
* Matrix correction

### [2.0.0]

* Ported 3.0.0 to Blender 2.8+
  * Fixed Several issues
  * Improved the exporter to work on versions above 3.6
  * Added support for camera export & 'Attributes' exporting format

### [1.0.3]

* Ported it to Blender 3.6 (Credits: [@box](https://github.com/box777555888))<br>  

### [1.0.2]

* Added mesh separation by vertex groups
  (Groups ending with `_mesh` are exported as distinct parts)

### [1.0.1]

* Split "Export Model" into:

  * Export Mesh
  * Export Armature
* Hidden joints are no longer exported

### [1.0.0]

* Initial release for Blender 2.8
<br><br><br><br>

## 2.79 CHANGELOG

### [3.0.0]

* Fixed `_ctypes / execstack` error completely
* Added detailed error warning messages
* Camera now always exports as `Attributes`
* Added Animation/Armature format selector

### [2.0.2]

* Added **Export only visible bones** option

### [2.0.1]

* Fixed camera animation export issue caused by quaternion ↔ matrix transformation

### [2.0.0]

* Added camera export for POV animation
* Added animation formatting optimization
  *(Attribute format recommended over Matrix format)*

### [1.0.2]

* Added mesh separation by vertex groups
  (Groups ending with `_mesh` are exported as distinct parts)

### [1.0.1]

* Split "Export Model" into:

  * Export Mesh
  * Export Armature
* Hidden joints are no longer exported

### [1.0.0]

* Initial release

*** 
