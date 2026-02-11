import mathutils
import bpy
import bmesh
from . import utils

def create_export_list(collection, exportHiddenObjects, useNamesFrom):
    export_list = []

    if(collection.hide_viewport):
        return export_list

    for object in collection.objects:
        if(object.type == 'MESH' and (object.hide_viewport == False or exportHiddenObjects)):
            if useNamesFrom == 'OBJECT':
                object.data.name = object.name

            export_list.append(object)

    for child in collection.children:
        export_list.extend(create_export_list(child, exportHiddenObjects, useNamesFrom))

    return export_list

def selectNonManifoldVertices(object):
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    object.hide_set(False)
    bpy.context.view_layer.objects.active = object
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='DESELECT')
    bpy.ops.mesh.select_non_manifold()

# checks if shadow meshes are correct and checks if material is missing
def checkShadowMesh(object):
    error = []
    if len(object.data.materials) > 0:
        shader = object.data.materials[0].shaderList.shaderList
        if shader in ['MeshShadowVolume.fx', 'RSkinShadowVolume.fx']:
            bm = bmesh.new()  # create an empty BMesh
            bm.from_mesh(object.data)  # fill it in from a Mesh
            bm.verts.ensure_lookup_table()

            for vertex in bm.verts:
                if not vertex.is_manifold:
                    # bm.free()
                    selectNonManifoldVertices(object)
                    error += [({'ERROR'}, f'ALAMO - Non manifold geometry shadow mesh: {object.name}')]
                    break

            for edge in bm.edges:
                if len(edge.link_faces) < 2:
                    # bm.free()
                    selectNonManifoldVertices(object)
                    error += [({'ERROR'}, f'ALAMO - Non manifold geometry shadow mesh: {object.name}')]
                    break

            bm.free()
    else:
        error += [({'ERROR'}, f'ALAMO - Missing material on object: {object.name}')]

    return error

def checkUV(object):  # throws error if object lacks UVs
    error = []
    for material in object.data.materials:
        if material.shaderList.shaderList == 'MeshShadowVolume.fx' or material.shaderList.shaderList == 'RSkinShadowVolume.fx':
            if len(object.data.materials) > 1:
                error += [({'ERROR'}, f'ALAMO - Multiple materials on shadow volume: {object.name}; remove additional materials')]
        if object.HasCollision:
            if len(object.data.materials) > 1:
                error += [({'ERROR'}, f'ALAMO - Multiple submeshes/materials on collision mesh: {object.name}; remove additional materials')]
    if not object.data.uv_layers:  # or material.shaderList.shaderList in settings.no_UV_Shaders:  #currently UVs are needed for everything but shadows
        error += [({'ERROR'}, f'ALAMO - Missing UV: {object.name}')]

    return error

# throws error if armature modifier lacks rig, this would crash the exporter later and checks if skeleton in modifier doesn't match active skeleton
def checkInvalidArmatureModifier(object):
    activeSkeleton = bpy.context.scene.ActiveSkeleton.skeletonEnum
    error = []
    for modifier in object.modifiers:
        if modifier.type == "ARMATURE":
            if modifier.object is None:
                error += [({'ERROR'}, f'ALAMO - Armature modifier without selected skeleton on: {object.name}')]
                break
            elif modifier.object.type != 'NoneType':
                if modifier.object.name != activeSkeleton:
                    error += [({'ERROR'}, f"ALAMO - Armature modifier skeleton doesn't match active skeleton on: {object.name}")]
                    break
    for constraint in object.constraints:
        if (
            constraint.type == 'CHILD_OF'
            and constraint.target is not None
            and constraint.target.name != activeSkeleton
        ):
            error += [({'ERROR'}, f"ALAMO - Constraint doesn't match active skeleton on: {object.name}")]
            break

    return error

# checks if the number of faces exceeds max ushort, which is used to save the indices
def checkFaceNumber(object):
    #if len(object.data.polygons) > 65535:
    #    return [({'ERROR'}, f'ALAMO - {object.name} exceeds maximum face limit; split mesh into multiple objects')]
    if len(object.data.loops) > 65535:
        return [({'ERROR'}, f'ALAMO - {object.name} exceeds maximum face limit 65535; split mesh into multiple objects; loop count = {len(object.data.loops)}')]
    elif len(object.data.loops) > 60000:
        return [({'WARNING'}, f'ALAMO - {object.name} close to maximum face limit 65535; split mesh into multiple objects; loop count = {len(object.data.loops)}')]
    return []

def checkAutosmooth(object):  # prints a warning if Autosmooth is used
    # Blender 4.1+ Compatibility: use_auto_smooth and auto_smooth_angle were removed.
    # They are replaced by the "Smooth by Angle" modifier (NODES type).
    has_autosmooth = getattr(object.data, 'use_auto_smooth', False)
    
    if not has_autosmooth:
        # Check for the modern "Smooth by Angle" modifier in Blender 4.1+
        for mod in object.modifiers:
            if mod.type == 'NODES' and mod.name == "Smooth by Angle":
                has_autosmooth = True
                break

    if has_autosmooth:
        return [({'ERROR'}, f'ALAMO - {object.name} uses autosmooth, ingame shading might not match blender; use edgesplit instead')]
    return []

