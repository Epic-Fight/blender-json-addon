***

# Epic Fight Animation & Model Exporter

A dedicated **Blender 2.79** exporter built specifically for **Epic Fight–based Minecraft development**.

This add-on enables exporting meshes, armatures, animations, and camera data into a structured JSON format compatible with Epic Fight workflows.

***

## 📦 Installation (Blender 2.79)

1. Download or clone the full source code.

2. Navigate to your Blender 2.79 installation directory.

3. Move the add-on folder to:

   ```
   /2.79/scripts/addons/<export-here>
   ```

4. Open Blender.

5. Go to **File → User Preferences → Add-ons**.

6. Search for:

   ```
   Import-Export: Minecraft Model Json Exporter
   ```

7. Enable the checkbox.

8. Click **Save User Settings**.

***

## ⚠️ Requirements & Limitations

This exporter is designed for a **very specific pipeline**.

Before exporting, ensure:

* Mesh is properly structured
* Armature is correctly configured
* Animations are fully created and validated

Before reporting issues, please make sure to seek other methods of support, 
be it by consulting the community or browsing our issue tracker.
Also ensure your data structure matches the expected workflow before reporting issues.
For more information on how to use this and use Blender for Epic Fight development, check our [wiki](https://epicfight-docs.readthedocs.io).

***

## 📝 Changelog

### 3.0.0

* Fixed `_ctypes / execstack` error completely
* Added detailed error warning messages
* Camera now always exports as `Attributes`
* Added Animation/Armature format selector

### 2.0.2

* Added **Export only visible bones** option

### 2.0.1

* Fixed camera animation export issue caused by quaternion ↔ matrix transformation

### 2.0.0

* Added camera export for POV animation
* Added animation formatting optimization
  *(Attribute format recommended over Matrix format)*

### 1.0.2

* Added mesh separation by vertex groups
  (Groups ending with `_mesh` are exported as distinct parts)

### 1.0.1

* Split "Export Model" into:

  * Export Mesh
  * Export Armature
* Hidden joints are no longer exported

### 1.0.0

* Initial release

***
