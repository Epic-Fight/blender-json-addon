from collections import OrderedDict
import json
import math
import os
import re
import traceback

import bpy
import mathutils
from mathutils import Matrix, Vector, Quaternion

IS_LEGACY = bpy.app.version < (2, 80, 0)


def mat_mul(a, b):
    if IS_LEGACY:
        return a * b
    return a @ b


def matrix_compose(loc, rot, sca):
    mat_sca = Matrix.Identity(4)
    mat_sca[0][0] = sca[0]
    mat_sca[1][1] = sca[1]
    mat_sca[2][2] = sca[2]
    return mat_mul(mat_mul(Matrix.Translation(Vector(loc)),
                           rot.to_matrix().to_4x4()),
                   mat_sca)


class ExportError(Exception):
    pass


# -- .json formatting

class NoIndent(object):
    def __init__(self, value):
        self.value = value


class NoIndentEncoder(json.JSONEncoder):
    FORMAT_SPEC = '@@{}@@'
    regex = re.compile(FORMAT_SPEC.format(r'(\d+)'))

    def __init__(self, **kwargs):
        self.__sort_keys = kwargs.get('sort_keys', None)
        super(NoIndentEncoder, self).__init__(**kwargs)
        self._no_indent_objects = {}

    def default(self, obj):
        if isinstance(obj, NoIndent):
            key = id(obj)
            self._no_indent_objects[key] = obj
            return self.FORMAT_SPEC.format(key)
        return super(NoIndentEncoder, self).default(obj)

    def encode(self, obj):
        format_spec = self.FORMAT_SPEC
        json_repr = super(NoIndentEncoder, self).encode(obj)

        for match in self.regex.finditer(json_repr):
            key = int(match.group(1))
            no_indent = self._no_indent_objects.get(key)
            if no_indent is not None:
                json_obj_repr = json.dumps(no_indent.value,
                                           sort_keys=self.__sort_keys)
                json_repr = json_repr.replace(
                    '"{}"'.format(format_spec.format(key)),
                    json_obj_repr)
        return json_repr


def ensure_extension(filepath, extension):
    if not filepath.lower().endswith(extension):
        filepath += extension
    return filepath


def veckey2d(v):
    return round(v.x, 4), round(v.y, 4)


def veckey3d(v):
    return round(v.x, 4), round(v.y, 4), round(v.z, 4)


def wrap_matrix(mat):
    return NoIndent([round(e, 6) for v in mat for e in v])


def create_array_dict(stride, count, array):
    d = OrderedDict()
    d['stride'] = stride
    d['count'] = count
    d['array'] = NoIndent(array)
    return d


def decompose_to_dict(matrix):
    loc, rot, sca = matrix.decompose()
    d = OrderedDict()
    d['loc'] = [round(v, 6) for v in loc]
    d['rot'] = [round(v, 6) for v in rot]
    d['sca'] = [round(v, 6) for v in sca]
    return NoIndent(d)


# -- bone utils

def find_deform_parent(bone):
    parent = bone.parent
    while parent is not None:
        if parent.use_deform:
            return parent
        parent = parent.parent
    return None


def correct_bones_as_vertex_groups(obj, bones, armature_obj=None):
    deform_names = None
    if armature_obj is not None:
        deform_names = {b.name for b in armature_obj.data.bones
                        if b.use_deform}

    corrected = []
    for vg in obj.vertex_groups:
        name = vg.name
        if not name.endswith("_mesh") and name != "Clothing":
            if deform_names is None or name in deform_names:
                corrected.append(name)
    return corrected


# -- fcurve helpers

def get_fcurves_from_action(action):
    if hasattr(action, 'fcurves') and len(action.fcurves) > 0:
        return list(action.fcurves)

    # 4.x+ layered actions
    fcurves = []
    if hasattr(action, 'layers'):
        for layer in action.layers:
            for strip in layer.strips:
                if hasattr(strip, 'channelbags'):
                    for channelbag in strip.channelbags:
                        fcurves.extend(channelbag.fcurves)
    return fcurves


