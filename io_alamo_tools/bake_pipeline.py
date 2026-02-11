import bpy
import os
import subprocess
import ctypes
import numpy as np
from . import settings, utils

def prepare_object_for_bake(obj, uv_name="ALAMO_BAKE", resolution=1024):
    """Creates a copy of the object and adds a new UV map for baking (single object mode)."""
    # Deselect all
    bpy.ops.object.select_all(action='DESELECT')
    
    # Copy object
    new_obj = obj.copy()
    new_obj.data = obj.data.copy()
    bpy.context.collection.objects.link(new_obj)
    new_obj.select_set(True)
    bpy.context.view_layer.objects.active = new_obj
    
    # Create new UV map
    if uv_name not in new_obj.data.uv_layers:
        new_obj.data.uv_layers.new(name=uv_name)
    
    new_obj.data.uv_layers[uv_name].active = True
    
    # Smart Project UVs then pack for efficiency
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(island_margin=0.0)
    
    # Pack islands with resolution-aware margin (2 pixels of padding)
    margin = 2.0 / resolution
    bpy.ops.uv.pack_islands(margin=margin, rotate=True)
    
    bpy.ops.object.mode_set(mode='OBJECT')
    
    return new_obj

def prepare_objects_for_bake(objects, uv_name="ALAMO_BAKE_ATLAS", resolution=1024):
    """
    Joins multiple objects into a single mesh with unified UV atlas.
    Returns: (joined_object, metadata_for_separation)
    """
    if len(objects) == 1:
        # Single object - use existing workflow with proper resolution
        return prepare_object_for_bake(objects[0], uv_name, resolution), None
    
    # Deselect all
    bpy.ops.object.select_all(action='DESELECT')
    
    # Store metadata for each object
    metadata = []
    duplicates = []
    
    for obj in objects:
        # Duplicate object
        new_obj = obj.copy()
        new_obj.data = obj.data.copy()
        bpy.context.collection.objects.link(new_obj)
        new_obj.select_set(True)
        duplicates.append(new_obj)
        
        # Store metadata
        metadata.append({
            'original_name': obj.name,
            'duplicate': new_obj,
            'vertex_count': len(new_obj.data.vertices)
        })
    
    # Set active object to first duplicate
    bpy.context.view_layer.objects.active = duplicates[0]
    
    # Join all duplicates into one
    bpy.ops.object.join()
    joined_obj = bpy.context.active_object
    
    # Create new UV map for atlas
    if uv_name not in joined_obj.data.uv_layers:
        joined_obj.data.uv_layers.new(name=uv_name)
    
    joined_obj.data.uv_layers[uv_name].active = True
    
    # Generate UVs and pack efficiently for atlas
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    
    # First unwrap with Smart UV Project (creates islands)
    bpy.ops.uv.smart_project(island_margin=0.0)
    
    # Then use Pack Islands for efficient space usage
    # Calculate margin based on resolution: 2 pixels of padding
    # margin = pixels / resolution
    margin = 2.0 / resolution
    
    # Pack islands to maximize space usage
    bpy.ops.uv.pack_islands(margin=margin, rotate=True)
    
    bpy.ops.object.mode_set(mode='OBJECT')
    
    return joined_obj, metadata

def separate_baked_meshes(joined_obj, metadata, uv_name="ALAMO_BAKE_ATLAS"):
    """
    Separates the joined object back into individual meshes.
    Removes old UV maps, keeping only the baked atlas UV.
    Returns: list of separated objects
    """
    if metadata is None:
        # Single object mode - remove old UV maps
        mesh = joined_obj.data
        uv_layers_to_remove = [uv for uv in mesh.uv_layers if uv.name != uv_name]
        for uv in uv_layers_to_remove:
            mesh.uv_layers.remove(uv)
        return [joined_obj]
    
    # Select the joined object
    bpy.ops.object.select_all(action='DESELECT')
    joined_obj.select_set(True)
    bpy.context.view_layer.objects.active = joined_obj
    
    # Separate by loose parts
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.separate(type='LOOSE')
    bpy.ops.object.mode_set(mode='OBJECT')
    
    # Get all separated objects
    separated_objs = [obj for obj in bpy.context.selected_objects if obj.type == 'MESH']
    
    # Try to match original names based on vertex count
    # This is a heuristic - may need refinement for complex cases
    for obj in separated_objs:
        vertex_count = len(obj.data.vertices)
        for meta in metadata:
            if abs(meta['vertex_count'] - vertex_count) < 5:  # Tolerance for triangulation
                obj.name = meta['original_name'] + "_Baked"
                break
        
        # Remove old UV maps, keep only the baked atlas UV
        mesh = obj.data
        uv_layers_to_remove = [uv for uv in mesh.uv_layers if uv.name != uv_name]
        for uv in uv_layers_to_remove:
            mesh.uv_layers.remove(uv)
    
    return separated_objs

