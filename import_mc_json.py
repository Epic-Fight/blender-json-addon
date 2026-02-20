import json
import math
import os
import traceback

import bpy
from mathutils import Matrix, Vector, Quaternion

from . import compat

_mul = compat.mat_mul
IS_LEGACY = compat.IS_LEGACY


class ImportError(Exception):
    pass


def _link_object(context, obj):
    if IS_LEGACY:
        context.scene.objects.link(obj)
    else:
        context.collection.objects.link(obj)


def _set_active(context, obj):
    if IS_LEGACY:
        context.scene.objects.active = obj
    else:
        context.view_layer.objects.active = obj


def _select_object(obj, state=True):
    if IS_LEGACY:
        obj.select = state
    else:
        obj.select_set(state)


def _set_armature_display(armature_data, style):
    if hasattr(armature_data, 'display_type'):
        armature_data.display_type = style
    elif hasattr(armature_data, 'draw_type'):
        armature_data.draw_type = style


def _create_uv_layer(mesh, name):
    # 2.79 needs uv_textures.new(), 2.80+ uses uv_layers.new()
    if IS_LEGACY:
        mesh.uv_textures.new(name=name)
        return mesh.uv_layers.active
    return mesh.uv_layers.new(name=name)


def _group_bone_fcurves(action, bone_name):
    """On 2.79 fcurves aren't auto-grouped by bone, so do it manually."""
    if not hasattr(action, 'fcurves') or not hasattr(action, 'groups'):
        return
    prefix = 'pose.bones["%s"]' % bone_name
    group = None
    for fc in action.fcurves:
        if fc.data_path.startswith(prefix) and fc.group is None:
            if group is None:
                group = action.groups.get(bone_name)
                if group is None:
                    group = action.groups.new(bone_name)
            fc.group = group


def reconstruct_matrix_from_flat(flat):
    if len(flat) != 16:
        raise ImportError(
            "Matrix data must have 16 elements, got %d" % len(flat))
    return Matrix((flat[0:4], flat[4:8], flat[8:12], flat[12:16]))


def reconstruct_matrix_from_attr(transform):
    for key in ("loc", "rot", "sca"):
        if key not in transform:
            raise ImportError("Transform dict missing '%s'" % key)
    return compat.matrix_compose(
        Vector(transform["loc"]),
        Quaternion(transform["rot"]),
        Vector(transform["sca"]))


def reconstruct_relative_matrix(transform_data, fmt):
    if fmt == 'ATTR':
        return reconstruct_matrix_from_attr(transform_data)
    return reconstruct_matrix_from_flat(transform_data)


def timestamp_to_frame(time_seconds, fps):
    return round(time_seconds * fps)


def _get_all_fcurves(action):
    if hasattr(action, 'fcurves'):
        try:
            result = list(action.fcurves)
            if result:
                return result
        except Exception:
            pass
    # 4.x+ layered actions
    fcurves = []
    if hasattr(action, 'layers'):
        for layer in action.layers:
            for strip in getattr(layer, 'strips', []):
                for bag in getattr(strip, 'channelbags', []):
                    fcurves.extend(bag.fcurves)
    return fcurves


def _set_interpolation_linear(action):
    for fc in _get_all_fcurves(action):
        for kp in fc.keyframe_points:
            kp.interpolation = 'LINEAR'


def _expand_frame_range(context, frames):
    if not frames:
        return
    mn, mx = min(frames), max(frames)
    if context.scene.frame_start > mn:
        context.scene.frame_start = mn
    if context.scene.frame_end < mx:
        context.scene.frame_end = mx


# Armature import

