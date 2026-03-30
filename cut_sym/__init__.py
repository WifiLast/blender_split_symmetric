if "bpy" in locals():
    from pathlib import Path
    essentials.reload_recursive(Path(__file__).parent, locals())
else:
    import bpy
    from bpy.props import PointerProperty

    from . import essentials, operators, preferences, ui


classes = essentials.get_classes((operators, preferences, ui))


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.cut_sym = PointerProperty(type=preferences.SceneProperties)

    # Menu
    # ---------------------------

    bpy.types.VIEW3D_MT_object.append(ui.draw_cut_sym_menu)
    bpy.types.VIEW3D_MT_edit_mesh.append(ui.draw_cut_sym_menu)


def unregister():
    for cls in classes:
        bpy.utils.unregister_class(cls)

    del bpy.types.Scene.cut_sym

    # Menu
    # ---------------------------

    bpy.types.VIEW3D_MT_object.remove(ui.draw_cut_sym_menu)
    bpy.types.VIEW3D_MT_edit_mesh.remove(ui.draw_cut_sym_menu)