def get_bone_name_from_fcurve(fcurve):
    if hasattr(fcurve, 'group') and fcurve.group is not None:
        return fcurve.group.name

    match = re.match(r'pose\.bones\["(.+?)"\]', fcurve.data_path)
    if match:
        return match.group(1)
    return None


def get_group_name_from_fcurve(fcurve):
    if hasattr(fcurve, 'group') and fcurve.group is not None:
        return fcurve.group.name
    return None


# -- keyframe optimization

def optimize_animation_keyframes(animation_data):
    """Remove redundant middle keyframes in runs of identical transforms."""
    total_removed = 0

    for entry in animation_data:
        time_obj = entry.get('time')
        transform_array = entry.get('transform')

        if time_obj is None or transform_array is None:
            continue

        times = (time_obj.value
                 if isinstance(time_obj, NoIndent) else time_obj)

        if len(times) <= 2:
            continue

        def _val(t):
            return t.value if isinstance(t, NoIndent) else t

        keep = []
        i = 0

        while i < len(times):
            run_start = i
            while (i + 1 < len(times)
                   and _val(transform_array[i + 1])
                       == _val(transform_array[run_start])):
                i += 1
            run_end = i

            if run_end - run_start + 1 >= 3:
                keep.append(run_start)
                keep.append(run_end)
            else:
                for j in range(run_start, run_end + 1):
                    keep.append(j)

            i += 1

        if len(keep) < len(times):
            removed = len(times) - len(keep)
            total_removed += removed

            entry['time'] = NoIndent([times[k] for k in keep])
            entry['transform'] = [transform_array[k] for k in keep]

            print("INFO     Optimized '%s': removed %d redundant "
                  "keyframe(s)" % (entry.get('name', '?'), removed))

    if total_removed > 0:
        print("INFO     Total redundant keyframes removed: %d"
              % total_removed)


# -- armature export

def export_armature(obj, export_visible_bones, armature_format='MAT'):
    skipped = []

    def _walk(b, bone_list, bone_dict, vis_only, fmt):
        if vis_only and b.hide:
            return None

        if not b.use_deform:
            skipped.append(b.name)
            promoted = []
            for child in b.children:
                result = _walk(child, bone_list, OrderedDict(),
                               vis_only, fmt)
                if result is not None:
                    if isinstance(result, list):
                        promoted.extend(result)
                    else:
                        promoted.append(result)
            return promoted if promoted else None

        bone_list.append(b.name)

        matrix = b.matrix_local
        deform_parent = find_deform_parent(b)
        if deform_parent is not None:
            matrix = mat_mul(deform_parent.matrix_local.inverted_safe(),
                             matrix)

        bone_dict['name'] = b.name

        if fmt == 'ATTR':
            bone_dict['transform'] = decompose_to_dict(matrix)
        else:
            bone_dict['transform'] = wrap_matrix(matrix)

        children = []
        for child in b.children:
            result = _walk(child, bone_list, OrderedDict(),
                           vis_only, fmt)
            if result is not None:
                if isinstance(result, list):
                    children.extend(result)
                else:
                    children.append(result)
        bone_dict['children'] = children

        return bone_dict

    output = OrderedDict()
    bones = []
    hierarchy = []

    for b in obj.data.bones:
        if b.parent is not None:
            continue
        result = _walk(b, bones, OrderedDict(),
                       export_visible_bones, armature_format)
        if result is not None:
            if isinstance(result, list):
                hierarchy.extend(result)
            else:
                hierarchy.append(result)

    if skipped:
        print("INFO  Skipped %d non-deform bone(s): %s"
              % (len(skipped), ', '.join(skipped)))

    if not bones:
        raise ExportError(
            "Armature '%s' produced no exportable bones. "
            "If 'Export Only Visible Bones' is checked, make sure at "
            "least some bones are visible. Also ensure your deform "
            "bones have 'Deform' enabled in Bone Properties."
            % obj.name)

    output['joints'] = NoIndent(bones)
    output['hierarchy'] = hierarchy

    return output


# -- animation export