def _parse_hierarchy_recursive(node, parent_name, parent_abs_matrix,
                               fmt, bone_data, bone_order):
    name = node.get("name")
    if not name:
        raise ImportError("Hierarchy node missing 'name' field")

    transform_data = node.get("transform")
    if transform_data is None:
        raise ImportError("Bone '%s' has no transform data" % name)

    relative = reconstruct_relative_matrix(transform_data, fmt)
    absolute = (_mul(parent_abs_matrix, relative)
                if parent_abs_matrix is not None else relative)

    children_names = [c["name"] for c in node.get("children", [])
                      if "name" in c]

    bone_data[name] = {
        "abs_matrix": absolute,
        "parent_name": parent_name,
        "children_names": children_names,
    }
    bone_order.append(name)

    for child in node.get("children", []):
        _parse_hierarchy_recursive(child, name, absolute,
                                   fmt, bone_data, bone_order)


def _estimate_bone_lengths(bone_data, bone_order):
    for name in bone_order:
        data = bone_data[name]
        head = data["abs_matrix"].translation
        children = data["children_names"]
        if children:
            dists = []
            for cname in children:
                if cname in bone_data:
                    d = (bone_data[cname]["abs_matrix"].translation
                         - head).length
                    if d > 0.001:
                        dists.append(d)
            data["length"] = min(dists) if dists else 0.1
        else:
            data["length"] = None

    for name in bone_order:
        data = bone_data[name]
        if data["length"] is None:
            pname = data["parent_name"]
            if pname and pname in bone_data and bone_data[pname]["length"]:
                data["length"] = bone_data[pname]["length"]
            else:
                data["length"] = 0.1


def import_armature(context, armature_json, armature_format,
                    armature_name):
    hierarchy = armature_json.get("hierarchy", [])
    if not hierarchy:
        raise ImportError("Armature has an empty hierarchy")

    bone_data = {}
    bone_order = []
    for root_node in hierarchy:
        _parse_hierarchy_recursive(root_node, None, None,
                                   armature_format, bone_data,
                                   bone_order)
    if not bone_order:
        raise ImportError("No bones found in armature hierarchy")

    _estimate_bone_lengths(bone_data, bone_order)

    if context.active_object and context.active_object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='DESELECT')

    armature_dat = bpy.data.armatures.new(armature_name)
    armature_obj = bpy.data.objects.new(armature_name, armature_dat)
    _link_object(context, armature_obj)
    _set_active(context, armature_obj)
    _select_object(armature_obj, True)

    bpy.ops.object.mode_set(mode='EDIT')
    try:
        for name in bone_order:
            data = bone_data[name]
            mat = data["abs_matrix"]

            eb = armature_dat.edit_bones.new(name)
            loc, rot, _sca = mat.decompose()
            rot_mat = rot.to_matrix()
            y_axis = _mul(rot_mat, Vector((0, 1, 0))).normalized()
            z_axis = _mul(rot_mat, Vector((0, 0, 1))).normalized()

            eb.head = loc
            eb.tail = loc + y_axis * data["length"]

            if (data["parent_name"]
                    and data["parent_name"]
                    in armature_dat.edit_bones):
                eb.parent = armature_dat.edit_bones[
                    data["parent_name"]]

            eb.use_deform = True
            eb.use_connect = False
            eb.align_roll(z_axis)
    finally:
        if armature_obj.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

    _set_armature_display(armature_dat, 'STICK')

    return {
        "armature_obj": armature_obj,
        "bone_data": bone_data,
        "bone_order": bone_order,
    }


# -- animation import

def _bone_local_relative(bone, bone_data):
    deform_parent = compat.find_deform_parent(bone)

    if bone_data and bone.name in bone_data:
        abs_mat = bone_data[bone.name]["abs_matrix"]
        if (deform_parent is not None
                and deform_parent.name in bone_data):
            parent_abs = bone_data[deform_parent.name]["abs_matrix"]
        elif deform_parent is not None:
            parent_abs = deform_parent.matrix_local
        else:
            return abs_mat
        return _mul(parent_abs.inverted_safe(), abs_mat)

    if deform_parent is not None:
        return _mul(deform_parent.matrix_local.inverted_safe(),
                    bone.matrix_local)
    return bone.matrix_local


