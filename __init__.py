bl_info = {
    "name": "Epic Fight JSON",
    "author": "Yesssssman, box, Guivnf",
    "version": (1, 0, 0),
    "blender": (2, 80, 0),
    "category": "Import-Export",
    "location": "File > Import-Export",
    "description": "Epic Fight JSON Exporter & Importer",
}

import os
import traceback

import bpy
from bpy.props import (StringProperty, BoolProperty, EnumProperty,
                        CollectionProperty)
from bpy_extras.io_utils import ExportHelper, ImportHelper

IS_LEGACY = bpy.app.version < (2, 80, 0)

_ADDON_MODULE = __name__

try:
    _ADDON_DIR = os.path.dirname(os.path.abspath(__file__))
except Exception:
    _ADDON_DIR = ''


def _compat_props(cls, prop_names):
    """Move class-level properties into __annotations__ for 2.80+."""
    if IS_LEGACY:
        return
    ann = cls.__dict__.get('__annotations__', {})
    for name in prop_names:
        val = cls.__dict__.get(name)
        if val is not None:
            ann[name] = val
            try:
                delattr(cls, name)
            except (AttributeError, TypeError):
                pass
    cls.__annotations__ = ann


_TRANSFORM_FMTS = [
    ("MAT",  "Matrix",
     "Export transform as matrix"),
    ("ATTR", "Attributes",
     "Export transform as loc, rot, scale attributes"),
]


class ExportToJson(bpy.types.Operator, ExportHelper):
    """Export to Json specially designed for Epic Fight"""
    bl_idname = "export_mc.json"
    bl_label = "Export to Json for Minecraft"
    filename_ext = ".json"

    filter_glob = StringProperty(
        default="*.json", options={"HIDDEN"})
    export_mesh = BoolProperty(
        name="Export Mesh", default=True)
    apply_modifiers = BoolProperty(
        name="Apply Modifiers",
        description=("Apply modifiers before exporting. "
                     "Make sure the armature is in rest pose if enabled"),
        default=False)
    export_armature = BoolProperty(
        name="Export Armature", default=True)
    armature_format = EnumProperty(
        name="Armature Format", default="MAT",
        items=_TRANSFORM_FMTS)
    export_anim = BoolProperty(
        name="Export Animation", default=True)
    animation_format = EnumProperty(
        name="Animation Format", default="ATTR",
        items=_TRANSFORM_FMTS)
    optimize_keyframes = BoolProperty(
        name="Optimize Keyframes",
        description=("Remove redundant middle keyframes when "
                     "consecutive frames have identical transforms"),
        default=False)
    bake_animation = BoolProperty(
        name="Bake Animation",
        description=("Sample every frame instead of only keyframed "
                     "frames. Use this to capture the final visual "
                     "pose when constraints affect bone transforms "
                     "but aren't baked into keyframes"),
        default=False)
    export_camera = BoolProperty(
        name="Export Camera",
        description="Export camera transform (always Attributes)",
        default=False)
    export_only_visible_bones = BoolProperty(
        name="Export Only Visible Bones", default=False)

    @classmethod
    def poll(cls, context):
        return context.active_object is not None

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "export_mesh")
        if self.export_mesh:
            layout.box().prop(self, "apply_modifiers")
        layout.separator()
        layout.prop(self, "export_armature")
        if self.export_armature:
            layout.box().prop(self, "armature_format")
        layout.separator()
        layout.prop(self, "export_anim")
        if self.export_anim:
            box = layout.box()
            box.prop(self, "animation_format")
            box.prop(self, "optimize_keyframes")
            box.prop(self, "bake_animation")
        layout.separator()
        layout.prop(self, "export_camera")
        if self.export_camera:
            layout.box().label(
                text="Camera is always exported as Attributes",
                icon='INFO')
        layout.separator()
        layout.prop(self, "export_only_visible_bones")

    def execute(self, context):
        if not self.filepath:
            self.report({'ERROR'}, "Filepath not set.")
            return {'CANCELLED'}
        from . import export_mc_json
        return export_mc_json.save(self, context, **self.as_keywords())


_compat_props(ExportToJson, [
    'filter_glob', 'export_mesh', 'apply_modifiers', 'export_armature',
    'armature_format', 'export_anim', 'animation_format',
    'optimize_keyframes', 'bake_animation', 'export_camera',
    'export_only_visible_bones',
])