def export_animation(obj, bone_name_list, animation_format,
                     bake=False):
    scene = bpy.context.scene

    if obj.animation_data is None:
        raise ExportError(
            "Armature '%s' has no animation data. "
            "Create an action or uncheck 'Export Animation'." % obj.name)

    action = obj.animation_data.action
    if action is None:
        raise ExportError(
            "Armature '%s' has no active action. "
            "Assign an action or uncheck 'Export Animation'." % obj.name)

    bones = obj.data.bones
    deform_set = set(bone_name_list)

    dope_sheet = {}
    timelines = []

    if bake:
        frame_range = action.frame_range
        start = int(frame_range[0])
        end = int(frame_range[1])
        timelines = list(range(start, end + 1))

        if not timelines:
            raise ExportError(
                "Action '%s' on armature '%s' has an empty frame range. "
                "Make sure the action has keyframes."
                % (action.name, obj.name))

        print("INFO     Baking visual transforms: frames %d - %d "
              "(%d frames)" % (start, end, len(timelines)))
    else:
        for curve in get_fcurves_from_action(action):
            name = get_bone_name_from_fcurve(curve)
            if name is None or name not in deform_set:
                continue

            if name not in dope_sheet:
                dope_sheet[name] = {'transform': [], 'timestamp': []}

            for kf in curve.keyframe_points:
                val = int(kf.co[0])
                if val not in dope_sheet[name]['timestamp']:
                    dope_sheet[name]['timestamp'].append(val)
                if val not in timelines:
                    timelines.append(val)

        if not timelines:
            raise ExportError(
                "Action '%s' on armature '%s' contains no keyframes "
                "for deform bones. Make sure your deform bones have "
                "keyframes, or uncheck 'Export Animation'."
                % (action.name, obj.name))

        timelines.sort()

    for t in timelines:
        scene.frame_set(t)

        for b in bones:
            if not b.use_deform:
                continue

            if b.name not in dope_sheet:
                dope_sheet[b.name] = {'transform': [], 'timestamp': []}

            if (bake
                    or t in dope_sheet[b.name]['timestamp']
                    or t == 0
                    or t == timelines[-1]):

                matrix = obj.pose.bones[b.name].matrix.copy()
                bone_local = b.matrix_local.copy()

                if animation_format == 'ATTR':
                    deform_parent = find_deform_parent(b)
                    if deform_parent is not None:
                        bone_local = mat_mul(
                            deform_parent.matrix_local.inverted_safe(),
                            bone_local)
                        parent_pose_inv = (
                            obj.pose.bones[deform_parent.name]
                               .matrix.inverted_safe())
                        matrix = mat_mul(
                            mat_mul(bone_local.inverted_safe(),
                                    parent_pose_inv),
                            matrix)
                    else:
                        matrix = mat_mul(bone_local.inverted_safe(),
                                         matrix)

                    if t not in dope_sheet[b.name]['timestamp']:
                        dope_sheet[b.name]['timestamp'].append(t)

                    dope_sheet[b.name]['transform'].append(
                        decompose_to_dict(matrix))
                else:
                    deform_parent = find_deform_parent(b)
                    if deform_parent is not None:
                        parent_pose_inv = (
                            obj.pose.bones[deform_parent.name]
                               .matrix.inverted_safe())
                        matrix = mat_mul(parent_pose_inv, matrix)

                    if t not in dope_sheet[b.name]['timestamp']:
                        dope_sheet[b.name]['timestamp'].append(t)

                    dope_sheet[b.name]['transform'].append(
                        wrap_matrix(matrix))

    output = []
    for b in bone_name_list:
        if b not in dope_sheet:
            print("WARNING  Bone '%s' has no animation data - skipped."
                  % b)
            continue
        d = OrderedDict()
        d['name'] = b
        d['time'] = NoIndent(
            [round(t / scene.render.fps, 4)
             for t in dope_sheet[b]['timestamp']])
        d['transform'] = dope_sheet[b]['transform']
        output.append(d)

    return output


# -- Camera export --

