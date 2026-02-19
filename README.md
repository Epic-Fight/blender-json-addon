***

# Epic Fight Animation & Model Exporter  

A dedicated **Blender 2.8+** exporter built specifically for **Epic Fight–based Minecraft development**.

This version of the exporter, supports **all versions above Blender 2.8**. 
The exporter itself was tested on the following versions:

* Blender (2.8) 🟩 Fully tested & working
* Blender (3.6) 🟩 Fully tested & working
* Blender (4.1) 🟩 Fully tested & working
* Blender (5.0) 🟩 Fully tested & working

This add-on enables exporting meshes, armatures, animations, and camera data into a structured JSON format compatible with Epic Fight workflows.

***

## 📦 Installation (Blender 2.8+)

1. Download or clone the full source code.

2. Navigate to your Blender installation directory.

3. Move the add-on folder to:

   ```
   /<blender-version>/scripts/addons/<export-here>
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

## 👥 Credits
[@box](https://github.com/box777555888) - Blender 3.6 exporter
