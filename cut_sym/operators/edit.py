import bpy
import bmesh
from bpy.types import Operator
from mathutils import Vector


class MESH_OT_bisect(Operator):
    bl_idname = "mesh.cut_sym_bisect"
    bl_label = "Split Model"
    bl_description = "Split the active mesh symmetrically in the middle into two separate objects"
    bl_options = {"REGISTER", "UNDO"}

    axis: bpy.props.EnumProperty(
        name="Axis",
        description="Axis along which to cut the model",
        items=(
            ("X", "X", "Cut along the X axis (left / right)"),
            ("Y", "Y", "Cut along the Y axis (front / back)"),
            ("Z", "Z", "Cut along the Z axis (top / bottom)"),
        ),
        default="X",
    )
    use_origin: bpy.props.BoolProperty(
        name="Cut at Origin",
        description="Cut at the world origin (0,0,0) instead of the bounding-box centre. "
                    "Use this for models that are already centred at the origin",
        default=False,
    )
    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.separator()
        layout.prop(self, "axis", expand=True)
        layout.prop(self, "use_origin")

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "MESH"

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != "MESH":
            self.report({"ERROR"}, "Select one mesh object to split")
            return {"CANCELLED"}

        if len(context.selected_objects) > 1:
            self.report({"WARNING"}, "Multiple selected objects. Only the active one will be split")

        if context.mode == "EDIT_MESH":
            bpy.ops.object.mode_set(mode="OBJECT")

        fill_cap = context.scene.cut_sym.fill_cap
        axis_index = "XYZ".index(self.axis)
        axis_label = self.axis.lower()

        base_name = obj.name
        # Strip existing suffixes to avoid accumulation on redo
        for suffix in ("_left", "_right",
                       "_x_negative", "_x_positive",
                       "_y_negative", "_y_positive",
                       "_z_negative", "_z_positive"):
            if base_name.endswith(suffix):
                base_name = base_name[: -len(suffix)]
                break

        duplicate = self._duplicate_object(context, obj)
        duplicate.name = f"{base_name}_{axis_label}_positive"
        obj.name = f"{base_name}_{axis_label}_negative"

        self._keep_half(obj, axis_index, keep_positive=False,
                        use_origin=self.use_origin, fill_cap=fill_cap)
        self._keep_half(duplicate, axis_index, keep_positive=True,
                        use_origin=self.use_origin, fill_cap=fill_cap)

        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        duplicate.select_set(True)
        context.view_layer.objects.active = duplicate

        return {"FINISHED"}

    def invoke(self, context, event):
        if context.object is None or not context.object.select_get():
            return {"CANCELLED"}

        self.axis = context.scene.cut_sym.cut_axis
        return self.execute(context)

    @staticmethod
    def _duplicate_object(context, obj):
        duplicate = obj.copy()
        duplicate.data = obj.data.copy()

        collections = obj.users_collection or (context.collection,)
        for collection in collections:
            collection.objects.link(duplicate)

        duplicate.matrix_world = obj.matrix_world.copy()
        return duplicate

    @staticmethod
    def _keep_half(obj, axis_index, keep_positive, use_origin=True, fill_cap=True):
        mesh = obj.data
        bm = bmesh.new()
        bm.from_mesh(mesh)

        if use_origin:
            # Cut at the world origin transformed into local object space.
            # For a model centred at the origin with no location offset this is (0,0,0).
            local_origin = obj.matrix_world.inverted() @ Vector((0.0, 0.0, 0.0))
            plane_co = local_origin
        else:
            # Bounding-box centre (original behaviour).
            plane_co = sum((Vector(corner) for corner in obj.bound_box), Vector()) / 8.0

        plane_no = Vector((0.0, 0.0, 0.0))
        plane_no[axis_index] = 1.0

        result = bmesh.ops.bisect_plane(
            bm,
            geom=[*bm.verts, *bm.edges, *bm.faces],
            plane_co=plane_co,
            plane_no=plane_no,
            clear_inner=False,
            clear_outer=False,
        )

        epsilon = 1e-6
        if keep_positive:
            verts_to_delete = [v for v in bm.verts if v.co[axis_index] < plane_co[axis_index] - epsilon]
        else:
            verts_to_delete = [v for v in bm.verts if v.co[axis_index] > plane_co[axis_index] + epsilon]

        if verts_to_delete:
            bmesh.ops.delete(bm, geom=verts_to_delete, context="VERTS")

        # Fill the open boundary created by the cut.
        if fill_cap:
            # After deletion, cut edges have exactly one linked face → is_boundary is True.
            boundary_edges = [e for e in bm.edges if e.is_boundary]
            if boundary_edges:
                bmesh.ops.holes_fill(bm, edges=boundary_edges, sides=0)

        bm.normal_update()
        bm.to_mesh(mesh)
        bm.free()
        mesh.update()