def export_camera(camera_obj):
    scene = bpy.context.scene

    if camera_obj.animation_data is None:
        raise ExportError(
            "Camera '%s' has no animation data. "
            "Add keyframes to the camera or uncheck 'Export Camera'."
            % camera_obj.name)

    action = camera_obj.animation_data.action
    if action is None:
        raise ExportError(
            "Camera '%s' has no active action. "
            "Assign an action or uncheck 'Export Camera'."
            % camera_obj.name)

    fcurves = get_fcurves_from_action(action)

    kf_names = set()
    has_groups = False
    for fc in fcurves:
        name = get_group_name_from_fcurve(fc)
        if name is not None:
            has_groups = True
            kf_names.add(name)

    if has_groups and len(kf_names) != 1:
        raise ExportError(
            "Camera action '%s' has %d keyframe group(s) (%s), "
            "but exactly 1 is expected. "
            "Make sure all camera F-Curves belong to a single group "
            "(select all keyframes in the Dope Sheet and press Ctrl+G "
            "to assign them to one group)."
            % (action.name, len(kf_names),
               ', '.join(kf_names) if kf_names else '<none>'))

    timestamp = []
    for curve in fcurves:
        for kf in curve.keyframe_points:
            val = int(kf.co[0])
            if val not in timestamp:
                timestamp.append(val)

    timestamp.sort()

    if not timestamp:
        raise ExportError(
            "Camera '%s' action '%s' contains no keyframes."
            % (camera_obj.name, action.name))

    transform = []
    blender_to_mc = Quaternion((1.0, 0.0, 0.0), math.radians(-90.0))

    for t in timestamp:
        scene.frame_set(t)
        world_mat = mat_mul(
            Matrix.Translation(Vector((0.0, 0.0, -1.62))),
            camera_obj.matrix_world)

        loc, rot, sca = world_mat.decompose()
        loc.rotate(blender_to_mc)
        rot.rotate(blender_to_mc)

        td = OrderedDict()
        td['loc'] = [round(v, 6) for v in loc]
        td['rot'] = [round(v, 6) for v in rot]
        td['sca'] = [round(v, 6) for v in sca]
        transform.append(NoIndent(td))

    output = OrderedDict()
    output['time'] = NoIndent(
        [round(t / scene.render.fps, 4) for t in timestamp])
    output['transform'] = transform

    return output


# -- main save (single-file export)

