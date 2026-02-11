import bpy
import os
from . import settings


class ALAMO_PT_materialPropertyPanel(bpy.types.Panel):
    bl_label = "Alamo Shader Properties"
    bl_id = "ALAMO_PT_materialPropertyPanel"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "material"

    def draw(self, context):
        object = context.object
        layout = self.layout
        col = layout.column()

        if type(object) != type(None) and object.type == "MESH":
            material = bpy.context.active_object.active_material
            if material is not None:
                # a None image is needed to represent not using a texture
                if "None" not in bpy.data.images:
                    bpy.data.images.new(name="None", width=1, height=1)
                col.prop(material.shaderList, "shaderList")
                if material.shaderList.shaderList != "alDefault.fx":
                    shader_props = settings.material_parameter_dict[
                        material.shaderList.shaderList
                    ]
                    for shader_prop in shader_props:
                        # because contains() doesn't exist, apparently
                        if shader_prop.find("Texture") > -1:
                            layout.prop_search(
                                material, shader_prop, bpy.data, "images"
                            )


class ALAMO_PT_materialBakePanel(bpy.types.Panel):
    bl_label = "Alamo Texture Baking"
    bl_id = "ALAMO_PT_materialBakePanel"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "material"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        obj = context.object
        if obj is None or obj.type != 'MESH':
            return
        
        # Count selected mesh objects
        selected_meshes = [o for o in context.selected_objects if o.type == 'MESH']
        num_selected = len(selected_meshes)
        
        # Info box showing what will be baked
        box = layout.box()
        if num_selected == 0:
            box.label(text="No mesh objects selected", icon='ERROR')
        elif num_selected == 1:
            box.label(text="Single Object Bake", icon='MESH_CUBE')
            box.label(text=f"Object: {selected_meshes[0].name}")
        else:
            box.label(text="Multi-Object Atlas Bake", icon='UV')
            box.label(text=f"Baking {num_selected} objects into shared texture")
            # Show first few object names
            for i, o in enumerate(selected_meshes[:3]):
                box.label(text=f"  â€¢ {o.name}")
            if num_selected > 3:
                box.label(text=f"  ... and {num_selected - 3} more")
        
        layout.separator()
        
        col = layout.column()
        col.prop(context.scene, "alamo_bake_res")
        col.prop(context.scene, "alamo_bake_shader")
        
        # DDS Settings
        sub = col.column(align=True)
        sub.label(text="DDS Compression:")
        sub.prop(context.scene, "alamo_bake_dds_diffuse")
        sub.prop(context.scene, "alamo_bake_dds_normal")
        
        layout.separator()
        
        # Alpha Channel Settings
        box = layout.box()
        box.label(text="Alpha Channel (Team Color):", icon='IMAGE_ALPHA')
        
        col = box.column(align=True)
        col.prop(context.scene, "alamo_bake_alpha_mode", text="Mode")
        
        # Show alpha value slider only for CONSTANT mode
        if context.scene.alamo_bake_alpha_mode == 'CONSTANT':
            col.prop(context.scene, "alamo_bake_alpha_value", text="Alpha Value")
            
            # Helper info
            sub = col.column(align=True)
            sub.scale_y = 0.8
            sub.label(text="255 = Full team color", icon='INFO')
            sub.label(text="0 = No team color (original texture)")
            sub.label(text="For BC1: Use 0 or 255 only")
        
        elif context.scene.alamo_bake_alpha_mode == 'EXTRACT_SATURATION':
            # Helper info for extract mode
            sub = col.column(align=True)
            sub.scale_y = 0.8
            sub.label(text="Extracts color saturation to alpha", icon='INFO')
            sub.label(text="Converts texture to grayscale")
            sub.label(text="Colored areas â†’ team-colorable")
            sub.label(text="Works best with BC3 format")
        
        layout.separator()
        
        # Format recommendation based on settings
        if context.scene.alamo_bake_alpha_mode == 'EXTRACT_SATURATION':
            info_box = layout.box()
            info_box.label(text="Recommended: BC3 format", icon='INFO')
            info_box.label(text="(Alpha for team colors)")
        elif context.scene.alamo_bake_alpha_mode == 'CONSTANT':
            alpha_val = context.scene.alamo_bake_alpha_value
            if alpha_val not in (0, 255):
                info_box = layout.box()
                info_box.label(text="Warning: Non-binary alpha!", icon='ERROR')
                info_box.label(text="BC1 will clamp to 0 or 255")
                info_box.label(text="Use BC3 for gradual values")
        
        layout.separator()
        
        # Texconv Path
        col = layout.column()
        col.prop(context.scene, "alamo_texconv_path")
        
        # Addon/Tool Status
        from . import bake_pipeline
        tool_path = bake_pipeline.find_texconv_tool(context=context)
        
        if tool_path:
            if tool_path.lower().endswith(".dll"):
                col.label(text=f"DDS Tool: DLL Found", icon='CHECKMARK')
            else:
                col.label(text=f"DDS Tool: EXE Found", icon='CHECKMARK')
        else:
            col.label(text="DDS Tool: Not Found (Fallback to PNG)", icon='ERROR')
        
        layout.separator()
        
        row = layout.row()
        row.operator("alamo.bake_textures", text="Bake & Prepare", icon='RENDER_STILL')
        row.scale_y = 2.0
        row.enabled = num_selected > 0