def setup_baking_material(obj, resolution=(1024, 1024)):
    """Sets up temporary baking image nodes in all materials of the object."""
    images = {}
    
    # Map bake types to texture parameter names
    bake_map = {
        'DIFFUSE': 'BaseTexture',
        'NORMAL': 'NormalTexture'
    }
    
    for bake_type, param_name in bake_map.items():
        image_name = f"{obj.name}_{param_name}"
        if image_name in bpy.data.images:
            bpy.data.images.remove(bpy.data.images[image_name])
        
        image = bpy.data.images.new(image_name, width=resolution[0], height=resolution[1], alpha=True)
        images[bake_type] = image

    # Ensure object has materials
    if not obj.data.materials:
        mat = bpy.data.materials.new(name="BakeTemp")
        obj.data.materials.append(mat)
    
    for mat in obj.data.materials:
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        
        # We need to bake one at a time, so we just prepare the nodes
        for bake_type, image in images.items():
            node_name = f"BAKE_{bake_type}"
            if node_name in nodes:
                nodes.remove(nodes[node_name])
            
            bake_node = nodes.new('ShaderNodeTexImage')
            bake_node.name = node_name
            bake_node.image = image
            bake_node.select = False # Will select during bake_pass
        
    return images

def bake_pass(obj, bake_type='DIFFUSE', image=None, save_path=None):
    """Executes the bake operation for the specified type."""
    bpy.context.view_layer.objects.active = obj
    
    # 1. Select the correct bake node in all materials
    for mat in obj.data.materials:
        if not mat.use_nodes: continue
        nodes = mat.node_tree.nodes
        node_name = f"BAKE_{bake_type}"
        if node_name in nodes:
            for n in nodes: n.select = False
            nodes[node_name].select = True
            nodes.active = nodes[node_name]

    # 2. Cycles setup
    original_engine = bpy.context.scene.render.engine
    bpy.context.scene.render.engine = 'CYCLES'
    
    # Set bake settings
    bpy.context.scene.cycles.bake_type = bake_type
    if bake_type == 'DIFFUSE':
        bpy.context.scene.render.bake.use_pass_direct = False
        bpy.context.scene.render.bake.use_pass_indirect = False
        bpy.context.scene.render.bake.use_pass_color = True
    elif bake_type == 'NORMAL':
        # Default settings are usually fine for tangent space normals
        pass
    
    # Perform Bake
    try:
        bpy.ops.object.bake(type=bake_type)
    except Exception as e:
        print(f"Bake failed: {e}")
        bpy.context.scene.render.engine = original_engine
        return None
    
    # Restore engine
    bpy.context.scene.render.engine = original_engine
    
    if image and save_path:
        # Save image
        image.filepath_raw = save_path
        image.file_format = 'PNG' 
        image.save()
        return image
    return image

