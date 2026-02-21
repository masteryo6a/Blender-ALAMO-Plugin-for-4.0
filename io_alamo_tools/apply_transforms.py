import bpy
import bmesh


def apply_transforms_to_objects(objects):
    """
    Apply location and scale transforms to mesh and armature objects.
    """
    if not objects:
        return 0, 0
    
    # Step 0: Make mesh objects single user (Armatures usually don't need this for simple transforms)
    for obj in objects:
        if obj.type == 'MESH' and obj.data.users > 1:
            obj.data = obj.data.copy()
    
    # Step 1: Track negative scale only for Meshes (to fix normals)
    negative_scale_meshes = [obj for obj in objects if obj.type == 'MESH' and (obj.scale.x < 0 or obj.scale.y < 0 or obj.scale.z < 0)]
    
    processed_count = 0
    
    # Step 2: Apply transforms to everything in the list (Mesh + Armature)
    for obj in objects:
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        
        # Apply location and scale
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        processed_count += 1
    
    # Step 3: Flip normals ONLY for the meshes that had negative scale
    flipped_count = 0
    for obj in negative_scale_meshes:
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.flip_normals()
        bpy.ops.object.mode_set(mode='OBJECT')
        flipped_count += 1
    
    return processed_count, flipped_count

def apply_transforms_to_selected():
    # Updated filter to include 'ARMATURE'
    selected_targets = [obj for obj in bpy.context.selected_objects if obj.type in {'MESH', 'ARMATURE'}]
    return apply_transforms_to_objects(selected_targets)


def apply_transforms_to_collection(collection, recursive=True):
    """
    Apply transforms to all mesh objects in a collection.
    
    Args:
        collection: The collection to process
        recursive: If True, also process objects in child collections
        
    Returns:
        Tuple of (processed_count, flipped_normals_count)
    """
    objects = []
    
    # Get objects from this collection
    for obj in collection.objects:
        if obj.type == 'MESH':
            objects.append(obj)
    
    # Recursively get objects from child collections
    if recursive:
        for child_collection in collection.children:
            child_objects = []
            for obj in child_collection.objects:
                if obj.type == 'MESH':
                    child_objects.append(obj)
            objects.extend(child_objects)
    
    return apply_transforms_to_objects(objects)