class ALAMO_OT_BakeTextures(bpy.types.Operator):
    bl_idname = "alamo.bake_textures"
    bl_label = "Bake Alamo Textures"
    bl_description = "Bake diffuse and normal maps and prepare object(s) for export"
    
    def execute(self, context):
        from . import bake_pipeline
        import os
        
        # Get selected mesh objects
        selected_meshes = [o for o in context.selected_objects if o.type == 'MESH']
        
        if len(selected_meshes) == 0:
            self.report({'ERROR'}, "No mesh objects selected")
            return {'CANCELLED'}
        
        # Use export path if available, or current file path
        if bpy.data.filepath:
            export_dir = os.path.dirname(bpy.data.filepath)
        else:
            export_dir = os.path.expanduser("~")  # Fallback to home
            
        res = int(context.scene.alamo_bake_res)
        shader = context.scene.alamo_bake_shader
        dds_diff = context.scene.alamo_bake_dds_diffuse
        dds_norm = context.scene.alamo_bake_dds_normal
        alpha_mode = context.scene.alamo_bake_alpha_mode
        alpha_value = context.scene.alamo_bake_alpha_value
        
        # Validation
        if alpha_mode == 'CONSTANT' and dds_diff == 'BC1_UNORM' and alpha_value not in (0, 255):
            self.report({'WARNING'}, f"BC1 will clamp alpha {alpha_value} to binary (0 or 255)")
        
        # Report what we're baking
        if len(selected_meshes) == 1:
            self.report({'INFO'}, f"Starting single object bake at {res}px with alpha={alpha_value}...")
        else:
            self.report({'INFO'}, f"Starting atlas bake for {len(selected_meshes)} objects at {res}px...")
        
        try:
            baked_objs, results = bake_pipeline.run_pipeline(
                selected_meshes,  # Pass list of objects
                export_dir, 
                resolution=res, 
                shader_name=shader,
                dds_format_diffuse=dds_diff,
                dds_format_normal=dds_norm,
                alpha_mode=alpha_mode,
                alpha_value=alpha_value
            )
            
            if len(selected_meshes) == 1:
                if alpha_mode == 'EXTRACT_SATURATION':
                    self.report({'INFO'}, f"Bake finished with saturation extraction. New object: {baked_objs[0].name}")
                else:
                    self.report({'INFO'}, f"Bake finished (alpha={alpha_value}). New object: {baked_objs[0].name}")
            else:
                self.report({'INFO'}, f"Atlas bake finished! Created {len(baked_objs)} objects with shared texture")
                
        except Exception as e:
            self.report({'ERROR'}, f"Bake failed: {str(e)}")
            import traceback
            traceback.print_exc()
            return {'CANCELLED'}
            
        return {'FINISHED'}


class ALAMO_PT_materialPropertySubPanel(bpy.types.Panel):
    bl_label = "Additional Properties"
    bl_parent_id = "ALAMO_PT_materialPropertyPanel"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "material"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        obj = context.object
        layout = self.layout
        col = layout.column()

        if obj is not None and obj.type == "MESH":
            material = bpy.context.active_object.active_material
            if (
                material is not None
                and material.shaderList.shaderList != "alDefault.fx"
            ):
                shader_props = settings.material_parameter_dict[
                    material.shaderList.shaderList
                ]
                for shader_prop in shader_props:
                    if shader_prop.find("Texture") == -1:
                        col.prop(material, shader_prop)


class shaderListProperties(bpy.types.PropertyGroup):
    mode_options = [
        (shader_name, shader_name, "", "", index)
        for index, shader_name in enumerate(settings.material_parameter_dict)
    ]

    shaderList: bpy.props.EnumProperty(
        items=mode_options,
        description="Choose ingame Shader",
        default="alDefault.fx",
    )


