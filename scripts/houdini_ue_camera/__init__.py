"""
Houdini → UE 5.5 摄像机导出库（USD 逐帧采样、清单由面板写入）。

对外主要入口：`export_camera_for_ue55`、`list_cameras_for_ui`。
"""

from .pipeline_paths import (
    HOUDINI_USER_AREA_VERSION,
    MANIFEST_FILENAME,
    fixed_manifest_path_for_running_houdini,
    fixed_manifest_path_in_pref_dir,
    houdini_user_pref_dir_from_home,
)
from .usd_writer import (
    MERGED_USDA_FILENAME,
    export_camera_for_ue55,
    export_merged_cameras_for_ue55,
    list_cameras_for_ui,
    safe_camera_prim_segment,
)

__all__ = [
    "export_camera_for_ue55",
    "export_merged_cameras_for_ue55",
    "list_cameras_for_ui",
    "MERGED_USDA_FILENAME",
    "safe_camera_prim_segment",
    "HOUDINI_USER_AREA_VERSION",
    "MANIFEST_FILENAME",
    "fixed_manifest_path_for_running_houdini",
    "fixed_manifest_path_in_pref_dir",
    "houdini_user_pref_dir_from_home",
]