def process_alpha_channel(image, alpha_mode='CONSTANT', alpha_value=255):
    """
    Process the alpha channel of a baked image.
    
    Args:
        image: Blender image object
        alpha_mode: 'CONSTANT', 'EXTRACT_SATURATION', or 'PRESERVE'
        alpha_value: Integer 0-255, alpha value for CONSTANT mode
    """
    if alpha_mode == 'EXTRACT_SATURATION':
        # Extract saturation to alpha and desaturate the RGB
        pixels = np.array(image.pixels[:]).reshape((image.size[1], image.size[0], 4))
        
        # Convert to HSV to get saturation
        for y in range(image.size[1]):
            for x in range(image.size[0]):
                r, g, b, a = pixels[y, x]
                
                # Calculate saturation
                max_c = max(r, g, b)
                min_c = min(r, g, b)
                
                if max_c > 0:
                    saturation = (max_c - min_c) / max_c
                else:
                    saturation = 0
                
                # Store saturation in alpha (for team colorization)
                # Binary: either 0 (not colorable) or 1.0 (fully colorable)
                # Use threshold of 0.1 to determine if pixel has color
                if saturation > 0.1:
                    pixels[y, x, 3] = 1.0  # Will become 255 in DDS
                else:
                    pixels[y, x, 3] = 0.0  # Will become 0 in DDS
                
                # Convert RGB to grayscale (preserve luminosity)
                gray = 0.299 * r + 0.587 * g + 0.114 * b
                pixels[y, x, 0] = gray
                pixels[y, x, 1] = gray
                pixels[y, x, 2] = gray
        
        # Write back to image
        image.pixels[:] = pixels.flatten()
        
    elif alpha_mode == 'CONSTANT':
        # Set constant alpha value (0-255)
        # Convert to 0.0-1.0 range for Blender
        alpha_normalized = alpha_value / 255.0
        pixels = np.array(image.pixels[:]).reshape((image.size[1], image.size[0], 4))
        pixels[:, :, 3] = alpha_normalized
        image.pixels[:] = pixels.flatten()
        
    # PRESERVE mode does nothing, keeps original alpha

def create_baked_material_shared(objects, texture_results, shader_name="MeshGloss.fx"):
    """
    Creates a single material for all baked objects and sets Alamo properties.
    Also creates Blender preview material.
    """
    # Determine base name from first object
    base_name = objects[0].name.replace("_Baked", "")
    if len(objects) > 1:
        mat_name = f"{base_name}_Atlas_Baked"
    else:
        mat_name = f"{base_name}_Baked"
    
    if mat_name in bpy.data.materials:
        mat = bpy.data.materials[mat_name]
    else:
        mat = bpy.data.materials.new(name=mat_name)
    
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    # Alamo Shader List
    mat.shaderList.shaderList = shader_name
    
    # Create standard Blender nodes for viewport preview
    node_output = nodes.new(type='ShaderNodeOutputMaterial')
    node_bsdf = nodes.new(type='ShaderNodeBsdfPrincipled')
    links.new(node_bsdf.outputs['BSDF'], node_output.inputs['Surface'])
    
    # Set texture properties and Blender nodes
    for param_name, tex_path in texture_results.items():
        base_name_tex = os.path.splitext(tex_path)[0]
        # In Alamo properties, always use .dds
        setattr(mat, param_name, base_name_tex + ".dds")
        
        # For viewport, load the DDS if it exists, otherwise PNG
        img = None
        dds_name = base_name_tex + ".dds"
        png_name = base_name_tex + ".png"
        
        if dds_name in bpy.data.images:
            img = bpy.data.images[dds_name]
        elif png_name in bpy.data.images:
            img = bpy.data.images[png_name]
        elif tex_path in bpy.data.images:
            img = bpy.data.images[tex_path]
        
        if img:
            tex_node = nodes.new('ShaderNodeTexImage')
            tex_node.image = img
            
            if param_name == 'BaseTexture':
                # Set alpha mode to None for proper display
                img.alpha_mode = 'NONE'
                
                # Connect only color, not alpha
                links.new(tex_node.outputs['Color'], node_bsdf.inputs['Base Color'])
            elif param_name == 'NormalTexture':
                normal_map = nodes.new('ShaderNodeNormalMap')
                links.new(tex_node.outputs['Color'], normal_map.inputs['Color'])
                links.new(normal_map.outputs['Normal'], node_bsdf.inputs['Normal'])
                img.colorspace_settings.name = 'Non-Color'

    # Assign to all objects
    for obj in objects:
        obj.data.materials.clear()
        obj.data.materials.append(mat)
    
    return mat

def create_baked_material(obj, texture_results, shader_name="MeshGloss.fx"):
    """Wrapper for backward compatibility - single object mode."""
    return create_baked_material_shared([obj], texture_results, shader_name)

