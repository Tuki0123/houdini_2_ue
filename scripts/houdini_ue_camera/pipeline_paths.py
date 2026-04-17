# -*- coding: utf-8 -*-
"""
与仓库根 ``installHouPackage.houdini_locations`` 一致的 Houdini 用户区版本号及
**固定清单路径**（清单始终写在 ``HOUDINI_USER_PREF_DIR`` 下，每次导出覆盖）。

UE 侧 ``manifest_smoke.default_fixed_manifest_abs_path`` 须与本模块路径规则保持同步。
"""

from __future__ import annotations

import platform
from pathlib import Path

# 与 installHouPackage.py 中 houdini_version 一致；更换主版本时请两处同改。
HOUDINI_USER_AREA_VERSION = "20.5"

MANIFEST_FILENAME = "houdini_ue_camera_manifest.json"


def houdini_user_pref_dir_from_home(home: Path | None = None) -> Path:
    """
    未启动 Houdini 时，按 OS 推断默认用户偏好根目录（与 ``installHouPackage`` 拼接规则一致）。

    - Windows: ``~/Documents/houdini<ver>``
    - macOS: ``~/Library/Preferences/houdini/<ver>``
    - Linux: ``~/houdini<ver>``
    """
    home = home or Path.home()
    sys = platform.system()
    ver = HOUDINI_USER_AREA_VERSION
    if sys == "Windows":
        return home / "Documents" / f"houdini{ver}"
    if sys == "Darwin":
        return home / "Library" / "Preferences" / "houdini" / ver
    return home / f"houdini{ver}"


def fixed_manifest_path_in_pref_dir(pref_dir: Path) -> Path:
    """给定 Houdini 用户偏好根目录，返回固定清单绝对路径。"""
    return (pref_dir.expanduser().resolve() / MANIFEST_FILENAME).resolve()


def fixed_manifest_path_for_running_houdini() -> Path:
    """
    在 Houdini 进程内：以 ``HOUDINI_USER_PREF_DIR`` 为准（可覆盖「文档」默认位置）。

    若环境变量为空，回退到 ``houdini_user_pref_dir_from_home()``。
    """
    try:
        import hou
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("fixed_manifest_path_for_running_houdini() requires Houdini") from exc
    raw = (hou.getenv("HOUDINI_USER_PREF_DIR") or "").strip()
    pref = Path(raw) if raw else houdini_user_pref_dir_from_home()
    return fixed_manifest_path_in_pref_dir(pref)