class BatchExportAnimations(bpy.types.Operator, ExportHelper):
    """Export every action as a separate animation JSON file"""
    bl_idname = "export_mc.batch_anim_json"
    bl_label = "Batch Export All Animations"
    filename_ext = ".json"

    filter_glob = StringProperty(
        default="*.json", options={"HIDDEN"})
    export_armature = BoolProperty(
        name="Include Armature", default=True)
    armature_format = EnumProperty(
        name="Armature Format", default="MAT",
        items=_TRANSFORM_FMTS)
    animation_format = EnumProperty(
        name="Animation Format", default="ATTR",
        items=_TRANSFORM_FMTS)
    optimize_keyframes = BoolProperty(
        name="Optimize Keyframes", default=False)
    bake_animation = BoolProperty(
        name="Bake Animation", default=False)
    export_only_visible_bones = BoolProperty(
        name="Export Only Visible Bones", default=False)

    @classmethod
    def poll(cls, context):
        return (any(o.type == 'ARMATURE' for o in context.scene.objects)
                and len(bpy.data.actions) > 0)

    def draw(self, context):
        layout = self.layout
        box = layout.box()
        box.label(text="Each action saves as 'action_name.json'",
                  icon='INFO')
        layout.separator()
        layout.prop(self, "export_armature")
        if self.export_armature:
            layout.box().prop(self, "armature_format")
        layout.separator()
        layout.prop(self, "animation_format")
        layout.prop(self, "optimize_keyframes")
        layout.prop(self, "bake_animation")
        layout.separator()
        layout.prop(self, "export_only_visible_bones")

    def execute(self, context):
        from . import compat
        export_dir = os.path.dirname(self.filepath)
        if not export_dir or not os.path.isdir(export_dir):
            self.report({'ERROR'}, "Invalid export directory.")
            return {'CANCELLED'}
        return compat.save_animation_batch(
            self, context, export_dir,
            animation_format=self.animation_format,
            armature_format=self.armature_format,
            optimize_keyframes=self.optimize_keyframes,
            bake_animation=self.bake_animation,
            export_armature=self.export_armature,
            export_only_visible_bones=self.export_only_visible_bones)


_compat_props(BatchExportAnimations, [
    'filter_glob', 'export_armature', 'armature_format',
    'animation_format', 'optimize_keyframes', 'bake_animation',
    'export_only_visible_bones',
])


class ImportFromJson(bpy.types.Operator, ImportHelper):
    """Import Epic Fight JSON files — select multiple to batch-import"""
    bl_idname = "import_mc.json"
    bl_label = "Import Epic Fight Json"
    filename_ext = ".json"

    filter_glob = StringProperty(
        default="*.json", options={"HIDDEN"})
    files = CollectionProperty(
        type=bpy.types.OperatorFileListElement,
        options={"HIDDEN", "SKIP_SAVE"})
    directory = StringProperty(
        subtype='DIR_PATH', options={"HIDDEN"})

    def execute(self, context):
        from . import import_mc_json
        paths = []
        if self.files:
            for f in self.files:
                if f.name:
                    paths.append(
                        os.path.join(self.directory, f.name))
        if not paths:
            if not self.filepath:
                self.report({'ERROR'}, "No files selected.")
                return {'CANCELLED'}
            paths = [self.filepath]
        if len(paths) == 1:
            return import_mc_json.load(
                self, context, filepath=paths[0])
        succeeded = 0
        failed = 0
        for filepath in paths:
            r = import_mc_json.load(self, context, filepath=filepath)
            if 'FINISHED' in r:
                succeeded += 1
            else:
                failed += 1
        if succeeded == 0:
            self.report({'ERROR'},
                        "All %d file(s) failed." % len(paths))
            return {'CANCELLED'}
        msg = "Batch import: %d succeeded" % succeeded
        if failed > 0:
            msg += ", %d failed" % failed
        self.report({'INFO'}, msg)
        return {'FINISHED'}


_compat_props(ImportFromJson, [
    'filter_glob', 'files', 'directory',
])


# updater state