def find_texconv_tool(context=None):
    """Attempts to find texconv.dll or texconv.exe in common locations."""
    # 1. Check if user provided an override in scene
    # Using context.scene is safer during draw() calls
    if context is None:
        context = getattr(bpy, "context", None)
        
    if context and hasattr(context, "scene"):
        props = context.scene
        if hasattr(props, "alamo_texconv_path") and props.alamo_texconv_path:
            path = bpy.path.abspath(props.alamo_texconv_path)
            if os.path.exists(path):
                return path

    # 2. Try to find the blender_dds_addon DLL
    appdata = os.getenv('APPDATA')
    if appdata:
        # Common paths for Blender 4.0 addons
        addon_paths = [
            os.path.join(appdata, "Blender Foundation", "Blender", "4.0", "scripts", "addons", "blender_dds_addon", "directx", "texconv.dll"),
            os.path.join(appdata, "Blender Foundation", "Blender", "4.0", "scripts", "addons", "blender-dds-addon", "directx", "texconv.dll"),
        ]
        for p in addon_paths:
            if os.path.exists(p):
                return p
    
    return None

class Texconv:
    """Wrapper for Microsoft's Texconv (DLL or EXE)."""
    def __init__(self, path=None):
        self.path = path or find_texconv_tool()
        self.is_dll = self.path and self.path.lower().endswith(".dll")
        self._dll = None
        
        if self.is_dll:
            try:
                self._dll = ctypes.cdll.LoadLibrary(self.path)
            except Exception as e:
                print(f"Failed to load Texconv DLL: {e}")
                self.is_dll = False

    def convert(self, input_path, output_path, dds_format='BC1_UNORM', verbose=False, use_alpha_flag=False, use_sepalpha=False, mipmap_levels=0):
        """Converts an image to DDS with proper flags for Alamo engine."""
        if not self.path:
            return False
            
        if self.is_dll and self._dll:
            return self._convert_dll(input_path, output_path, dds_format, verbose, use_alpha_flag, use_sepalpha, mipmap_levels)
        else:
            return self._convert_exe(input_path, output_path, dds_format, verbose, use_alpha_flag, use_sepalpha, mipmap_levels)

    def _convert_dll(self, input_path, output_path, dds_format, verbose, use_alpha_flag, use_sepalpha, mipmap_levels):
        """Internal DLL call via ctypes (matches blender_dds_addon signature)."""
        output_dir = os.path.dirname(output_path)
        
        # Build arguments
        # -f: format, -y: overwrite, -o: output directory
        args = ["-f", dds_format, "-y", "-o", output_dir]
        
        # Mipmap control
        # texconv defaults to generating ALL mipmaps (0)
        # Use -m 1 to disable mipmaps completely
        if mipmap_levels == 1:
            args.extend(["-m", "1"])  # No mipmaps
        elif mipmap_levels > 1:
            args.extend(["-m", str(mipmap_levels)])  # Specific number
        # If 0 or not specified, texconv generates all mipmaps by default
        
        # -sepalpha: Prevents RGB from being zeroed behind transparent pixels
        # This is CRITICAL for BC3 with alpha channel
        # Without this, mipmaps will have black RGB where alpha=0
        if use_sepalpha:
            args.extend(["-sepalpha"])
        
        # -alpha: For BC1 1-bit alpha mode
        # Only use for BC1, not BC3
        if use_alpha_flag:
            args.extend(["-alpha"])
        
        # Important: Never use sRGB formats - EaW handles gamma itself
        args.extend(["--", input_path])
        
        try:
            args_p = (ctypes.c_wchar_p * len(args))(*args)
            err_buf = ctypes.create_unicode_buffer(512)
            # blender_dds_addon DLL signature
            result = self._dll.texconv(len(args), args_p, verbose, False, True, err_buf, 512)
            if result == 0:
                # Find what it created. Texconv uses input filename for output.
                created_dds = os.path.splitext(input_path)[0] + ".dds"
                if os.path.exists(created_dds) and created_dds != output_path:
                    if os.path.exists(output_path):
                        os.remove(output_path)
                    os.rename(created_dds, output_path)
                return True
            else:
                print(f"Texconv DLL Error: {err_buf.value}")
                return False
        except Exception as e:
            print(f"Texconv DLL Invocation Exception: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _convert_exe(self, input_path, output_path, dds_format, verbose, use_alpha_flag, use_sepalpha, mipmap_levels):
        """Fallback to subprocess for standalone texconv.exe."""
        output_dir = os.path.dirname(output_path)
        
        # Build command
        cmd = [self.path, "-f", dds_format, "-y", "-o", output_dir]
        
        # Mipmap control
        if mipmap_levels == 1:
            cmd.extend(["-m", "1"])  # No mipmaps
        elif mipmap_levels > 1:
            cmd.extend(["-m", str(mipmap_levels)])
        # If 0, texconv generates all mipmaps by default
        
        # -sepalpha: Preserves RGB behind transparent pixels during mipmap generation
        if use_sepalpha:
            cmd.append("-sepalpha")
        
        # -alpha: For BC1 1-bit alpha mode
        if use_alpha_flag:
            cmd.append("-alpha")
        
        cmd.append(input_path)
        
        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            if result.stdout:
                print(f"Texconv output: {result.stdout}")
            # Find what it created. Texconv uses input filename for output.
            created_dds = os.path.splitext(input_path)[0] + ".dds"
            if os.path.exists(created_dds) and created_dds != output_path:
                if os.path.exists(output_path):
                    os.remove(output_path)
                os.rename(created_dds, output_path)
            return True
        except subprocess.CalledProcessError as e:
            print(f"Texconv EXE Error: {e.stderr}")
            return False
        except Exception as e:
            print(f"Texconv EXE Invocation Exception: {e}")
            import traceback
            traceback.print_exc()
            return False

def save_image_as_dds(image, save_path, dds_format='BC1_UNORM', use_alpha_flag=False, use_sepalpha=False, mipmap_levels=0):
    """Saves the image as DDS using our standalone Texconv wrapper or PNG fallback."""
    original_filepath = image.filepath_raw
    original_format = image.file_format
    
    # 1. Save temporary PNG for conversion
    temp_png = os.path.splitext(save_path)[0] + "_temp.png"
    image.filepath_raw = temp_png
    image.file_format = 'PNG'
    image.save()
    
    # Verify PNG was created
    if not os.path.exists(temp_png):
        print(f"ERROR: Failed to save temporary PNG: {temp_png}")
        return None
    
    # 2. Convert to DDS
    conv = Texconv()
    dds_file_path = os.path.splitext(save_path)[0] + ".dds"
    
    success = False
    if conv.path:
        print(f"Converting {temp_png} to {dds_file_path}")
        print(f"  Format: {dds_format}, Alpha flag: {use_alpha_flag}, SepAlpha: {use_sepalpha}, Mipmaps: {mipmap_levels}")
        success = conv.convert(temp_png, dds_file_path, dds_format=dds_format, 
                              use_alpha_flag=use_alpha_flag, use_sepalpha=use_sepalpha,
                              mipmap_levels=mipmap_levels)
        
        if not success:
            print(f"ERROR: Texconv conversion failed for {dds_file_path}")
        elif not os.path.exists(dds_file_path):
            print(f"ERROR: DDS file was not created: {dds_file_path}")
            success = False
    else:
        print(f"ERROR: Texconv not found, falling back to PNG")
    
    # Clean up temp PNG
    if os.path.exists(temp_png):
        try:
            os.remove(temp_png)
        except Exception as e:
            print(f"Warning: Could not remove temporary bake PNG: {e}")

    if success and os.path.exists(dds_file_path):
        print(f"SUCCESS: Created DDS file: {dds_file_path}")
        # Load the DDS into Blender for preview
        try:
            dds_img = bpy.data.images.load(dds_file_path)
            dds_img.alpha_mode = 'NONE'
        except:
            pass
        return os.path.basename(dds_file_path)
    
    # 3. Final Fallback to PNG
    print(f"Using PNG fallback for {save_path}")
    try:
        image.filepath_raw = save_path
        image.file_format = 'PNG'
        image.save()
        return os.path.basename(save_path)
    finally:
        image.filepath_raw = original_filepath
        image.file_format = original_format

def cleanup_bake_nodes(obj):
    """Removes temporary baking nodes from materials."""
    for mat in obj.data.materials:
        if not mat or not mat.use_nodes: continue
        nodes = mat.node_tree.nodes
        to_remove = [n for n in nodes if n.name.startswith("BAKE_")]
        for n in to_remove:
            nodes.remove(n)

def run_pipeline(objects, export_dir, resolution=1024, shader_name="MeshGloss.fx", 
                dds_format_diffuse='BC1_UNORM', dds_format_normal='BC3_UNORM',
                alpha_mode='CONSTANT', alpha_value=255, use_bc1_alpha_flag=True,
                mipmap_levels=9):
    """
    Main entry point for the baking pipeline.
    Supports both single object and multi-object atlas baking.
    
    Args:
        objects: Single object or list of objects to bake
        export_dir: Directory to save textures
        ... (other parameters as before)
    
    Returns:
        (baked_objects, texture_results) where baked_objects is a list
    """
    # Normalize input to list
    if not isinstance(objects, list):
        objects = [objects]
    
    if not objects:
        return None, None
    
    # 1. Prepare (single or multi-object)
    is_multi = len(objects) > 1
    joined_obj, metadata = prepare_objects_for_bake(objects, resolution=resolution)
    
    # 2. Setup images
    images = setup_baking_material(joined_obj, resolution=(resolution, resolution))
    
    texture_results = {}
    
    # Determine base filename
    base_name = objects[0].name
    if is_multi:
        base_name = base_name + "_Atlas"
    
    # 3. Bake each pass
    for bake_type, image in images.items():
        is_normal = (bake_type == 'NORMAL')
        param_name = 'NormalTexture' if is_normal else 'BaseTexture'
        dds_fmt = dds_format_normal if is_normal else dds_format_diffuse
        
        filename = f"{base_name}_{param_name}.png"
        save_path = os.path.join(export_dir, filename)
        
        bake_pass(joined_obj, bake_type, image=image, save_path=save_path)
        
        # Process alpha channel for diffuse textures
        use_alpha_flag = False
        use_sepalpha = False
        if bake_type == 'DIFFUSE':
            process_alpha_channel(image, alpha_mode=alpha_mode, alpha_value=alpha_value)
            # Re-save after alpha processing
            image.filepath_raw = save_path
            image.file_format = 'PNG'
            image.save()
            
            # Configure flags based on format
            if dds_fmt == 'BC1_UNORM':
                # BC1: Use -alpha flag for 1-bit alpha mode (when enabled)
                use_alpha_flag = use_bc1_alpha_flag
            elif dds_fmt == 'BC3_UNORM':
                # BC3: Use -sepalpha to preserve RGB behind transparent pixels in mipmaps
                # This prevents WIC from premultiplying alpha and zeroing RGB
                use_sepalpha = True
        
        # Calculate actual mipmap levels to pass to texconv
        # texconv defaults to ALL mipmaps (0), use 1 to disable
        actual_mipmap_levels = mipmap_levels if mipmap_levels > 0 else 0
        if mipmap_levels == 0:  # User disabled mipmaps
            actual_mipmap_levels = 1  # Tell texconv: no mipmaps
        
        # Save as DDS
        saved_name = save_image_as_dds(image, save_path, dds_format=dds_fmt, 
                                       use_alpha_flag=use_alpha_flag,
                                       use_sepalpha=use_sepalpha,
                                       mipmap_levels=actual_mipmap_levels)
        texture_results[param_name] = saved_name
    
    # 4. Separate meshes (if multi-object)
    separated_objs = separate_baked_meshes(joined_obj, metadata, uv_name="ALAMO_BAKE_ATLAS" if is_multi else "ALAMO_BAKE")
    
    # 5. Create baked material (shared for all objects)
    create_baked_material_shared(separated_objs, texture_results, shader_name=shader_name)
    
    # 6. Cleanup
    for obj in objects:
        cleanup_bake_nodes(obj)
    for obj in separated_objs:
        cleanup_bake_nodes(obj)
    
    return separated_objs, texture_results