def save_common(operator, context, export_mesh_fn, **kwargs):
    file_path = ensure_extension(kwargs['filepath'], ".json")
    output = OrderedDict()

    mesh_obj = armature_obj = camera_obj = None
    mesh_result = armature_result = animation_result = camera_result = None

    export_msh    = kwargs.get('export_mesh', True)
    export_armat  = kwargs.get('export_armature', True)
    export_anim   = kwargs.get('export_anim', True)
    export_cam    = kwargs.get('export_camera', False)
    apply_mods    = kwargs.get('apply_modifiers', False)
    anim_fmt      = kwargs.get('animation_format', 'ATTR')
    arm_fmt       = kwargs.get('armature_format', 'MAT')
    vis_bones     = kwargs.get('export_only_visible_bones', False)
    optimize_kf   = kwargs.get('optimize_keyframes', False)
    bake_anim     = kwargs.get('bake_animation', False)

    for obj in context.scene.objects:
        if obj.type == 'MESH' and mesh_obj is None:
            mesh_obj = obj
        elif obj.type == 'ARMATURE' and armature_obj is None:
            armature_obj = obj
        elif obj.type == 'CAMERA' and camera_obj is None:
            camera_obj = obj

    if export_msh and mesh_obj is None:
        operator.report(
            {'WARNING'},
            "No mesh object found in the scene. Mesh export skipped.")
        export_msh = False

    if armature_obj is None:
        if export_armat:
            operator.report(
                {'WARNING'},
                "No armature object found. Armature export skipped.")
            export_armat = False
        if export_anim:
            operator.report(
                {'WARNING'},
                "No armature object found. Animation export skipped.")
            export_anim = False
    else:
        if export_anim:
            if armature_obj.animation_data is None:
                operator.report(
                    {'WARNING'},
                    "Armature '%s' has no animation data. "
                    "Animation export skipped." % armature_obj.name)
                export_anim = False
            elif armature_obj.animation_data.action is None:
                operator.report(
                    {'WARNING'},
                    "Armature '%s' has no active action. "
                    "Animation export skipped." % armature_obj.name)
                export_anim = False

    if export_cam:
        if camera_obj is None:
            operator.report(
                {'ERROR'},
                "No camera object found. "
                "Add a camera or uncheck 'Export Camera'.")
            return {'CANCELLED'}
        if camera_obj.animation_data is None:
            operator.report(
                {'ERROR'},
                "Camera '%s' has no animation data. "
                "Add keyframes or uncheck 'Export Camera'."
                % camera_obj.name)
            return {'CANCELLED'}
        if camera_obj.animation_data.action is None:
            operator.report(
                {'ERROR'},
                "Camera '%s' has no active action. "
                "Assign an action or uncheck 'Export Camera'."
                % camera_obj.name)
            return {'CANCELLED'}

    if armature_obj is not None:
        nd_bones = [b.name for b in armature_obj.data.bones
                    if not b.use_deform]
        if nd_bones:
            operator.report(
                {'INFO'},
                "Skipping %d non-deform bone(s): %s"
                % (len(nd_bones), ', '.join(nd_bones)))

    if armature_obj is not None:
        try:
            armature_result = export_armature(
                armature_obj, vis_bones, arm_fmt)
        except ExportError as e:
            operator.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        except Exception as e:
            traceback.print_exc()
            operator.report(
                {'ERROR'},
                "Unexpected error exporting armature: %s" % str(e))
            return {'CANCELLED'}

        if export_anim:
            try:
                animation_result = export_animation(
                    armature_obj,
                    armature_result['joints'].value,
                    anim_fmt,
                    bake=bake_anim)
            except ExportError as e:
                operator.report({'ERROR'}, str(e))
                return {'CANCELLED'}
            except Exception as e:
                traceback.print_exc()
                operator.report(
                    {'ERROR'},
                    "Unexpected error exporting animation: %s"
                    % str(e))
                return {'CANCELLED'}

            if optimize_kf and animation_result is not None:
                optimize_animation_keyframes(animation_result)

    if mesh_obj is not None:
        if armature_result is not None:
            armature_result['joints'].value = \
                correct_bones_as_vertex_groups(
                    mesh_obj, armature_result['joints'].value,
                    armature_obj)

        if export_msh:
            try:
                mesh_result = export_mesh_fn(
                    mesh_obj,
                    (armature_result['joints'].value
                     if armature_result is not None else None),
                    apply_modifiers=apply_mods)
            except ExportError as e:
                operator.report({'ERROR'}, str(e))
                return {'CANCELLED'}
            except Exception as e:
                traceback.print_exc()
                operator.report(
                    {'ERROR'},
                    "Unexpected error exporting mesh: %s" % str(e))
                return {'CANCELLED'}

    if export_cam:
        try:
            camera_result = export_camera(camera_obj)
        except ExportError as e:
            operator.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        except Exception as e:
            traceback.print_exc()
            operator.report(
                {'ERROR'},
                "Unexpected error exporting camera: %s" % str(e))
            return {'CANCELLED'}

    if mesh_result is not None:
        output['vertices'] = mesh_result

    if armature_result is not None and export_armat:
        if arm_fmt == 'ATTR':
            output['armature_format'] = 'attributes'
        output['armature'] = armature_result

    if animation_result is not None and export_anim:
        if anim_fmt == 'ATTR':
            output['format'] = 'attributes'
        output['animation'] = animation_result

    if camera_result is not None and export_cam:
        output['camera'] = camera_result

    if not output:
        operator.report(
            {'WARNING'},
            "Nothing to export. Enable at least one export option and "
            "make sure the required objects exist in the scene.")
        return {'CANCELLED'}

    output['fps'] = float(context.scene.render.fps)

    try:
        json_str = json.dumps(output, cls=NoIndentEncoder, indent=4)
        with open(file_path, 'w') as f:
            f.write(json_str)
    except Exception as e:
        traceback.print_exc()
        operator.report(
            {'ERROR'},
            "Failed to write file '%s': %s" % (file_path, str(e)))
        return {'CANCELLED'}

    operator.report({'INFO'},
                    "Export completed successfully: %s" % file_path)
    return {"FINISHED"}


