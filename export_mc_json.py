from collections import OrderedDict
import json
import re
import traceback
import math

import bpy
import mathutils


class ExportError(Exception):
    pass


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
                    '"{}"'.format(format_spec.format(key)), json_obj_repr)
        return json_repr


def ensure_extension(filepath, extension):
    if not filepath.lower().endswith(extension):
        filepath += extension
    return filepath


def mesh_triangulate(me):
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.triangulate(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()


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
    d['loc'] = NoIndent([round(v, 6) for v in loc])
    d['rot'] = NoIndent([round(v, 6) for v in rot])
    d['sca'] = NoIndent([round(v, 6) for v in sca])
    return d


def get_fcurves_from_action(action):
    if hasattr(action, 'fcurves') and len(action.fcurves) > 0:
        return list(action.fcurves)

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


# ──────────────────────────────────────────────────────────────────
#  NEW HELPER — walks up the parent chain to find the nearest
#  ancestor whose "Deform" flag (use_deform) is enabled.
#  Returns None when the bone is a root-level deform bone.
# ──────────────────────────────────────────────────────────────────
def _find_deform_parent(bone):
    """Return the nearest ancestor bone with use_deform=True, or None."""
    parent = bone.parent
    while parent is not None:
        if parent.use_deform:
            return parent
        parent = parent.parent
    return None


def export_mesh(obj, bones, apply_modifiers=False):
    # ── obtain the mesh, optionally with modifiers baked in ──
    if apply_modifiers:
        depsgraph = bpy.context.evaluated_depsgraph_get()
        obj_eval = obj.evaluated_get(depsgraph)
        try:
            obj_mesh = obj_eval.to_mesh(preserve_all_data_layers=True,
                                        depsgraph=depsgraph)
        except TypeError:
            obj_mesh = obj_eval.to_mesh()
    else:
        try:
            obj_mesh = obj.to_mesh(preserve_all_data_layers=True)
        except TypeError:
            obj_mesh = obj.to_mesh()

    # ── vertex-group look-up must always go through the *original* object ──
    original_poly_verts = [list(p.vertices) for p in obj_mesh.polygons]

    mesh_triangulate(obj_mesh)

    if hasattr(obj_mesh, 'calc_normals_split'):
        obj_mesh.calc_normals_split()

    owner_polygon_indices = {}
    for f in obj_mesh.polygons:
        tri_verts = set(f.vertices)
        owners = [i for i, orig_verts in enumerate(original_poly_verts)
                  if tri_verts.issubset(set(orig_verts))]

        if len(owners) != 1:
            raise ExportError(
                "Triangulation error: a triangulated face could not be "
                "matched to exactly one original polygon. "
                "Check the mesh '%s' for overlapping or degenerate faces."
                % obj.name)

        owner_polygon_indices[f.index] = owners[0]

    position_array = [round(pos, 6)
                      for v in obj_mesh.vertices
                      for pos in v.co[:]]

    uv_array = []
    normal_array = []
    loops = obj_mesh.loops
    uv_unique_count = no_unique_count = 0

    no_key = no_val = None
    normals_to_idx = {}
    no_get = normals_to_idx.get
    loops_to_normals = [0] * len(loops)

    for f in obj_mesh.polygons:
        for l_idx in f.loop_indices:
            no_key = veckey3d(loops[l_idx].normal)
            no_val = no_get(no_key)
            if no_val is None:
                no_val = normals_to_idx[no_key] = no_unique_count
                for n_val in no_key:
                    normal_array.append(n_val)
                no_unique_count += 1
            loops_to_normals[l_idx] = no_val

    del normals_to_idx, no_get, no_key, no_val

    uv_layer_active = obj_mesh.uv_layers.active
    if uv_layer_active is None:
        raise ExportError(
            "Mesh '%s' has no active UV layer. "
            "Unwrap the mesh before exporting." % obj.name)
    uv_layer = uv_layer_active.data[:]

    uv = f_index = uv_index = uv_key = uv_val = uv_ls = None
    uv_face_mapping = [None] * len(obj_mesh.polygons)
    uv_dict = {}
    uv_get = uv_dict.get

    for f_index, f in enumerate(obj_mesh.polygons):
        uv_ls = uv_face_mapping[f_index] = []
        for uv_index, l_index in enumerate(f.loop_indices):
            uv = uv_layer[l_index].uv
            uv_key = veckey2d(uv)
            uv_val = uv_get(uv_key)
            if uv_val is None:
                uv_val = uv_dict[uv_key] = uv_unique_count
                for i, uv_cor in enumerate(uv):
                    uv_array.append(
                        round(uv_cor if i % 2 == 0 else 1 - uv_cor, 6))
                uv_unique_count += 1
            uv_ls.append(uv_val)

    del uv_dict, uv, f_index, uv_index, uv_ls, uv_get, uv_key, uv_val

    parts = {'noGroups': []}
    for vg in obj.vertex_groups:
        if vg.name[-5:] == "_mesh":
            parts[vg.name[:-5]] = []

    for f_index, f in enumerate(obj_mesh.polygons):
        f_v = [(vi, obj_mesh.vertices[v_idx], l_idx)
               for vi, (v_idx, l_idx)
               in enumerate(zip(f.vertices, f.loop_indices))]

        polygons_part_indices = {}
        for name in parts.keys():
            polygons_part_indices[name] = []

        for vi, v, li in f_v:
            mesh_vgs = [obj.vertex_groups[vg.group].name
                        for vg in v.groups
                        if vg.group < len(obj.vertex_groups)]
            mesh_vgs = list(filter(lambda x: x[-5:] == "_mesh", mesh_vgs))

            if len(mesh_vgs) == 0:
                i_list = polygons_part_indices['noGroups']
                i_list.append(v.index)
                i_list.append(uv_face_mapping[f_index][vi])
                i_list.append(loops_to_normals[li])
            else:
                for name in mesh_vgs:
                    i_list = polygons_part_indices[name[:-5]]
                    i_list.append(v.index)
                    i_list.append(uv_face_mapping[f_index][vi])
                    i_list.append(loops_to_normals[li])

        for part_name, i_list in polygons_part_indices.items():
            if len(i_list) // 3 == len(f.vertices):
                orig_idx = owner_polygon_indices[f.index]
                orig_verts = original_poly_verts[orig_idx]
                vg_names = [
                    [obj.vertex_groups[vg.group].name[:-5]
                     for vg in v.groups
                     if (vg.group < len(obj.vertex_groups)
                         and obj.vertex_groups[vg.group].name[-5:] == '_mesh')]
                    for v in [obj_mesh.vertices[vid]
                              for vid in orig_verts]
                ]
                if part_name == 'noGroups':
                    if all(len(names) == 0 for names in vg_names):
                        parts[part_name].extend(i_list)
                else:
                    if all(part_name in names for names in vg_names):
                        parts[part_name].extend(i_list)

    output = OrderedDict()
    output['positions'] = create_array_dict(
        3, len(position_array) // 3, position_array)
    output['uvs'] = create_array_dict(
        2, len(uv_array) // 2, uv_array)
    output['normals'] = create_array_dict(
        3, len(normal_array) // 3, normal_array)

    if bones is not None:
        # ── FIX: build a set of accepted (deform) bone names so ──
        # ── weights to IK / non-deform bones are ignored         ──
        bones_set = set(bones)

        vcounts = []
        weights = []
        vindices = []

        for v in obj_mesh.vertices:
            vc_val = 0
            appended_joints = []
            weight_list = []
            weight_total = 0.0

            for vg in v.groups:
                if vg.group >= len(obj.vertex_groups):
                    continue
                w_val = max(min(vg.weight, 1.0), 0.0)
                name = obj.vertex_groups[vg.group].name
                if (w_val > 0.0
                        and name not in appended_joints
                        and name[-5:] != "_mesh"
                        and name in bones_set):          # ← NEW CHECK
                    appended_joints.append(name)
                    weight_total += w_val
                    weight_list.append((name, w_val))

            if weight_total == 0.0:
                weight_total += 1.0
                weight_list.append(('Root', 1.0))
                print("WARNING  Vertex %d in mesh '%s' has no weights to "
                      "any deform bone - defaulting to 'Root'."
                      % (v.index, obj.name))

            normalization = 1.0 / weight_total
            weight_list = [(name, round(e * normalization, 4))
                           for name, e in weight_list]

            for name, w_val in weight_list:
                vindices.append(bones.index(name) if name in bones else 0)
                if w_val not in weights:
                    weights.append(w_val)
                vindices.append(weights.index(w_val))
                vc_val += 1

            vcounts.append(vc_val)

        output['vcounts'] = create_array_dict(1, len(vcounts), vcounts)
        output['weights'] = create_array_dict(1, len(weights), weights)
        output['vindices'] = create_array_dict(1, len(vindices), vindices)

    output['parts'] = {}
    for k, v in parts.items():
        if len(v) > 0:
            output['parts'][k] = create_array_dict(3, len(v) // 3, v)

    # ── clean up the temporary mesh ──
    if apply_modifiers:
        obj_eval.to_mesh_clear()
    else:
        obj.to_mesh_clear()

    return output


def export_armature(obj, export_visible_bones, armature_format='MAT'):
    skipped_bones = []

    def export_bones(b, bone_list, bone_dict,
                     export_visible_bones, armature_format):
        if export_visible_bones and b.hide:
            return None

        # ── FIX: skip non-deform bones (IK targets, pole targets, ──
        # ── constraints, etc.) but still recurse into children so  ──
        # ── deform bones parented under control bones are kept.    ──
        if not b.use_deform:
            skipped_bones.append(b.name)
            promoted = []
            for child in b.children:
                result = export_bones(child, bone_list, OrderedDict(),
                                      export_visible_bones, armature_format)
                if result is not None:
                    if isinstance(result, list):
                        promoted.extend(result)
                    else:
                        promoted.append(result)
            return promoted if promoted else None

        bone_list.append(b.name)

        # ── FIX: compute transform relative to the nearest         ──
        # ── *deform* ancestor, not the direct parent (which may be ──
        # ── a non-deform control bone that was skipped).           ──
        matrix = b.matrix_local
        deform_parent = _find_deform_parent(b)
        if deform_parent is not None:
            matrix = deform_parent.matrix_local.inverted_safe() @ matrix

        bone_dict['name'] = b.name

        if armature_format == 'ATTR':
            bone_dict['transform'] = decompose_to_dict(matrix)
        else:
            bone_dict['transform'] = wrap_matrix(matrix)

        children = []
        for child in b.children:
            result = export_bones(child, bone_list, OrderedDict(),
                                  export_visible_bones, armature_format)
            if result is not None:
                # result may be a dict (deform bone) or a list
                # (promoted children of a skipped non-deform bone)
                if isinstance(result, list):
                    children.extend(result)
                else:
                    children.append(result)
        bone_dict['children'] = children

        return bone_dict

    output = OrderedDict()
    bones = []
    bone_hierarchy = []

    for b in obj.data.bones:
        if b.parent is not None:
            continue
        result = export_bones(b, bones, OrderedDict(),
                              export_visible_bones, armature_format)
        if result is not None:
            if isinstance(result, list):
                bone_hierarchy.extend(result)
            else:
                bone_hierarchy.append(result)

    if skipped_bones:
        print("INFO  Skipped %d non-deform bone(s): %s"
              % (len(skipped_bones), ', '.join(skipped_bones)))

    if not bones:
        raise ExportError(
            "Armature '%s' produced no exportable bones. "
            "If 'Export Only Visible Bones' is checked, make sure at "
            "least some bones are visible. Also ensure your deform "
            "bones have 'Deform' enabled in Bone Properties."
            % obj.name)

    output['joints'] = NoIndent(bones)
    output['hierarchy'] = bone_hierarchy

    return output


def export_animation(obj, bone_name_list, animation_format):
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

    # ── FIX: only process deform bones ──
    deform_bone_names = set(bone_name_list)

    dope_sheet = {}
    timelines = []
    output = []

    fcurves = get_fcurves_from_action(action)

    for curve in fcurves:
        name = get_bone_name_from_fcurve(curve)
        if name is None:
            continue

        # ── FIX: skip fcurves belonging to non-deform bones ──
        if name not in deform_bone_names:
            continue

        if name not in dope_sheet:
            dope_sheet[name] = {'transform': [], 'timestamp': []}

        for keyframe in curve.keyframe_points:
            val = int(keyframe.co[0])
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
            # ── FIX: skip non-deform bones entirely ──
            if not b.use_deform:
                continue

            if b.name not in dope_sheet:
                dope_sheet[b.name] = {'transform': [], 'timestamp': []}

            if (t in dope_sheet[b.name]['timestamp']
                    or t == 0
                    or t == timelines[-1]):

                matrix = obj.pose.bones[b.name].matrix.copy()
                bone_local = b.matrix_local.copy()

                if animation_format == 'ATTR':
                    # ── FIX: use nearest deform ancestor instead of ──
                    # ── direct parent (which may be non-deform)     ──
                    deform_parent = _find_deform_parent(b)
                    if deform_parent is not None:
                        bone_local = (deform_parent.matrix_local
                                      .inverted_safe() @ bone_local)
                        parent_pose_inv = (
                            obj.pose.bones[deform_parent.name]
                               .matrix.inverted_safe())
                        matrix = (bone_local.inverted_safe()
                                  @ parent_pose_inv @ matrix)
                    else:
                        matrix = bone_local.inverted_safe() @ matrix

                    if t not in dope_sheet[b.name]['timestamp']:
                        dope_sheet[b.name]['timestamp'].append(t)

                    dope_sheet[b.name]['transform'].append(
                        decompose_to_dict(matrix))
                else:
                    # ── FIX: same deform-parent logic for MAT format ──
                    deform_parent = _find_deform_parent(b)
                    if deform_parent is not None:
                        parent_pose_inv = (
                            obj.pose.bones[deform_parent.name]
                               .matrix.inverted_safe())
                        matrix = parent_pose_inv @ matrix

                    if t not in dope_sheet[b.name]['timestamp']:
                        dope_sheet[b.name]['timestamp'].append(t)

                    dope_sheet[b.name]['transform'].append(
                        wrap_matrix(matrix))

    for b in bone_name_list:
        if b not in dope_sheet:
            print("WARNING  Bone '%s' has no animation data - skipped." % b)
            continue
        d = OrderedDict()
        d['name'] = b
        d['time'] = NoIndent(
            [round(t / bpy.context.scene.render.fps, 4)
             for t in dope_sheet[b]['timestamp']])
        d['transform'] = dope_sheet[b]['transform']
        output.append(d)

    return output


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

    transform = []
    timestamp = []

    fcurves = get_fcurves_from_action(action)

    kf_names = set()
    has_groups = False
    for fcurve in fcurves:
        name = get_group_name_from_fcurve(fcurve)
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
            % (action.name,
               len(kf_names),
               ', '.join(kf_names) if kf_names else '<none>'))

    for curve in fcurves:
        for keyframe in curve.keyframe_points:
            val = int(keyframe.co[0])
            if val not in timestamp:
                timestamp.append(val)

    timestamp.sort()

    if not timestamp:
        raise ExportError(
            "Camera '%s' action '%s' contains no keyframes."
            % (camera_obj.name, action.name))

    for t in timestamp:
        scene.frame_set(t)
        world_mat = (mathutils.Matrix.Translation(
                         mathutils.Vector((0.0, 0.0, -1.62)))
                     @ camera_obj.matrix_world)

        loc, rot, sca = world_mat.decompose()
        blender_to_mc = mathutils.Quaternion(
            (1.0, 0.0, 0.0), math.radians(-90.0))

        loc.rotate(blender_to_mc)
        rot.rotate(blender_to_mc)

        transformdict = OrderedDict()
        transformdict['loc'] = NoIndent([round(v, 6) for v in loc])
        transformdict['rot'] = NoIndent([round(v, 6) for v in rot])
        transformdict['sca'] = NoIndent([round(v, 6) for v in sca])
        transform.append(transformdict)

    output = OrderedDict()
    output['time'] = NoIndent(
        [round(t / bpy.context.scene.render.fps, 4) for t in timestamp])
    output['transform'] = transform

    return output


def correct_bones_as_vertex_groups(obj, bones, armature_obj=None):
    # ── FIX: also filter out vertex groups that correspond to ──
    # ── non-deform bones so they can't sneak back in.         ──
    deform_names = None
    if armature_obj is not None:
        deform_names = {b.name for b in armature_obj.data.bones
                        if b.use_deform}

    corrected = []
    for vg in obj.vertex_groups:
        name = vg.name
        if name[-5:] != "_mesh" and name != "Clothing":
            if deform_names is None or name in deform_names:
                corrected.append(name)
    return corrected


def save(operator, context, **kwargs):
    file_path = ensure_extension(kwargs['filepath'], ".json")
    output = OrderedDict()

    mesh_obj = armature_obj = camera_obj = None
    mesh_result = armature_result = animation_result = camera_result = None

    export_msh = kwargs.get('export_mesh', True)
    export_armat = kwargs.get('export_armature', True)
    export_anim = kwargs.get('export_anim', True)
    export_cam = kwargs.get('export_camera', False)
    apply_mods = kwargs.get('apply_modifiers', False)
    animation_fmt = kwargs.get('animation_format', 'ATTR')
    armature_fmt = kwargs.get('armature_format', 'MAT')
    visible_bones = kwargs.get('export_only_visible_bones', False)

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
                "No armature object found in the scene. "
                "Armature export skipped.")
            export_armat = False
        if export_anim:
            operator.report(
                {'WARNING'},
                "No armature object found in the scene. "
                "Animation export skipped.")
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
                "No camera object found in the scene. "
                "Add a camera or uncheck 'Export Camera'.")
            return {'CANCELLED'}
        if camera_obj.animation_data is None:
            operator.report(
                {'ERROR'},
                "Camera '%s' has no animation data. "
                "Add keyframes to the camera or uncheck 'Export Camera'."
                % camera_obj.name)
            return {'CANCELLED'}
        if camera_obj.animation_data.action is None:
            operator.report(
                {'ERROR'},
                "Camera '%s' has no active action. "
                "Assign an action or uncheck 'Export Camera'."
                % camera_obj.name)
            return {'CANCELLED'}

    # ── Report skipped non-deform bones early so users see the info ──
    non_deform_bones = []
    if armature_obj is not None:
        non_deform_bones = [b.name for b in armature_obj.data.bones
                            if not b.use_deform]
        if non_deform_bones:
            operator.report(
                {'INFO'},
                "Skipping %d non-deform bone(s) "
                "(IK targets, constraints, etc.): %s"
                % (len(non_deform_bones), ', '.join(non_deform_bones)))

    if armature_obj is not None:
        try:
            armature_result = export_armature(
                armature_obj, visible_bones, armature_fmt)
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
                    animation_fmt)
            except ExportError as e:
                operator.report({'ERROR'}, str(e))
                return {'CANCELLED'}
            except Exception as e:
                traceback.print_exc()
                operator.report(
                    {'ERROR'},
                    "Unexpected error exporting animation: %s" % str(e))
                return {'CANCELLED'}

    if mesh_obj is not None:
        if armature_result is not None:
            # ── FIX: pass armature_obj so non-deform vertex ──
            # ── groups are filtered out                      ──
            armature_result['joints'].value = \
                correct_bones_as_vertex_groups(
                    mesh_obj, armature_result['joints'].value,
                    armature_obj)

        if export_msh:
            try:
                mesh_result = export_mesh(
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
        if armature_fmt == 'ATTR':
            output['armature_format'] = 'attributes'
        output['armature'] = armature_result

    if animation_result is not None and export_anim:
        if animation_fmt == 'ATTR':
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
