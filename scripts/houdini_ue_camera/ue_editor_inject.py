# -*- coding: utf-8 -*-
"""
将仓库 ``tools/ue_editor_minimal`` 下的 ``.py`` / ``.uasset`` 复制到
UE 工程 ``Content/Python``（不存在则创建），供编辑器 Python / 资产使用。
"""

from __future__ import annotations

import shutil
from pathlib import Path

_INJECT_SUFFIXES = frozenset({".py", ".uasset"})


def resolve_package_repo_root() -> Path:
    """
    仓库根目录：优先 ``CUSTOM_ENV``（与 ``installHouPackage.py`` 一致），否则根据本包路径推断。
    """
    try:
        import hou

        raw = (hou.getenv("CUSTOM_ENV") or "").strip()
        if raw:
            return Path(raw).expanduser().resolve()
    except ImportError:
        pass
    from . import pipeline_paths as _pp

    return Path(_pp.__file__).resolve().parents[2]


def ue_minimal_tools_dir() -> Path:
    """``tools/ue_editor_minimal`` 绝对路径。"""
    return resolve_package_repo_root() / "tools" / "ue_editor_minimal"


def ue_content_python_dir(ue_project_root: Path) -> Path:
    """``<uproject_root>/Content/Python``。"""
    return (ue_project_root / "Content" / "Python").resolve()


def list_inject_source_files(src_dir: Path) -> list[Path]:
    """仅包含直接子级中的 ``.py`` / ``.uasset``（不递归，跳过 README 等）。"""
    if not src_dir.is_dir():
        return []
    out: list[Path] = []
    for p in sorted(src_dir.iterdir()):
        if p.is_file() and p.suffix.lower() in _INJECT_SUFFIXES:
            out.append(p)
    return out


def inject_ue_editor_minimal(ue_project_root: Path) -> tuple[list[Path], Path]:
    """
    创建 ``Content/Python`` 并将可注入文件复制到该目录。

    :param ue_project_root: UE 工程根目录（含 ``.uproject`` 的目录）。
    :return: ``(已复制目标路径列表, 目标目录)``。
    :raises FileNotFoundError: 源 ``tools/ue_editor_minimal`` 不存在。
    :raises NotADirectoryError: ``ue_project_root`` 不是目录。
    """
    root = ue_project_root.expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(str(root))

    src = ue_minimal_tools_dir()
    if not src.is_dir():
        raise FileNotFoundError(str(src))

    files = list_inject_source_files(src)
    dest_dir = ue_content_python_dir(root)
    dest_dir.mkdir(parents=True, exist_ok=True)

    copied: list[Path] = []
    for f in files:
        target = dest_dir / f.name
        shutil.copy2(f, target)
        copied.append(target)
    return copied, dest_dir