_update_state = {
    'checked': False,
    'update_available': False,
    'latest_tag': '',
    'release_name': '',
    'release_notes': '',
    'download_url': '',
    'error': '',
    'installed': False,
    'install_msg': '',
    'popup_shown': False,
    'pending_popup': False,
    'manually_checked': False,
}

_MAX_POPUP_LINES = 12
_CHANGELOG_SCALE_Y = 0.7

_load_post_count = [0]
_splash_dismissed = [False]
_popup_attempts = [0]
_wait_ticks = [0]
_showing_popup = [False]


def _get_popup_metrics():
    try:
        windows = bpy.context.window_manager.windows
        if windows:
            win_width = windows[0].width
        else:
            win_width = 1920
    except Exception:
        win_width = 1920

    dialog_width = int(win_width * 0.35)
    dialog_width = max(350, min(dialog_width, 700))
    max_chars = max(30, int((dialog_width - 50) / 7))

    return dialog_width, max_chars


def _store_check_result(result):
    _update_state['checked'] = True
    _update_state['update_available'] = result.get(
        'update_available', False)
    _update_state['latest_tag'] = result.get(
        'latest_tag', '') or ''
    _update_state['release_name'] = result.get(
        'release_name', '') or ''
    _update_state['release_notes'] = result.get(
        'release_notes', '') or ''
    _update_state['download_url'] = result.get(
        'download_url', '') or ''
    _update_state['error'] = result.get('error', '') or ''


def _get_changelog_lines():
    notes = _update_state.get('release_notes', '')
    if not notes:
        return []
    lines = notes.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def _wrap_line(text, max_chars):
    text = text.rstrip()
    if not text or len(text) <= max_chars:
        return [text]
    lines = []
    while len(text) > max_chars:
        split = text.rfind(' ', 0, max_chars)
        if split <= 0:
            split = max_chars
        lines.append(text[:split].rstrip())
        text = text[split:].lstrip()
    if text:
        lines.append(text)
    return lines


