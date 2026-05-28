import bpy
import bmesh
import gpu
from gpu_extras.batch import batch_for_shader
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
    cut_offset: bpy.props.FloatProperty(
        name="Cut Offset",
        description="Fine offset of the cut plane along the selected axis",
        default=0.0,
        subtype="DISTANCE",
    )

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.separator()
        layout.prop(self, "axis", expand=True)
        layout.prop(self, "use_origin")
        layout.prop(self, "cut_offset")

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "MESH"

    def execute(self, context):
        obj = getattr(self, "_source_object", None) or context.active_object
        if obj is None or obj.type != "MESH":
            self.report({"ERROR"}, "Select one mesh object to split")
            return {"CANCELLED"}

        if context.mode == "EDIT_MESH":
            bpy.ops.object.mode_set(mode="OBJECT")

        fill_cap = context.scene.cut_sym.fill_cap
        axis_index = "XYZ".index(self.axis)
        axis_label = self.axis.lower()

        base_name = obj.name
        # Strip existing suffixes to avoid accumulation on redo.
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

        self._keep_half(
            obj,
            axis_index,
            keep_positive=False,
            use_origin=self.use_origin,
            fill_cap=fill_cap,
            cut_offset=self.cut_offset,
        )
        self._keep_half(
            duplicate,
            axis_index,
            keep_positive=True,
            use_origin=self.use_origin,
            fill_cap=fill_cap,
            cut_offset=self.cut_offset,
        )

        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        duplicate.select_set(True)
        context.view_layer.objects.active = duplicate

        return {"FINISHED"}

    def invoke(self, context, event):
        obj = context.active_object
        if obj is None or obj.type != "MESH":
            return {"CANCELLED"}

        self.axis = context.scene.cut_sym.cut_axis
        self.use_origin = False
        self.cut_offset = 0.0
        self._source_object = obj
        self._axis_index = "XYZ".index(self.axis)
        self._base_plane = self._get_base_plane(obj)
        self._preview_handle = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_preview,
            (context,),
            "WINDOW",
            "POST_VIEW",
        )
        self._set_status_text(context)
        context.area.tag_redraw()
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type in {"ESC"}:
            self._finish_modal(context, cancel=True)
            return {"CANCELLED"}

        if event.type in {"RET", "NUMPAD_ENTER", "SPACE"} and event.value == "PRESS":
            self._finish_modal(context, cancel=False)
            return self.execute(context)

        if event.value == "PRESS" and event.type in {"LEFT_ARROW", "DOWN_ARROW", "RIGHT_ARROW", "UP_ARROW"}:
            step = self._get_nudge_step(event)
            if event.type in {"LEFT_ARROW", "DOWN_ARROW"}:
                self.cut_offset -= step
            else:
                self.cut_offset += step
            self._set_status_text(context)
            if context.area is not None:
                context.area.tag_redraw()
            return {"RUNNING_MODAL"}

        return {"RUNNING_MODAL", "PASS_THROUGH"}

    def cancel(self, context):
        self._finish_modal(context, cancel=True)

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
    def _keep_half(obj, axis_index, keep_positive, use_origin=True, fill_cap=True, cut_offset=0.0):
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

        plane_co[axis_index] += cut_offset

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

    def _finish_modal(self, context, cancel=False):
        handle = getattr(self, "_preview_handle", None)
        if handle is not None:
            bpy.types.SpaceView3D.draw_handler_remove(handle, "WINDOW")
            self._preview_handle = None

        if getattr(context, "workspace", None) is not None:
            context.workspace.status_text_set(None)

        if cancel and context.area is not None:
            context.area.tag_redraw()

    def _get_base_plane(self, obj):
        if self.use_origin:
            return obj.matrix_world.inverted() @ Vector((0.0, 0.0, 0.0))
        return sum((Vector(corner) for corner in obj.bound_box), Vector()) / 8.0

    def _get_plane_co(self):
        plane_co = self._base_plane.copy()
        plane_co[self._axis_index] += self.cut_offset
        return plane_co

    def _get_nudge_step(self, event):
        obj = getattr(self, "_source_object", None)
        if obj is None:
            return 0.001

        axis_lengths = []
        for axis in range(3):
            values = [corner[axis] for corner in obj.bound_box]
            axis_lengths.append(max(values) - min(values))

        base = max(axis_lengths[self._axis_index] * 0.0025, 0.0001)
        if event.shift:
            base *= 10.0
        if event.ctrl:
            base *= 0.1
        return base

    def _set_status_text(self, context):
        if getattr(context, "workspace", None) is None:
            return

        context.workspace.status_text_set(
            f"Cut Sym  [{self.axis}]  Arrow keys: nudge cut  |  Enter: confirm  |  Esc: cancel  |  Offset: {self.cut_offset:.4f}"
        )

    def _draw_preview(self, context):
        obj = getattr(self, "_source_object", None)
        if obj is None or obj.name not in context.scene.objects:
            return

        plane_co = self._get_plane_co()
        axis = self._axis_index

        bounds = [Vector(corner) for corner in obj.bound_box]
        min_vals = [min(corner[i] for corner in bounds) for i in range(3)]
        max_vals = [max(corner[i] for corner in bounds) for i in range(3)]

        other_axes = [i for i in range(3) if i != axis]
        corners = []
        for first, second in (
            (min_vals[other_axes[0]], min_vals[other_axes[1]]),
            (max_vals[other_axes[0]], min_vals[other_axes[1]]),
            (max_vals[other_axes[0]], max_vals[other_axes[1]]),
            (min_vals[other_axes[0]], max_vals[other_axes[1]]),
        ):
            local = Vector((0.0, 0.0, 0.0))
            local[axis] = plane_co[axis]
            local[other_axes[0]] = first
            local[other_axes[1]] = second
            corners.append(obj.matrix_world @ local)

        shader_name = "UNIFORM_COLOR" if bpy.app.version >= (4, 0, 0) else "3D_UNIFORM_COLOR"
        shader = gpu.shader.from_builtin(shader_name)
        fill_batch = batch_for_shader(shader, "TRIS", {"pos": (corners[0], corners[1], corners[2], corners[0], corners[2], corners[3])})
        outline_batch = batch_for_shader(shader, "LINE_STRIP", {"pos": (corners[0], corners[1], corners[2], corners[3], corners[0])})

        gpu.state.blend_set("ALPHA")
        gpu.state.depth_test_set("LESS_EQUAL")
        shader.bind()
        shader.uniform_float("color", (1.0, 0.85, 0.1, 0.18))
        fill_batch.draw(shader)
        gpu.state.line_width_set(2.0)
        shader.uniform_float("color", (1.0, 0.85, 0.1, 0.95))
        outline_batch.draw(shader)
        gpu.state.line_width_set(1.0)
        gpu.state.depth_test_set("NONE")
        gpu.state.blend_set("NONE")
