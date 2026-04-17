# -*- coding: utf-8 -*-
"""
Houdini → UE 相机管线：通过 **USD Stage Editor** 将 USDA 导入到 Content（默认 ``/Game/houdini_camera``）。

流程概览：``open_stage_editor`` → ``file_open(usda)`` → ``actions_import(content_folder, options)``
→ ``file_close``。依赖同目录下的 ``houdini_camera_manifest`` 解析清单。
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

import unreal

import houdini_camera_manifest

_LOG_PREFIX = "[HoudiniCamera:Import]"

# Default Content path (matches student spec: houdini_camera folder under Content)
DEFAULT_CONTENT_ROOT = "/Game/houdini_camera"

# 关卡里由 ``import_actors=True`` 生成的 CineCameraActor 不会随 Content 资产删除而消失。
# - ``"all"``（默认）：导入前删除当前编辑关卡中**全部** CineCameraActor，再导入（避免旧实例残留）。
# - ``"none"``：不删关卡电影机（仅删 LSA + Content 树）；若场景里仍有残留，请改回 ``all`` 或在 EUW 里先调 ``purge_only()``。
PURGE_LEVEL_CINECAMERA_POLICY: str = "all"


def _safe_folder_segment(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_]", "_", str(name))
    return s or "Camera"


def ensure_content_dir(content_path: str) -> None:
    """Create /Game/... folder if missing."""
    if not unreal.EditorAssetLibrary.does_directory_exist(content_path):
        unreal.EditorAssetLibrary.make_directory(content_path)
        unreal.log_warning(f"{_LOG_PREFIX} created Content folder: {content_path}")


def _destroy_actor_safe(actor: unreal.Actor) -> bool:
    """编辑器下销毁 Actor；统一走 ``EditorLevelLibrary``（避免误用不存在的实例方法）。"""
    try:
        unreal.EditorLevelLibrary.destroy_actor(actor)
        return True
    except Exception:
        return False


def _purge_cine_camera_actors_in_editor_world() -> None:
    """按 ``PURGE_LEVEL_CINECAMERA_POLICY`` 删除关卡里的 CineCameraActor（USD ``import_actors`` 残留）。"""
    policy = (PURGE_LEVEL_CINECAMERA_POLICY or "all").strip().lower()
    if policy == "none":
        return
    if policy != "all":
        unreal.log_warning(
            f"{_LOG_PREFIX} unknown PURGE_LEVEL_CINECAMERA_POLICY={policy!r}, using 'all'"
        )
        policy = "all"
    world = unreal.EditorLevelLibrary.get_editor_world()
    if world is None:
        return
    try:
        actors = unreal.GameplayStatics.get_all_actors_of_class(world, unreal.CineCameraActor)
    except Exception:
        return
    removed = 0
    for a in actors or []:
        if _destroy_actor_safe(a):
            removed += 1
    if removed:
        unreal.log_warning(f"{_LOG_PREFIX} purge: destroyed {removed} CineCameraActor(s) in level")


def _purge_level_sequence_actors_for_content_root(content_root: str) -> None:
    """删除当前关卡中、绑定的 LevelSequence 资源路径位于 ``content_root`` 下的 ``LevelSequenceActor``。"""
    root = content_root.rstrip("/")
    root_lower = root.lower()
    world = unreal.EditorLevelLibrary.get_editor_world()
    if world is None:
        return
    try:
        actors = unreal.GameplayStatics.get_all_actors_of_class(world, unreal.LevelSequenceActor)
    except Exception:
        return
    removed = 0
    for a in actors or []:
        try:
            seq = a.get_editor_property("sequence")
            if seq is not None:
                p = seq.get_path_name().lower()
                if not (p == root_lower or p.startswith(root_lower + "/")):
                    continue
        except Exception:
            continue
        if _destroy_actor_safe(a):
            removed += 1
    if removed:
        unreal.log_warning(
            f"{_LOG_PREFIX} purge: destroyed {removed} LevelSequenceActor(s) under {root}"
        )


def _purge_all_assets_under_content_root(content_root: str) -> None:
    """删除 ``content_root`` 下（递归）全部资产，便于固定路径重复导入时与 Houdini 相机数量一致。"""
    root = content_root.rstrip("/")
    if not unreal.EditorAssetLibrary.does_directory_exist(root):
        return
    try:
        paths = unreal.EditorAssetLibrary.list_assets(root, recursive=True, include_folder=False)
    except TypeError:
        paths = unreal.EditorAssetLibrary.list_assets(root, recursive=True)
    paths = paths or []
    for p in sorted(paths, key=lambda x: len(str(x)), reverse=True):
        try:
            if unreal.EditorAssetLibrary.does_asset_exist(p):
                unreal.EditorAssetLibrary.delete_asset(p)
        except Exception:
            pass
    unreal.log_warning(
        f"{_LOG_PREFIX} purge: removed up to {len(paths)} asset path(s) under {root}"
    )


def purge_houdini_camera_import_before_reimport(content_root: str) -> None:
    """
    在写入 USDA 之前调用，顺序为：

    1. 删除绑定到 ``content_root`` 下 LevelSequence 的 ``LevelSequenceActor``（关卡里拖的序列实例）。
    2. 按 ``PURGE_LEVEL_CINECAMERA_POLICY`` 删除关卡里残留的 ``CineCameraActor``（``import_actors`` 生成、
       不会随 Content 资产删除而消失）。
    3. 递归删除 ``content_root`` 下全部 Content 资产，再 ``ensure_content_dir``。
    """
    root = content_root.rstrip("/")
    if not root.startswith("/Game/"):
        unreal.log_warning(
            f"{_LOG_PREFIX} purge skipped: content_root must be under /Game/, got {root!r}"
        )
        return
    _purge_level_sequence_actors_for_content_root(root)
    _purge_cine_camera_actors_in_editor_world()
    _purge_all_assets_under_content_root(root)
    ensure_content_dir(root)


def _post_import_flush_and_count_assets(content_dest: str) -> int:
    """
    USD Stage Editor 的 ``actions_import`` 在部分版本/负载下近乎异步：若立刻 ``file_close``，
    Content 里可能尚未出现 uasset。此处短暂等待、尝试保存脏包并刷新 AssetRegistry，再统计
    ``content_dest`` 下（递归）资产路径数量。

    返回 ``-1`` 表示统计失败（不当作「零资产」误判）。
    """
    time.sleep(0.6)
    try:
        unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, False)
    except Exception:
        try:
            unreal.EditorAssetLibrary.save_directory(content_dest)
        except Exception:
            pass
    try:
        reg = unreal.AssetRegistryHelpers.get_asset_registry()
        try:
            reg.scan_paths_synchronous([content_dest], force_rescan=True)
        except TypeError:
            reg.scan_paths_synchronous([content_dest])
    except Exception:
        pass
    try:
        assets = unreal.EditorAssetLibrary.list_assets(
            content_dest, recursive=True, include_folder=False
        )
    except TypeError:
        try:
            assets = unreal.EditorAssetLibrary.list_assets(content_dest, recursive=True)
        except Exception:
            return -1
    except Exception:
        return -1
    n = len(assets) if assets else 0
    if assets:
        sample = ", ".join(str(a) for a in assets[:6])
        unreal.log_warning(f"{_LOG_PREFIX} assets under {content_dest!r} (n={n}): {sample}…")
    else:
        unreal.log_warning(
            f"{_LOG_PREFIX} no assets listed under {content_dest!r} after import flush"
        )
    return n


def build_import_options(*, import_level_actors: bool = True) -> unreal.UsdStageImportOptions:
    """
    Defaults tuned for Houdini camera USDA (matrix + imaging), minimal geometry.

    ``import_level_actors``：是否在关卡中生成/更新 Camera / CineCamera（默认 ``True``）。
    合并导入前会先 ``purge_houdini_camera_import_before_reimport`` 清空 ``content_root``，
    以减轻「减相机」重导后关卡里残留旧实例的问题。
    """
    o = unreal.UsdStageImportOptions()
    # False: avoid mirroring /World/... prim paths as deep Content folders; assets
    # group by type (e.g. LevelSequences) under the import root instead.
    try:
        o.set_editor_property("prim_path_folder_structure", False)
    except Exception:
        pass
    o.set_editor_property("import_actors", import_level_actors)
    o.set_editor_property("import_level_sequences", True)
    o.set_editor_property("import_geometry", False)
    o.set_editor_property("import_materials", False)
    o.set_editor_property("import_groom_assets", False)
    o.set_editor_property("import_sparse_volume_textures", False)
    try:
        o.set_editor_property(
            "existing_asset_policy",
            unreal.ReplaceAssetPolicy.REPLACE,
        )
    except Exception:
        pass
    try:
        o.set_editor_property(
            "existing_actor_policy",
            unreal.ReplaceActorPolicy.REPLACE,
        )
    except Exception:
        pass
    return o


def import_usda_to_content(
    usda_abs_path: str,
    content_dest: str,
    *,
    options: unreal.UsdStageImportOptions | None = None,
) -> bool:
    """
    Open USDA in USD Stage Editor and run Actions -> Import into content_dest.
    content_dest example: /Game/houdini_camera/cam_A
    """
    p = Path(os.path.expandvars(usda_abs_path.strip().strip('"')))
    if not p.is_file():
        unreal.log_error(f"{_LOG_PREFIX} file not found: {p}")
        return False
    disk_path = str(p.resolve())

    ensure_content_dir(content_dest)
    opts = options or build_import_options()

    try:
        unreal.UsdStageEditorLibrary.open_stage_editor()
        unreal.UsdStageEditorLibrary.file_open(disk_path)
        unreal.UsdStageEditorLibrary.actions_import(content_dest, opts)
    except Exception as exc:  # noqa: BLE001
        unreal.log_error(f"{_LOG_PREFIX} import failed for {disk_path}: {exc!r}")
        try:
            unreal.UsdStageEditorLibrary.file_close()
        except Exception:
            pass
        return False

    try:
        n_assets = _post_import_flush_and_count_assets(content_dest)
    except Exception as exc:  # noqa: BLE001
        unreal.log_error(f"{_LOG_PREFIX} post-import flush failed: {exc!r}")
        n_assets = -1
    try:
        unreal.UsdStageEditorLibrary.file_close()
    except Exception:
        pass

    if n_assets == 0:
        unreal.log_error(
            f"{_LOG_PREFIX} import reported no assets under {content_dest!r}. "
            "Check: USD Stage Editor plugins enabled; Output Log for USD errors; "
            "Content Browser 里打开 /Game/houdini_camera（不是只看磁盘上的 Content 文件夹）。\n"
            "若仍为空，可把 houdini_camera_usd_import._post_import_flush_and_count_assets 里的 sleep 略加大。"
        )
        return False
    if n_assets < 0:
        unreal.log_warning(
            f"{_LOG_PREFIX} could not verify asset count under {content_dest!r}; "
            "请手动在 Content Browser 中确认是否已有 LevelSequence 等资产。"
        )

    unreal.log_warning(
        f"{_LOG_PREFIX} imported -> {content_dest} | source={disk_path}"
        + (f" | assets={n_assets}" if n_assets >= 0 else "")
    )
    return True


def import_cameras_from_manifest(
    manifest_abs_path: str | None = None,
    *,
    content_root: str = DEFAULT_CONTENT_ROOT,
    max_cameras: int = 8,
    show_dialog: bool = True,
) -> int:
    """
    读取清单（默认 ``houdini_camera_manifest.default_fixed_manifest_abs_path()``），
    再经 USD Stage Editor 导入合并 USDA 或逐机 USDA（磁盘上的 USDA 文件不改写）。

    关卡中 LevelSequenceActor / 相机位置等由 EUW 蓝图自行处理。
    """
    if manifest_abs_path is None or not str(manifest_abs_path).strip():
        manifest_abs_path = houdini_camera_manifest.default_fixed_manifest_abs_path()
    try:
        data = houdini_camera_manifest.load_manifest(manifest_abs_path)
    except Exception as exc:  # noqa: BLE001
        unreal.log_error(f"{_LOG_PREFIX} manifest load failed: {exc!r}")
        return 0

    errs = houdini_camera_manifest.validate_manifest(data)
    if errs:
        for e in errs:
            unreal.log_error(f"{_LOG_PREFIX} {e}")
        return 0

    base = Path(manifest_abs_path).resolve().parent
    cams = data.get("cameras") or []
    if not isinstance(cams, list):
        return 0

    ensure_content_dir(content_root)
    purge_houdini_camera_import_before_reimport(content_root)
    opts = build_import_options()
    ok = 0

    merged_usda_path = houdini_camera_manifest.merged_usda_file_for_import(data, manifest_abs_path)
    if merged_usda_path is not None:
        if not merged_usda_path.is_file():
            unreal.log_error(f"{_LOG_PREFIX} merged USDA missing: {merged_usda_path}")
            return 0
        dest = content_root.rstrip("/")
        if import_usda_to_content(str(merged_usda_path.resolve()), dest, options=opts):
            ok = 1
    else:
        for cam in cams[: max(0, int(max_cameras))]:
            if not isinstance(cam, dict):
                continue
            rel = cam.get("usda_relative")
            name = cam.get("display_name") or "cam"
            rel_s = str(rel).strip() if rel is not None else ""
            if not rel_s:
                continue
            usda = base / rel_s
            if not usda.is_file():
                unreal.log_warning(f"{_LOG_PREFIX} skip missing usda: {usda}")
                continue
            dest = f"{content_root.rstrip('/')}/{_safe_folder_segment(name)}"
            if import_usda_to_content(str(usda.resolve()), dest, options=opts):
                ok += 1

    unreal.log_warning(f"{_LOG_PREFIX} batch done | imported={ok}")

    if show_dialog:
        try:
            merged = houdini_camera_manifest.manifest_uses_merged_usda(data)
            hint = (
                "Merged USDA: Level Sequence(s) under import root (flat by asset type).\n"
                if merged
                else "Per-camera USDA folders.\n"
            )
            unreal.EditorDialog.show_message(
                title=unreal.Text("Houdini camera — import"),
                message=unreal.Text(
                    f"Import batches completed: {ok}\nRoot: {content_root}\n{hint}"
                    "Check Content Browser -> houdini_camera."
                ),
                message_type=unreal.AppMsgType.OK,
                default_value=unreal.AppReturnType.OK,
            )
        except Exception as exc:
            unreal.log_error(f"{_LOG_PREFIX} dialog: {exc!r}")

    return ok