def _center_cursor():
    try:
        windows = bpy.context.window_manager.windows
        if windows:
            window = windows[0]
            window.cursor_warp(window.width // 2,
                               window.height // 2)
    except Exception:
        pass


def _print_console_update():
    v = bl_info["version"]
    tag = _update_state.get('latest_tag', '?')
    changelog = _get_changelog_lines()
    print("")
    print("=" * 50)
    print("  Epic Fight JSON: UPDATE AVAILABLE!")
    print("  Installed: v%d.%d.%d" % (v[0], v[1], v[2]))
    print("  Available: %s" % tag)
    if changelog:
        print("  Changelog:")
        for line in changelog:
            print("    %s" % line.rstrip())
    print("  Go to Edit > Preferences > Add-ons")
    print("  to install the update.")
    print("=" * 50)
    print("")


def _show_update_popup():
    if _update_state.get('popup_shown'):
        return True

    # guard against re-entry on 2.79 where the operator call
    # can trigger scene_update_post before popup_shown is set
    if _showing_popup[0]:
        return False
    _showing_popup[0] = True

    _popup_attempts[0] += 1
    _center_cursor()

    try:
        bpy.ops.epicfight.update_popup('INVOKE_DEFAULT')
        _update_state['popup_shown'] = True
        _update_state['pending_popup'] = False
        print("EF-UPDATE: update dialog shown")
        _showing_popup[0] = False
        return True
    except Exception:
        if _popup_attempts[0] >= 10:
            _update_state['popup_shown'] = True
            _update_state['pending_popup'] = False
            _print_console_update()
            _showing_popup[0] = False
            return True
        print("EF-UPDATE: popup attempt %d failed, will retry"
              % _popup_attempts[0])
        _showing_popup[0] = False
        return False


def _draw_changelog_compact(parent_layout, changelog, max_chars):
    cl_box = parent_layout.box()
    cl_box.label(text="What's New:")
    col = cl_box.column(align=True)
    col.scale_y = _CHANGELOG_SCALE_Y
    shown = 0
    for line in changelog:
        text = line.rstrip()
        if not text:
            continue
        for wrapped in _wrap_line(text, max_chars):
            col.label(text="  " + wrapped)
            shown += 1
            if shown >= _MAX_POPUP_LINES:
                break
        if shown >= _MAX_POPUP_LINES:
            col.label(
                text="  ... full notes in "
                     "Addon Preferences")
            break


class EPICFIGHT_OT_update_popup(bpy.types.Operator):
    """Centered update notification dialog"""
    bl_idname = "epicfight.update_popup"
    bl_label = "Epic Fight JSON — Update Available"
    bl_options = {'INTERNAL'}

    def draw(self, context):
        layout = self.layout
        v = bl_info["version"]
        tag = _update_state.get('latest_tag', '?')
        title = _update_state.get('release_name', '') or tag
        changelog = _get_changelog_lines()
        _dw, max_chars = _get_popup_metrics()

        box = layout.box()
        box.label(text="A new update is available!", icon='INFO')
        if title and title != tag:
            for wrapped in _wrap_line(title, max_chars):
                box.label(text=wrapped)

        layout.separator()

        col = layout.column(align=True)
        col.label(
            text="Installed:  v%d.%d.%d" % (v[0], v[1], v[2]))
        col.label(text="Available:  %s" % tag)

        if changelog:
            layout.separator()
            _draw_changelog_compact(layout, changelog, max_chars)

        layout.separator()

        row = layout.row()
        row.scale_y = 1.5
        row.operator(
            "epicfight.install_update",
            text="Download & Install",
            icon='IMPORT')

    def execute(self, context):
        return {'FINISHED'}

    def invoke(self, context, event):
        _center_cursor()
        wm = context.window_manager
        dialog_width, _mc = _get_popup_metrics()
        try:
            return wm.invoke_props_dialog(self, width=dialog_width)
        except TypeError:
            return wm.invoke_props_dialog(self)


class EPICFIGHT_OT_check_update(bpy.types.Operator):
    """Check GitHub for a newer version of this addon"""
    bl_idname = "epicfight.check_update"
    bl_label = "Check for Updates"

    def execute(self, context):
        from . import updater
        result = updater.check_for_update(bl_info["version"])
        _store_check_result(result)
        _update_state['installed'] = False
        _update_state['install_msg'] = ''
        _update_state['manually_checked'] = True

        if result.get('error'):
            self.report({'WARNING'},
                        "Update check failed: %s"
                        % result['error'])
        elif result.get('update_available'):
            self.report({'INFO'},
                        "Update available: %s"
                        % result['latest_tag'])
        else:
            self.report({'INFO'},
                        "You are running the latest version.")
        return {'FINISHED'}


class EPICFIGHT_OT_install_update(bpy.types.Operator):
    """Download and install the latest version from GitHub"""
    bl_idname = "epicfight.install_update"
    bl_label = "Install Update"

    def execute(self, context):
        from . import updater
        url = _update_state.get('download_url', '')
        if not url:
            self.report({'ERROR'}, "No download URL available.")
            return {'CANCELLED'}
        if not _ADDON_DIR:
            self.report({'ERROR'},
                        "Cannot determine addon directory.")
            return {'CANCELLED'}
        ok, msg = updater.install_update(url, _ADDON_DIR)
        _update_state['installed'] = ok
        _update_state['install_msg'] = msg
        if ok:
            self.report({'INFO'}, msg)
        else:
            self.report({'ERROR'}, msg)
        return {'FINISHED'} if ok else {'CANCELLED'}


class EPICFIGHT_OT_dismiss_update(bpy.types.Operator):
    """Dismiss the update notification for this session"""
    bl_idname = "epicfight.dismiss_update"
    bl_label = "Dismiss"

    def execute(self, context):
        self.report({'INFO'},
                    "Update dismissed. Check again via "
                    "Edit > Preferences > Add-ons.")
        return {'FINISHED'}


class EpicFightJSONPreferences(bpy.types.AddonPreferences):
    bl_idname = _ADDON_MODULE

    def draw(self, context):
        layout = self.layout
        v = bl_info["version"]
        layout.label(
            text="Epic Fight JSON  v%d.%d.%d" % (v[0], v[1], v[2]))

        update_box = layout.box()
        update_box.label(text="Updates", icon='URL')

        manually = _update_state.get('manually_checked', False)

        if _update_state.get('installed'):
            update_box.label(
                text=_update_state.get('install_msg', ''),
                icon='INFO')
            update_box.label(
                text="Restart Blender to apply the update.",
                icon='ERROR')
            update_box.separator()
            update_box.operator(
                "epicfight.check_update",
                text="Check Again",
                icon='FILE_REFRESH')

        elif manually and _update_state.get('error'):
            update_box.label(
                text="Check failed: %s"
                % _update_state['error'],
                icon='ERROR')
            update_box.operator(
                "epicfight.check_update",
                text="Retry",
                icon='FILE_REFRESH')

        elif manually and _update_state.get('update_available'):

            title = (_update_state.get('release_name', '')
                     or _update_state.get('latest_tag', ''))
            tag = _update_state.get('latest_tag', '')

            update_box.label(text=title, icon='INFO')
            update_box.label(text="Tag:  %s" % tag)

            update_box.separator()
            update_box.label(
                text="Installed:  v%d.%d.%d"
                % (v[0], v[1], v[2]))
            update_box.label(
                text="Available:  %s" % tag)

            changelog = _get_changelog_lines()
            if changelog:
                update_box.separator()
                _dw, max_chars = _get_popup_metrics()
                cl_box = update_box.box()
                cl_box.label(text="Changelog:")
                col = cl_box.column(align=True)
                col.scale_y = _CHANGELOG_SCALE_Y
                for line in changelog:
                    text = line.rstrip()
                    if not text:
                        col.separator()
                    else:
                        for wrapped in _wrap_line(text, max_chars):
                            col.label(text=wrapped)

            update_box.separator()
            row = update_box.row()
            row.scale_y = 1.4
            row.operator(
                "epicfight.install_update",
                text="Download and Install Update",
                icon='IMPORT')

            update_box.operator(
                "epicfight.check_update",
                text="Check Again",
                icon='FILE_REFRESH')

        elif manually and _update_state.get('checked'):
            update_box.label(
                text="You are running the latest version.",
                icon='CHECKMARK')
            update_box.operator(
                "epicfight.check_update",
                text="Check Again",
                icon='FILE_REFRESH')

        else:
            update_box.operator(
                "epicfight.check_update",
                text="Check for Updates",
                icon='URL')


# startup auto check 

_poll_count = [0]


@bpy.app.handlers.persistent
def _load_post_handler(*args):
    # 1st fire = startup file, 2nd = user opened a file (splash gone)
    _load_post_count[0] += 1
    print("EF-UPDATE: load_post fired (#%d)"
          % _load_post_count[0])

    if _load_post_count[0] < 2:
        return

    _splash_dismissed[0] = True

    if (_update_state.get('pending_popup')
            and not _update_state.get('popup_shown')
            and not _showing_popup[0]):
        print("EF-UPDATE: file opened, showing pending popup")
        if IS_LEGACY:
            _show_update_popup()
        else:
            try:
                bpy.app.timers.register(_timer_show_popup,
                                        first_interval=0.5)
            except Exception:
                pass


# 2.80+ timers 

def _timer_begin_check():
    print("EF-UPDATE: startup timer fired")
    try:
        from . import updater
        if (not _update_state.get('checked')
                and not updater.is_checking()):
            updater.check_for_update_background(
                bl_info["version"])
    except Exception:
        traceback.print_exc()
        return None
    _poll_count[0] = 0
    bpy.app.timers.register(_timer_poll_result,
                            first_interval=0.5)
    return None


def _timer_poll_result():
    _poll_count[0] += 1
    try:
        from . import updater
        result = updater.get_background_result()
    except Exception:
        return None
    if result is None:
        if _poll_count[0] > 60:
            print("EF-UPDATE: gave up polling")
            return None
        return 0.5
    _store_check_result(result)
    if result.get('update_available'):
        _update_state['pending_popup'] = True
        _wait_ticks[0] = 0
        print("EF-UPDATE: update found, waiting for splash")
        bpy.app.timers.register(_timer_wait_ready,
                                first_interval=0.5)
    return None


def _timer_wait_ready():
    if _update_state.get('popup_shown'):
        return None

    _wait_ticks[0] += 1

    if _splash_dismissed[0] or _wait_ticks[0] > 12:
        if _splash_dismissed[0]:
            print("EF-UPDATE: splash gone (file opened)")
        else:
            print("EF-UPDATE: splash fallback (6s elapsed)")
        if _show_update_popup():
            return None
        if _wait_ticks[0] > 30:
            return None
        return 0.5

    return 0.5


def _timer_show_popup():
    _show_update_popup()
    return None


# 2.79 handler

_legacy_ticks = [0]
_legacy_started = [False]


@bpy.app.handlers.persistent
def _legacy_update_handler(scene):
    # on 2.79 scene_update_post can re-enter via cursor_warp / bpy.ops
    if _showing_popup[0]:
        return
    if _update_state.get('popup_shown'):
        _legacy_remove_handler()
        return

    _legacy_ticks[0] += 1
    if _legacy_ticks[0] < 30:
        return
    try:
        from . import updater
    except Exception:
        _legacy_remove_handler()
        return

    if not _legacy_started[0]:
        _legacy_started[0] = True
        if not _update_state.get('checked'):
            updater.check_for_update_background(
                bl_info["version"])
        return

    if not _update_state.get('checked'):
        result = updater.get_background_result()
        if result is None:
            if _legacy_ticks[0] > 500:
                _legacy_remove_handler()
            return
        _store_check_result(result)
        if result.get('update_available'):
            _update_state['pending_popup'] = True

    if not _update_state.get('update_available'):
        _legacy_remove_handler()
        return

    if _splash_dismissed[0] or _legacy_ticks[0] > 200:
        _legacy_remove_handler()
        _show_update_popup()


def _legacy_remove_handler():
    try:
        h = bpy.app.handlers.scene_update_post
        if _legacy_update_handler in h:
            h.remove(_legacy_update_handler)
    except (ValueError, AttributeError):
        pass


# -- menus

def _menu_export(self, context):
    self.layout.operator(ExportToJson.bl_idname,
                         text="Animated Minecraft Model (.json)")
    self.layout.operator(BatchExportAnimations.bl_idname,
                         text="Batch MC Animations (.json)")


def _menu_import(self, context):
    self.layout.operator(ImportFromJson.bl_idname,
                         text="Animated Minecraft Model (.json)")


# -- registration

_classes = [
    ExportToJson,
    BatchExportAnimations,
    ImportFromJson,
    EPICFIGHT_OT_update_popup,
    EPICFIGHT_OT_check_update,
    EPICFIGHT_OT_install_update,
    EPICFIGHT_OT_dismiss_update,
    EpicFightJSONPreferences,
]


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)

    if IS_LEGACY:
        bpy.types.INFO_MT_file_export.append(_menu_export)
        bpy.types.INFO_MT_file_import.append(_menu_import)
    else:
        bpy.types.TOPBAR_MT_file_export.append(_menu_export)
        bpy.types.TOPBAR_MT_file_import.append(_menu_import)

    if not bpy.app.background:
        _load_post_count[0] = 0
        _splash_dismissed[0] = False
        _popup_attempts[0] = 0
        _wait_ticks[0] = 0
        _showing_popup[0] = False
        _update_state['pending_popup'] = False
        _update_state['popup_shown'] = False
        _update_state['manually_checked'] = False

        try:
            if _load_post_handler not in bpy.app.handlers.load_post:
                bpy.app.handlers.load_post.append(
                    _load_post_handler)
        except Exception:
            pass

        if IS_LEGACY:
            _legacy_ticks[0] = 0
            _legacy_started[0] = False
            try:
                h = bpy.app.handlers.scene_update_post
                if _legacy_update_handler not in h:
                    h.append(_legacy_update_handler)
            except AttributeError:
                pass
        else:
            try:
                bpy.app.timers.register(
                    _timer_begin_check, first_interval=0.5)
            except Exception:
                pass


def unregister():
    try:
        if _load_post_handler in bpy.app.handlers.load_post:
            bpy.app.handlers.load_post.remove(_load_post_handler)
    except (ValueError, AttributeError):
        pass

    if IS_LEGACY:
        _legacy_remove_handler()
    else:
        for fn in (_timer_begin_check, _timer_poll_result,
                   _timer_wait_ready, _timer_show_popup):
            try:
                bpy.app.timers.unregister(fn)
            except (ValueError, AttributeError):
                pass

    if IS_LEGACY:
        bpy.types.INFO_MT_file_import.remove(_menu_import)
        bpy.types.INFO_MT_file_export.remove(_menu_export)
    else:
        bpy.types.TOPBAR_MT_file_import.remove(_menu_import)
        bpy.types.TOPBAR_MT_file_export.remove(_menu_export)

    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)