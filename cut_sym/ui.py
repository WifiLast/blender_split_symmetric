import bpy
from bpy.types import Menu, Panel


# Menus
# ---------------------------


def draw_cut_sym_menu(self, context):
    layout = self.layout
    layout.separator()
    layout.menu("VIEW3D_MT_cut_sym")


class VIEW3D_MT_cut_sym(Menu):
    bl_label = "Cut Sym"

    def draw(self, context):
        layout = self.layout
        props = context.scene.cut_sym
        layout.operator_context = "INVOKE_DEFAULT"
        op = layout.operator("mesh.cut_sym_bisect")
        op.axis = props.cut_axis
        layout.prop(props, "fill_cap")
        layout.prop(props, "cut_axis", expand=True)


# Panels
# ---------------------------


class Sidebar:
    bl_category = "Cut Sym"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"

    @classmethod
    def poll(cls, context):
        return context.mode in {"OBJECT", "EDIT_MESH"}


class VIEW3D_PT_cut_sym_edit(Sidebar, Panel):
    bl_label = "Cut Sym"

    def draw(self, context):
        layout = self.layout
        layout.enabled = context.object is not None
        props = context.scene.cut_sym

        col = layout.column(align=True)
        op = col.operator("mesh.cut_sym_bisect")
        op.axis = props.cut_axis
        col.prop(props, "fill_cap")
        col.prop(props, "cut_axis", expand=True)