def checkTranslation(object):  # prints warning when translation is not default
    if object.location != mathutils.Vector((0.0, 0.0, 0.0)) or object.rotation_euler != mathutils.Euler((0.0, 0.0, 0.0), 'XYZ'):
        return [({'ERROR'}, f'ALAMO - {object.name} is not aligned with the world origin; apply translation or bind to bone')]
    return []

def checkScale(object):  # prints warning when scale is not default
    if object.scale != mathutils.Vector((1.0, 1.0, 1.0)):
        return [({'ERROR'}, f'ALAMO - {object.name} has non-identity scale. Apply scale.')]
    return []

# checks if vertices have 0 or > 1 groups
def checkVertexGroups(object):
    if object.vertex_groups is None or len(object.vertex_groups) == 0:
        return []
    for vertex in object.data.vertices:
        total = 0
        for group in vertex.groups:
            if group.weight not in [0, 1]:
                return [({'ERROR'}, f'ALAMO - Object {object.name} has improper vertex groups')]
            total += group.weight
        if total not in [0, 1]:
            return [({'ERROR'}, f'ALAMO - Object {object.name} has improper vertex groups')]

    return []

def checkNumBones(object):
    if type(object) != type(None) and object.type == 'MESH':
        material = object.active_material
        if material is not None and material.shaderList.shaderList.find("RSkin") > -1:
            used_groups = []
            for vertex in object.data.vertices:
                for group in vertex.groups:
                    if group.weight == 1:
                        used_groups.append(group.group)

            if len(set(used_groups)) > 23:
                return [({'ERROR'}, f'ALAMO - Object {object.name} has more than 23 bones.')]
    return []

def checkTranslationArmature():  # prints warning when translation is not default
    armature = utils.findArmature()
    if armature is not None:
        if (
            armature.location != mathutils.Vector((0.0, 0.0, 0.0))
            or armature.rotation_euler != mathutils.Euler((0.0, 0.0, 0.0), 'XYZ')
            or armature.scale != mathutils.Vector((1.0, 1.0, 1.0))
        ):
            return [({'ERROR'}, f'ALAMO - Armature {armature.name} is not aligned with the world origin; apply translation')]
    return []

def checkBoneNames():
    error = []
    armature = utils.findArmature()
    if armature is not None:
        for bone in armature.data.bones:
            if len(bone.name) > 63:
                error += [({'ERROR'}, f'ALAMO - Bone name too long (> 63 chars): {bone.name}')]
            if not bone.name.isascii():
                error += [({'ERROR'}, f'ALAMO - Bone name contains non-ASCII characters: {bone.name}')]
    return error

def checkBoneCount():
    armature = utils.findArmature()
    if armature is not None:
        # EaW has a limit of 256 bones in the ALO skeleton chunk
        if len(armature.data.bones) > 255: # 255 because we might add a Root bone
            return [({'ERROR'}, f'ALAMO - Armature {armature.name} has too many bones ({len(armature.data.bones)}); maximum is 255')]
    return []

def checkActiveSkeleton(mesh_list):
    activeSkeleton = bpy.context.scene.ActiveSkeleton.skeletonEnum
    if activeSkeleton == 'None':
        for object in mesh_list:
            for modifier in object.modifiers:
                if modifier.type == "ARMATURE" and modifier.object is not None:
                    return [({'ERROR'}, 'ALAMO - Active Skeleton is set to None, but meshes have armature modifiers. Please select the active skeleton in the Sidebar.')]
    return []

def checkProxyKeyframes():
    local_errors = []
    actions = bpy.data.actions
    current_frame = bpy.context.scene.frame_current
    armature = utils.findArmature()
    if armature is not None:
        for action in actions:
            print(action.name)
            for fcurve in action.fcurves:
                if fcurve.data_path.find("proxyIsHiddenAnimation") > -1:
                    group_name = fcurve.group.name if fcurve.group else "Proxy"
                    previous_keyframe = None
                    for keyframe in fcurve.keyframe_points:
                        bpy.context.scene.frame_set(int(keyframe.co[0]))
                        # Note: this resolution depends on the current armature state, not necessarily the action values
                        # until we set the action on the armature.
                        try:
                            this_keyframe = armature.path_resolve(fcurve.data_path)
                            if this_keyframe == previous_keyframe:
                                local_errors += [({'WARNING'}, f'ALAMO - {group_name} has duplicate keyframe on frame {bpy.context.scene.frame_current}')]
                            previous_keyframe = this_keyframe
                        except:
                            pass
    bpy.context.scene.frame_set(current_frame)
    return local_errors

def validate(mesh_list):
    errors = []
    checklist = [
        checkShadowMesh,
        checkUV,
        checkFaceNumber,
        checkAutosmooth,
        checkTranslation,
        checkInvalidArmatureModifier,
        checkScale,
        checkVertexGroups,
        checkNumBones,
    ]
    checklist_no_object = [
        checkTranslationArmature,
        checkBoneNames,
        checkBoneCount,
        # checkProxyKeyframes, # Disabled until it can be fixed
    ]

    for check in checklist:
        for object in mesh_list:
            errors += check(object)
    
    errors += checkActiveSkeleton(mesh_list)
    
    for check in checklist_no_object:
        errors += check()

    return errors