def import_animation(context, armature_obj, animation_data,
                     animation_format, bone_data=None,
                     action_name="Imported", override_fps=None):
    if not animation_data:
        raise ImportError("Animation data is empty")

    fps = (override_fps if override_fps is not None
           else context.scene.render.fps)
    bones = armature_obj.data.bones
    target_names = set(bones.keys())

    if armature_obj.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    _set_active(context, armature_obj)

    for pb in armature_obj.pose.bones:
        pb.rotation_mode = 'QUATERNION'
        pb.location = (0.0, 0.0, 0.0)
        pb.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
        pb.scale = (1.0, 1.0, 1.0)

    action = bpy.data.actions.new(name=action_name)
    if armature_obj.animation_data is None:
        armature_obj.animation_data_create()
    armature_obj.animation_data.action = action

    all_frames = set()
    imported_bones = 0

    for entry in animation_data:
        bone_name = entry.get("name")
        if not bone_name or bone_name not in target_names:
            if bone_name:
                print("WARNING  Bone '%s' not in armature - skipped"
                      % bone_name)
            continue

        time_array = entry.get("time", [])
        transform_array = entry.get("transform", [])

        if len(time_array) != len(transform_array) or not time_array:
            if time_array or transform_array:
                print("WARNING  Bone '%s' time/transform mismatch "
                      "- skipped" % bone_name)
            continue

        frames = [timestamp_to_frame(t, fps) for t in time_array]
        all_frames.update(frames)

        bone = bones[bone_name]
        pose_bone = armature_obj.pose.bones[bone_name]

        locs = []
        rots = []
        scas = []

        if animation_format == 'ATTR':
            for tr in transform_array:
                locs.append(Vector(tr["loc"]))
                rots.append(Quaternion(tr["rot"]))
                scas.append(Vector(tr["sca"]))
        else:
            blr_inv = _bone_local_relative(
                bone, bone_data).inverted_safe()
            for tr in transform_array:
                stored = reconstruct_matrix_from_flat(tr)
                channel = _mul(blr_inv, stored)
                loc, rot, sca = channel.decompose()
                locs.append(loc)
                rots.append(rot)
                scas.append(sca)

        # flip quaternions to avoid interpolation artifacts
        for i in range(1, len(rots)):
            if rots[i - 1].dot(rots[i]) < 0:
                rots[i].negate()

        for ki in range(len(frames)):
            frame = frames[ki]

            pose_bone.location = (
                float(locs[ki][0]),
                float(locs[ki][1]),
                float(locs[ki][2]))
            pose_bone.keyframe_insert(
                data_path="location", frame=frame)

            pose_bone.rotation_quaternion = (
                float(rots[ki][0]),
                float(rots[ki][1]),
                float(rots[ki][2]),
                float(rots[ki][3]))
            pose_bone.keyframe_insert(
                data_path="rotation_quaternion", frame=frame)

            pose_bone.scale = (
                float(scas[ki][0]),
                float(scas[ki][1]),
                float(scas[ki][2]))
            pose_bone.keyframe_insert(
                data_path="scale", frame=frame)

        _group_bone_fcurves(action, bone_name)
        imported_bones += 1

    _set_interpolation_linear(action)
    _expand_frame_range(context, all_frames)

    print("INFO     Imported animation for %d bones, %d unique frames"
          % (imported_bones, len(all_frames)))
    return action


# -- mesh import

def _set_custom_normals(mesh, per_loop_normals):
    try:
        if hasattr(mesh, 'calc_normals_split'):
            mesh.calc_normals_split()
        mesh.normals_split_custom_set(per_loop_normals)
        if hasattr(mesh, 'use_auto_smooth'):
            mesh.use_auto_smooth = True
    except Exception as e:
        print("WARNING  Custom normals failed: %s" % e)


