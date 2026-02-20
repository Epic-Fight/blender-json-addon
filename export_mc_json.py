from collections import OrderedDict

import bmesh
import bpy
from . import compat


def _acquire_mesh(obj, apply_modifiers):
    """Return (mesh, cleanup_callable)."""
    if compat.IS_LEGACY:
        # 2.79: to_mesh(scene, apply_modifiers, settings, …)
        mesh = obj.to_mesh(
            bpy.context.scene, apply_modifiers,
            calc_tessface=False, settings='PREVIEW')
        return mesh, lambda: None

    # 2.80+
    if apply_modifiers:
        depsgraph = bpy.context.evaluated_depsgraph_get()
        obj_eval = obj.evaluated_get(depsgraph)
        try:
            mesh = obj_eval.to_mesh(preserve_all_data_layers=True,
                                    depsgraph=depsgraph)
        except TypeError:
            mesh = obj_eval.to_mesh()
        return mesh, obj_eval.to_mesh_clear

    try:
        mesh = obj.to_mesh(preserve_all_data_layers=True)
    except TypeError:
        mesh = obj.to_mesh()
    return mesh, obj.to_mesh_clear


def _mesh_triangulate(mesh):
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.triangulate(bm, faces=bm.faces)
    bm.to_mesh(mesh)
    bm.free()


def export_mesh(obj, bones, apply_modifiers=False):
    mesh, cleanup = _acquire_mesh(obj, apply_modifiers)

    try:
        # snapshot polygon topology before triangulation
        original_poly_verts = [list(p.vertices) for p in mesh.polygons]

        _mesh_triangulate(mesh)

        if hasattr(mesh, 'calc_normals_split'):
            mesh.calc_normals_split()

        # match each triangulated face back to its original polygon
        owner_polygon_indices = {}
        for f in mesh.polygons:
            tri_verts = set(f.vertices)
            owners = [i for i, ov in enumerate(original_poly_verts)
                      if tri_verts.issubset(set(ov))]

            if len(owners) != 1:
                raise compat.ExportError(
                    "Triangulation error: a triangulated face could not "
                    "be matched to exactly one original polygon. "
                    "Check the mesh '%s' for overlapping or degenerate "
                    "faces." % obj.name)

            owner_polygon_indices[f.index] = owners[0]

        position_array = [round(pos, 6)
                          for v in mesh.vertices
                          for pos in v.co[:]]

        # deduplicate normals
        normal_array = []
        loops = mesh.loops
        no_unique_count = 0
        normals_to_idx = {}
        no_get = normals_to_idx.get
        loops_to_normals = [0] * len(loops)

        for f in mesh.polygons:
            for l_idx in f.loop_indices:
                no_key = compat.veckey3d(loops[l_idx].normal)
                no_val = no_get(no_key)
                if no_val is None:
                    no_val = normals_to_idx[no_key] = no_unique_count
                    for n_val in no_key:
                        normal_array.append(n_val)
                    no_unique_count += 1
                loops_to_normals[l_idx] = no_val

        del normals_to_idx, no_get

        # deduplicate UVs
        uv_layer_active = mesh.uv_layers.active
        if uv_layer_active is None:
            raise compat.ExportError(
                "Mesh '%s' has no active UV layer. "
                "Unwrap the mesh before exporting." % obj.name)
        uv_layer = uv_layer_active.data[:]

        uv_array = []
        uv_unique_count = 0
        uv_face_mapping = [None] * len(mesh.polygons)
        uv_dict = {}
        uv_get = uv_dict.get

        for f_index, f in enumerate(mesh.polygons):
            uv_ls = uv_face_mapping[f_index] = []
            for uv_index, l_index in enumerate(f.loop_indices):
                uv = uv_layer[l_index].uv
                uv_key = compat.veckey2d(uv)
                uv_val = uv_get(uv_key)
                if uv_val is None:
                    uv_val = uv_dict[uv_key] = uv_unique_count
                    for i, uv_cor in enumerate(uv):
                        uv_array.append(
                            round(uv_cor if i % 2 == 0
                                  else 1 - uv_cor, 6))
                    uv_unique_count += 1
                uv_ls.append(uv_val)

        del uv_dict

        # assign faces to _mesh vertex group parts
        parts = {'noGroups': []}
        for vg in obj.vertex_groups:
            if vg.name.endswith("_mesh"):
                parts[vg.name[:-5]] = []

        for f_index, f in enumerate(mesh.polygons):
            f_v = [(vi, mesh.vertices[v_idx], l_idx)
                   for vi, (v_idx, l_idx)
                   in enumerate(zip(f.vertices, f.loop_indices))]

            polygons_part_indices = {name: [] for name in parts}

            for vi, v, li in f_v:
                mesh_vgs = [
                    obj.vertex_groups[vg.group].name
                    for vg in v.groups
                    if (vg.group < len(obj.vertex_groups)
                        and obj.vertex_groups[vg.group].name.endswith(
                            "_mesh"))]

                if not mesh_vgs:
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
                if len(i_list) // 3 != len(f.vertices):
                    continue

                orig_verts = original_poly_verts[
                    owner_polygon_indices[f.index]]
                vg_names = [
                    [obj.vertex_groups[vg.group].name[:-5]
                     for vg in vert.groups
                     if (vg.group < len(obj.vertex_groups)
                         and obj.vertex_groups[vg.group].name.endswith(
                             '_mesh'))]
                    for vert in (mesh.vertices[vid]
                                 for vid in orig_verts)]

                if part_name == 'noGroups':
                    if all(len(names) == 0 for names in vg_names):
                        parts[part_name].extend(i_list)
                else:
                    if all(part_name in names for names in vg_names):
                        parts[part_name].extend(i_list)

        output = OrderedDict()
        output['positions'] = compat.create_array_dict(
            3, len(position_array) // 3, position_array)
        output['uvs'] = compat.create_array_dict(
            2, len(uv_array) // 2, uv_array)
        output['normals'] = compat.create_array_dict(
            3, len(normal_array) // 3, normal_array)

        # vertex weights
        if bones is not None:
            bones_set = set(bones)
            vcounts = []
            weights = []
            vindices = []

            for v in mesh.vertices:
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
                            and not name.endswith("_mesh")
                            and name in bones_set):
                        appended_joints.append(name)
                        weight_total += w_val
                        weight_list.append((name, w_val))

                if weight_total == 0.0:
                    weight_total += 1.0
                    weight_list.append(('Root', 1.0))
                    print("WARNING  Vertex %d in mesh '%s' has no "
                          "weights to any deform bone — defaulting "
                          "to 'Root'." % (v.index, obj.name))

                normalization = 1.0 / weight_total
                weight_list = [(n, round(e * normalization, 4))
                               for n, e in weight_list]

                for name, w_val in weight_list:
                    vindices.append(
                        bones.index(name) if name in bones else 0)
                    if w_val not in weights:
                        weights.append(w_val)
                    vindices.append(weights.index(w_val))
                    vc_val += 1

                vcounts.append(vc_val)

            output['vcounts'] = compat.create_array_dict(
                1, len(vcounts), vcounts)
            output['weights'] = compat.create_array_dict(
                1, len(weights), weights)
            output['vindices'] = compat.create_array_dict(
                1, len(vindices), vindices)

        output['parts'] = {}
        for k, v in parts.items():
            if v:
                output['parts'][k] = compat.create_array_dict(
                    3, len(v) // 3, v)

        return output

    finally:
        cleanup()


def save(operator, context, **kwargs):
    return compat.save_common(operator, context, export_mesh, **kwargs)