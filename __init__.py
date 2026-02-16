bl_info = {
    "name": "Minecraft Model Json Exporter",
    "author": "Yesssssman",
    "blender": (2, 80, 0),
    "category": "Import-Export",
    "location": "File > Import-Export",
    "description": "Specially designed exporter for developing Minecraft Epic Fight Mod"
}

import bpy
from bpy.props import *
from bpy_extras.io_utils import ExportHelper


class ExportToJson(bpy.types.Operator, ExportHelper):
    """Export to Json that specially designed for Epic Fight"""
    bl_idname = "export_mc.json"
    bl_label = "Export to Json for Minecraft"
    filename_ext = ".json"
    filter_glob = StringProperty(default="*.json", options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        return context.active_object is not None

    # export toggles (ordered top to bottom in the panel)

    export_mesh = BoolProperty(
        name="Export Mesh",
        description="Export mesh data",
        default=True
    )

    apply_modifiers = BoolProperty(
        name="Apply Modifiers",
        description="Apply modifiers before exporting. "
                    "Make sure the armature is in rest pose if enabled",
        default=False
    )

    export_armature = BoolProperty(
        name="Export Armature",
        description="Export armature data",
        default=True
    )

    transform_formats = [
        ('MAT', 'Matrix', "Export transform as matrix"),
        ('ATTR', 'Attributes', "Export transform as loc, rot, scale attributes")
    ]

    armature_format = EnumProperty(
        name="Armature Format",
        description="Armature transform export format",
        default='ATTR',
        items=transform_formats
    )

    export_anim = BoolProperty(
        name="Export Animation",
        description="Export animation data",
        default=True
    )

    animation_format = EnumProperty(
        name="Animation Format",
        description="Animation transform export format",
        default='ATTR',
        items=transform_formats
    )

    export_camera = BoolProperty(
        name="Export Camera",
        description="Export camera transform (always exported as Attributes)",
        default=False
    )

    export_only_visible_bones = BoolProperty(
        name="Export Only Visible Bones",
        description="Export bones that are visible. Warning: child bones of hidden bones won't export either",
        default=False
    )

    # custom draw so controls appear in the right order

    def draw(self, context):
        layout = self.layout

        layout.prop(self, "export_mesh")
        if self.export_mesh:
            box = layout.box()
            box.prop(self, "apply_modifiers")

        layout.separator()
        layout.prop(self, "export_armature")
        if self.export_armature:
            box = layout.box()
            box.prop(self, "armature_format")

        layout.separator()
        layout.prop(self, "export_anim")
        if self.export_anim:
            box = layout.box()
            box.prop(self, "animation_format")

        layout.separator()
        layout.prop(self, "export_camera")
        if self.export_camera:
            box = layout.box()
            box.label("Camera is always exported as Attributes", icon='INFO')

        layout.separator()
        layout.prop(self, "export_only_visible_bones")


    def execute(self, context):
        if not self.filepath:
            self.report({'ERROR'}, "Filepath not set.")
            return {'CANCELLED'}

        keywords = self.as_keywords()

        from . import export_mc_json
        return export_mc_json.save(self, context, **keywords)


def menu_func(self, context):
    self.layout.operator(ExportToJson.bl_idname, text="Animated Minecraft Model (.json)")


def register():
    bpy.utils.register_module(__name__)
    bpy.types.INFO_MT_file_export.append(menu_func)


def unregister():
    bpy.utils.unregister_module(__name__)
    bpy.types.INFO_MT_file_export.remove(menu_func)


if __name__ == "__main__":
    register()