def import_mesh(context, mesh_json, joints_list, armature_obj,
                mesh_name):
    positions_data = mesh_json.get("positions")
    if not positions_data:
        raise ImportError("Mesh has no position data")

    parts_data = mesh_json.get("parts")
    if not parts_data:
        raise ImportError("Mesh has no parts data (no faces)")

    uvs_data = mesh_json.get("uvs")
    normals_data = mesh_json.get("normals")
    vcounts_data = mesh_json.get("vcounts")
    weights_data = mesh_json.get("weights")
    vindices_data = mesh_json.get("vindices")

    has_weights = all(d is not None
                      for d in (vcounts_data, weights_data,
                                vindices_data))
    if has_weights and not joints_list:
        print("WARNING  Mesh has weight data but no joints list "
              "- skipped")
        has_weights = False

    positions = positions_data["array"]
    num_verts = positions_data["count"]

    all_faces = []
    face_loops_uv = []
    face_loops_normal = []

    for part_name, part_d in parts_data.items():
        arr = part_d["array"]
        for i in range(0, len(arr), 9):
            all_faces.append(
                (int(arr[i]), int(arr[i + 3]), int(arr[i + 6])))
            face_loops_uv.append(
                (int(arr[i + 1]), int(arr[i + 4]),
                 int(arr[i + 7])))
            face_loops_normal.append(
                (int(arr[i + 2]), int(arr[i + 5]),
                 int(arr[i + 8])))

    num_faces = len(all_faces)
    if num_faces == 0:
        raise ImportError("Mesh parts contain no faces")

    num_loops = num_faces * 3

    mesh = bpy.data.meshes.new(mesh_name)
    mesh.vertices.add(num_verts)
    mesh.loops.add(num_loops)
    mesh.polygons.add(num_faces)

    mesh.vertices.foreach_set("co", positions)

    loop_verts = []
    loop_starts = []
    for fi, (v0, v1, v2) in enumerate(all_faces):
        loop_starts.append(fi * 3)
        loop_verts.extend((v0, v1, v2))

    mesh.loops.foreach_set("vertex_index", loop_verts)
    mesh.polygons.foreach_set("loop_start", loop_starts)
    mesh.polygons.foreach_set("loop_total", [3] * num_faces)

    mesh.validate(clean_customdata=False)
    mesh.update()

    if uvs_data:
        uv_arr = uvs_data["array"]
        uv_layer = _create_uv_layer(mesh, "UVMap")
        per_loop_uvs = []
        for fi in range(num_faces):
            for li in range(3):
                idx = face_loops_uv[fi][li]
                per_loop_uvs.append(float(uv_arr[idx * 2]))
                per_loop_uvs.append(
                    1.0 - float(uv_arr[idx * 2 + 1]))
        try:
            uv_layer.data.foreach_set("uv", per_loop_uvs)
        except Exception:
            for i in range(num_loops):
                uv_layer.data[i].uv = (
                    per_loop_uvs[i * 2],
                    per_loop_uvs[i * 2 + 1])

    if normals_data:
        n_arr = normals_data["array"]
        per_loop_normals = []
        for fi in range(num_faces):
            for li in range(3):
                idx = face_loops_normal[fi][li]
                per_loop_normals.append((
                    float(n_arr[idx * 3]),
                    float(n_arr[idx * 3 + 1]),
                    float(n_arr[idx * 3 + 2])))
        _set_custom_normals(mesh, per_loop_normals)

    mesh.update()

    mesh_obj = bpy.data.objects.new(mesh_name, mesh)
    _link_object(context, mesh_obj)

    if has_weights:
        vcounts = vcounts_data["array"]
        weight_palette = weights_data["array"]
        vindices = vindices_data["array"]

        expected_len = sum(int(c) for c in vcounts) * 2
        if expected_len != len(vindices):
            print("WARNING  vindices length mismatch "
                  "- weights skipped")
        else:
            vertex_groups = {}
            for bname in joints_list:
                if bname not in vertex_groups:
                    vertex_groups[bname] = \
                        mesh_obj.vertex_groups.new(name=bname)

            ptr = 0
            for vi in range(num_verts):
                count = int(vcounts[vi])
                for _ in range(count):
                    bi = int(vindices[ptr])
                    wi = int(vindices[ptr + 1])
                    ptr += 2
                    if (0 <= bi < len(joints_list)
                            and 0 <= wi < len(weight_palette)):
                        vertex_groups[joints_list[bi]].add(
                            [vi], float(weight_palette[wi]),
                            'REPLACE')

    for part_name, part_d in parts_data.items():
        if part_name == "noGroups":
            continue
        vg = mesh_obj.vertex_groups.new(
            name=part_name + "_mesh")
        arr = part_d["array"]
        idxs = set()
        for i in range(0, len(arr), 9):
            idxs.update((int(arr[i]), int(arr[i + 3]),
                         int(arr[i + 6])))
        if idxs:
            vg.add(list(idxs), 1.0, 'REPLACE')

    if armature_obj is not None:
        mesh_obj.parent = armature_obj
        mesh_obj.modifiers.new(
            name="Armature",
            type='ARMATURE').object = armature_obj

    return mesh_obj