# Registration ####################################################################################
classes = (
    shaderListProperties,
    ALAMO_PT_materialPropertyPanel,
    ALAMO_PT_materialPropertySubPanel,
    ALAMO_PT_materialBakePanel,
    ALAMO_OT_BakeTextures,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Material.BaseTexture = bpy.props.StringProperty(default="None")
    bpy.types.Material.DetailTexture = bpy.props.StringProperty(default="None")
    bpy.types.Material.NormalDetailTexture = bpy.props.StringProperty(default="None")
    bpy.types.Material.NormalTexture = bpy.props.StringProperty(default="None")
    bpy.types.Material.GlossTexture = bpy.props.StringProperty(default="None")
    bpy.types.Material.WaveTexture = bpy.props.StringProperty(default="None")
    bpy.types.Material.DistortionTexture = bpy.props.StringProperty(default="None")
    bpy.types.Material.CloudTexture = bpy.props.StringProperty(default="None")
    bpy.types.Material.CloudNormalTexture = bpy.props.StringProperty(default="None")

    bpy.types.Material.shaderList = bpy.props.PointerProperty(type=shaderListProperties)
    
    # Scene properties for baking
    bpy.types.Scene.alamo_bake_res = bpy.props.EnumProperty(
        name="Resolution",
        items=[
            ('512', '512', ""),
            ('1024', '1024', ""),
            ('2048', '2048', ""),
            ('4096', '4096', ""),
            ('8192', '8192', ""),
        ],
        default='1024'
    )
    
    bpy.types.Scene.alamo_bake_shader = bpy.props.EnumProperty(
        name="Target Shader",
        items=[(s, s, "") for s in settings.material_parameter_dict.keys()],
        default='MeshGloss.fx'
    )

    # DDS Compression Options
    dds_items = [
        ('BC1_UNORM', 'BC1 (DXT1) - 1-bit Alpha', "Highest compression with 1-bit alpha"),
        ('BC3_UNORM', 'BC3 (DXT5) - 8-bit Alpha', "Compression with full alpha channel"),
        ('BC7_UNORM', 'BC7 - High Quality', "Modern high-quality compression"),
        ('R8G8B8A8_UNORM', 'Uncompressed', "No compression"),
    ]

    bpy.types.Scene.alamo_bake_dds_diffuse = bpy.props.EnumProperty(
        name="Diffuse Format",
        items=dds_items,
        default='BC1_UNORM',
    )

    bpy.types.Scene.alamo_bake_dds_normal = bpy.props.EnumProperty(
        name="Normal Format",
        items=dds_items,
        default='BC3_UNORM'
    )

    # Alpha Channel Control
    bpy.types.Scene.alamo_bake_alpha_mode = bpy.props.EnumProperty(
        name="Alpha Mode",
        description="How to handle the alpha channel for team colorization",
        items=[
            ('CONSTANT', 'Constant Value', "Set alpha to a constant value (0-255)"),
            ('EXTRACT_SATURATION', 'Extract Saturation', "Alpha from color saturation (Use BC3)"),
            ('PRESERVE', 'Preserve Original', "Keep the original alpha from materials"),
        ],
        default='CONSTANT'
    )

    bpy.types.Scene.alamo_bake_alpha_value = bpy.props.IntProperty(
        name="Alpha Value",
        description="Alpha channel value (0-255). 255 = full team color, 0 = original texture. BC1 only supports 255, loses RGB at 0",
        min=0,
        max=255,
        default=255,
        subtype='UNSIGNED'
    )

    bpy.types.Scene.alamo_texconv_path = bpy.props.StringProperty(
        name="Texconv Path",
        description="Path to texconv.exe or texconv.dll (overrides auto-detection)",
        subtype='FILE_PATH',
        default=""
    )

    bpy.types.Material.Emissive = bpy.props.FloatVectorProperty(
        min=0.0, max=1.0, size=4, default=(0.0, 0.0, 0.0, 0.0)
    )
    bpy.types.Material.Diffuse = bpy.props.FloatVectorProperty(
        min=0.0, max=1.0, size=4, default=(1.0, 1.0, 1.0, 0.0)
    )
    bpy.types.Material.Specular = bpy.props.FloatVectorProperty(
        min=0.0, max=1.0, size=4, default=(1.0, 1.0, 1.0, 0.0)
    )
    bpy.types.Material.Shininess = bpy.props.FloatProperty(
        min=0.0, max=255.0, default=32.0
    )
    bpy.types.Material.Colorization = bpy.props.FloatVectorProperty(
        min=0.0, max=1.0, size=4, default=(1.0, 1.0, 1.0, 0.0)
    )
    bpy.types.Material.DebugColor = bpy.props.FloatVectorProperty(
        min=0.0, max=1.0, size=4, default=(0.0, 1.0, 0.0, 0.0)
    )
    bpy.types.Material.UVOffset = bpy.props.FloatVectorProperty(
        min=0.0, max=1.0, size=4, default=(0.0, 0.0, 0.0, 0.0)
    )
    bpy.types.Material.Color = bpy.props.FloatVectorProperty(
        min=0.0, max=1.0, size=4, default=(1.0, 1.0, 1.0, 1.0)
    )
    bpy.types.Material.UVScrollRate = bpy.props.FloatVectorProperty(
        min=0.0, max=1.0, size=4, default=(0.0, 0.0, 0.0, 0.0)
    )
    bpy.types.Material.DiffuseColor = bpy.props.FloatVectorProperty(
        min=0.0, max=1.0, size=3, default=(0.5, 0.5, 0.5)
    )
    # shield shader properties
    bpy.types.Material.EdgeBrightness = bpy.props.FloatProperty(
        min=0.0, max=255.0, default=0.5
    )
    bpy.types.Material.BaseUVScale = bpy.props.FloatProperty(
        min=-255.0, max=255.0, default=1.0
    )
    bpy.types.Material.WaveUVScale = bpy.props.FloatProperty(
        min=-255.0, max=255.0, default=1.0
    )
    bpy.types.Material.DistortUVScale = bpy.props.FloatProperty(
        min=-255.0, max=255.0, default=1.0
    )
    bpy.types.Material.BaseUVScrollRate = bpy.props.FloatProperty(
        min=-255.0, max=255.0, default=-0.15
    )
    bpy.types.Material.WaveUVScrollRate = bpy.props.FloatProperty(
        min=-255.0, max=255.0, default=-0.15
    )
    bpy.types.Material.DistortUVScrollRate = bpy.props.FloatProperty(
        min=-255.0, max=255.0, default=-0.25
    )
    # tree properties
    bpy.types.Material.BendScale = bpy.props.FloatProperty(
        min=-255.0, max=255.0, default=0.4
    )
    # grass properties
    bpy.types.Material.Diffuse1 = bpy.props.FloatVectorProperty(
        min=0.0, max=1.0, size=4, default=(1.0, 1.0, 1.0, 1.0)
    )
    # skydome.fx properties
    bpy.types.Material.CloudScrollRate = bpy.props.FloatProperty(
        min=-255.0, max=255.0, default=0.001
    )
    bpy.types.Material.CloudScale = bpy.props.FloatProperty(
        min=-255.0, max=255.0, default=1.0
    )
    # nebula.fx properties
    bpy.types.Material.SFreq = bpy.props.FloatProperty(
        min=-255.0, max=255.0, default=0.002
    )
    bpy.types.Material.TFreq = bpy.props.FloatProperty(
        min=-255.0, max=255.0, default=0.005
    )
    bpy.types.Material.DistortionScale = bpy.props.FloatProperty(
        min=-255.0, max=255.0, default=1.0
    )
    # planet.fx properties
    bpy.types.Material.Atmosphere = bpy.props.FloatVectorProperty(
        min=0.0, max=1.0, size=4, default=(0.5, 0.5, 0.5, 0.5)
    )
    bpy.types.Material.CityColor = bpy.props.FloatVectorProperty(
        min=0.0, max=1.0, size=4, default=(0.5, 0.5, 0.5, 0.5)
    )
    bpy.types.Material.AtmospherePower = bpy.props.FloatProperty(
        min=-255.0, max=255.0, default=1.0
    )
    # tryplanar mapping properties
    bpy.types.Material.MappingScale = bpy.props.FloatProperty(
        min=0.0, max=255.0, default=0.1
    )
    bpy.types.Material.BlendSharpness = bpy.props.FloatProperty(
        min=0.0, max=255.0, default=0.1
    )


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    # Clean up material properties
    props_to_del = [
        "BaseTexture", "DetailTexture", "NormalTexture", "NormalDetailTexture",
        "GlossTexture", "WaveTexture", "DistortionTexture", "CloudTexture",
        "CloudNormalTexture", "shaderList", "Emissive", "Diffuse", "Specular",
        "Shininess", "Colorization", "DebugColor", "UVOffset", "Color",
        "UVScrollRate", "DiffuseColor", "EdgeBrightness", "BaseUVScale",
        "WaveUVScale", "DistortUVScale", "BaseUVScrollRate", "WaveUVScrollRate",
        "DistortUVScrollRate", "BendScale", "Diffuse1", "CloudScrollRate",
        "CloudScale", "SFreq", "TFreq", "DistortionScale", "Atmosphere",
        "CityColor", "AtmospherePower", "MappingScale", "BlendSharpness"
    ]
    
    for p in props_to_del:
        if hasattr(bpy.types.Material, p):
            delattr(bpy.types.Material, p)

    # Clean up scene properties
    scene_props_to_del = [
        "alamo_bake_res", "alamo_bake_shader", "alamo_bake_dds_diffuse",
        "alamo_bake_dds_normal", "alamo_texconv_path", "alamo_bake_alpha_mode",
        "alamo_bake_alpha_value"
    ]
    for p in scene_props_to_del:
        if hasattr(bpy.types.Scene, p):
            delattr(bpy.types.Scene, p)


if __name__ == "__main__":
    register()