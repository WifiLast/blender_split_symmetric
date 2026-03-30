
import bpy
from bpy.props import BoolProperty, EnumProperty
from bpy.types import PropertyGroup


class SceneProperties(PropertyGroup):
    cut_axis: EnumProperty(
        name="Cut Axis",
        description="Axis along which to cut the model",
        items=(
            ("X", "X", "Cut along the X axis (left / right)"),
            ("Y", "Y", "Cut along the Y axis (front / back)"),
            ("Z", "Z", "Cut along the Z axis (top / bottom)"),
        ),
        default="X",
    )
    fill_cap: BoolProperty(
        name="Fill Cut",
        description="Fill the open face on each half after splitting",
        default=True,
    )