# -- camera import

def _reverse_camera_transform(loc_raw, rot_raw, sca_raw):
    loc = Vector(loc_raw)
    rot = Quaternion(rot_raw)
    sca = Vector(sca_raw)

    mc_to_blender = Quaternion((1.0, 0.0, 0.0), math.radians(90.0))
    loc.rotate(mc_to_blender)
    rot.rotate(mc_to_blender)

    world_mat = compat.matrix_compose(loc, rot, sca)
    return _mul(
        Matrix.Translation(Vector((0.0, 0.0, 1.62))), world_mat)


def import_camera(context, camera_json, camera_name,
                  override_fps=None):
    time_array = camera_json.get("time", [])
    transform_array = camera_json.get("transform", [])

    if not time_array or not transform_array:
        raise ImportError("Camera has no keyframe data")
    if len(time_array) != len(transform_array):
        raise ImportError(
            "Camera time/transform length mismatch (%d vs %d)"
            % (len(time_array), len(transform_array)))

    fps = (override_fps if override_fps is not None
           else context.scene.render.fps)
    frames = [timestamp_to_frame(t, fps) for t in time_array]

    locs = []
    rots = []
    scas = []
    for tr in transform_array:
        cam_mat = _reverse_camera_transform(
            tr["loc"], tr["rot"], tr["sca"])
        loc, rot, sca = cam_mat.decompose()
        locs.append(loc)
        rots.append(rot)
        scas.append(sca)

    for i in range(1, len(rots)):
        if rots[i - 1].dot(rots[i]) < 0:
            rots[i].negate()

    cam_data = bpy.data.cameras.new(name=camera_name)
    cam_obj = bpy.data.objects.new(camera_name, cam_data)
    _link_object(context, cam_obj)
    cam_obj.rotation_mode = 'QUATERNION'
    context.scene.camera = cam_obj

    action = bpy.data.actions.new(name=camera_name + "_action")
    if cam_obj.animation_data is None:
        cam_obj.animation_data_create()
    cam_obj.animation_data.action = action

    for ki, frame in enumerate(frames):
        cam_obj.location = (
            float(locs[ki][0]), float(locs[ki][1]),
            float(locs[ki][2]))
        cam_obj.keyframe_insert(
            data_path="location", frame=frame)

        cam_obj.rotation_quaternion = (
            float(rots[ki][0]), float(rots[ki][1]),
            float(rots[ki][2]), float(rots[ki][3]))
        cam_obj.keyframe_insert(
            data_path="rotation_quaternion", frame=frame)

        cam_obj.scale = (
            float(scas[ki][0]), float(scas[ki][1]),
            float(scas[ki][2]))
        cam_obj.keyframe_insert(
            data_path="scale", frame=frame)

    _set_interpolation_linear(action)
    _expand_frame_range(context, frames)
    return cam_obj


# -- main entry point