# -- batch animation export

def save_animation_batch(operator, context, export_dir, **kwargs):
    anim_fmt      = kwargs.get('animation_format', 'ATTR')
    arm_fmt       = kwargs.get('armature_format', 'MAT')
    vis_bones     = kwargs.get('export_only_visible_bones', False)
    optimize_kf   = kwargs.get('optimize_keyframes', False)
    bake_anim     = kwargs.get('bake_animation', False)
    include_armat = kwargs.get('export_armature', True)

    armature_obj = None
    for obj in context.scene.objects:
        if obj.type == 'ARMATURE':
            armature_obj = obj
            break

    if armature_obj is None:
        operator.report({'ERROR'},
                        "No armature found in the scene.")
        return {'CANCELLED'}

    try:
        armature_result = export_armature(
            armature_obj, vis_bones, arm_fmt)
    except ExportError as e:
        operator.report({'ERROR'}, str(e))
        return {'CANCELLED'}
    except Exception as e:
        traceback.print_exc()
        operator.report(
            {'ERROR'},
            "Armature export error: %s" % str(e))
        return {'CANCELLED'}

    bone_list = armature_result['joints'].value

    if armature_obj.animation_data is None:
        armature_obj.animation_data_create()
    original_action = armature_obj.animation_data.action

    exported = 0
    skipped = 0
    errors = []

    for action in bpy.data.actions:
        has_pose = False
        for fc in get_fcurves_from_action(action):
            if get_bone_name_from_fcurve(fc) is not None:
                has_pose = True
                break

        if not has_pose:
            skipped += 1
            continue

        armature_obj.animation_data.action = action

        try:
            animation_result = export_animation(
                armature_obj, bone_list, anim_fmt,
                bake=bake_anim)
        except ExportError as e:
            print("WARNING  Skipping action '%s': %s"
                  % (action.name, e))
            skipped += 1
            continue
        except Exception as e:
            traceback.print_exc()
            errors.append("Action '%s': %s"
                          % (action.name, str(e)))
            continue

        if optimize_kf and animation_result is not None:
            optimize_animation_keyframes(animation_result)

        output = OrderedDict()

        if include_armat:
            if arm_fmt == 'ATTR':
                output['armature_format'] = 'attributes'
            output['armature'] = armature_result

        if anim_fmt == 'ATTR':
            output['format'] = 'attributes'
        output['animation'] = animation_result
        output['fps'] = float(context.scene.render.fps)

        safe_name = re.sub(r'[<>:"/\\|?*]', '_', action.name)
        file_path = os.path.join(export_dir, safe_name + ".json")

        try:
            json_str = json.dumps(output, cls=NoIndentEncoder,
                                  indent=4)
            with open(file_path, 'w') as f:
                f.write(json_str)
            exported += 1
            print("INFO     Exported action '%s' -> %s"
                  % (action.name, file_path))
        except Exception as e:
            traceback.print_exc()
            errors.append("Failed to write '%s': %s"
                          % (file_path, str(e)))

    armature_obj.animation_data.action = original_action

    if errors:
        for err in errors:
            print("ERROR    %s" % err)
        operator.report(
            {'WARNING'},
            "%d error(s) during batch export — "
            "check the system console." % len(errors))

    if exported == 0:
        operator.report(
            {'WARNING'},
            "No actions exported. Make sure actions contain "
            "pose-bone keyframes.")
        return {'CANCELLED'}

    operator.report(
        {'INFO'},
        "Batch export: %d action(s) exported, %d skipped"
        % (exported, skipped))
    return {'FINISHED'}