def load(operator, context, **kwargs):
    filepath = kwargs["filepath"]

    try:
        with open(filepath, 'r') as f:
            json_data = json.load(f)
    except Exception as e:
        operator.report({'ERROR'},
                        "Failed to read JSON: %s" % str(e))
        return {'CANCELLED'}

    base_name = os.path.splitext(os.path.basename(filepath))[0]

    anim_fmt = ('ATTR' if json_data.get('format') == 'attributes'
                else 'MAT')
    arm_fmt = ('ATTR'
               if json_data.get('armature_format') == 'attributes'
               else 'MAT')

    has_mesh = 'vertices' in json_data
    has_armature = 'armature' in json_data
    has_animation = 'animation' in json_data
    has_camera = 'camera' in json_data

    if not any((has_mesh, has_armature, has_animation, has_camera)):
        operator.report({'WARNING'},
                        "JSON file contains no importable data")
        return {'CANCELLED'}

    stored_fps = json_data.get('fps')
    if stored_fps is not None:
        stored_fps = float(stored_fps)
        context.scene.render.fps = int(round(stored_fps))
        context.scene.render.fps_base = 1.0
        operator.report(
            {'INFO'},
            "Scene FPS set to %d (from JSON)"
            % context.scene.render.fps)

    armature_obj = None
    bone_data = None
    joints_list = None

    if (context.active_object
            and context.active_object.type == 'ARMATURE'):
        armature_obj = context.active_object
    else:
        scene_armatures = [obj for obj in context.scene.objects
                           if obj.type == 'ARMATURE']
        if len(scene_armatures) == 1:
            armature_obj = scene_armatures[0]

    if armature_obj is None and has_armature:
        try:
            result = import_armature(
                context, json_data["armature"],
                arm_fmt, base_name)
            armature_obj = result["armature_obj"]
            bone_data = result["bone_data"]
            operator.report(
                {'INFO'},
                "Created armature '%s'" % armature_obj.name)
        except ImportError as e:
            operator.report({'ERROR'},
                            "Armature import: %s" % str(e))
            return {'CANCELLED'}
        except Exception as e:
            traceback.print_exc()
            operator.report({'ERROR'},
                            "Armature import error: %s" % str(e))
            return {'CANCELLED'}
    elif armature_obj is not None:
        operator.report(
            {'INFO'},
            "Using existing armature '%s'" % armature_obj.name)

    if has_armature:
        joints_list = json_data["armature"].get("joints")

    if has_animation:
        if armature_obj is None:
            operator.report(
                {'ERROR'},
                "Cannot import animation: no armature available")
            return {'CANCELLED'}
        try:
            import_animation(
                context, armature_obj,
                json_data["animation"], anim_fmt,
                bone_data=bone_data,
                action_name=base_name,
                override_fps=stored_fps)
            operator.report(
                {'INFO'},
                "Imported animation '%s'" % base_name)
        except ImportError as e:
            operator.report({'ERROR'},
                            "Animation import: %s" % str(e))
            return {'CANCELLED'}
        except Exception as e:
            traceback.print_exc()
            operator.report(
                {'ERROR'},
                "Animation import error: %s" % str(e))
            return {'CANCELLED'}

    if has_mesh:
        try:
            mesh_obj = import_mesh(
                context, json_data["vertices"],
                joints_list, armature_obj,
                base_name + "_mesh")
            operator.report(
                {'INFO'},
                "Imported mesh '%s'" % mesh_obj.name)
        except ImportError as e:
            operator.report({'ERROR'},
                            "Mesh import: %s" % str(e))
            return {'CANCELLED'}
        except Exception as e:
            traceback.print_exc()
            operator.report(
                {'ERROR'},
                "Mesh import error: %s" % str(e))
            return {'CANCELLED'}

    if has_camera:
        try:
            cam_obj = import_camera(
                context, json_data["camera"],
                base_name + "_camera",
                override_fps=stored_fps)
            operator.report(
                {'INFO'},
                "Imported camera '%s'" % cam_obj.name)
        except ImportError as e:
            operator.report({'ERROR'},
                            "Camera import: %s" % str(e))
            return {'CANCELLED'}
        except Exception as e:
            traceback.print_exc()
            operator.report(
                {'ERROR'},
                "Camera import error: %s" % str(e))
            return {'CANCELLED'}

    operator.report({'INFO'},
                    "Import completed: %s" % filepath)
    return {'FINISHED'}