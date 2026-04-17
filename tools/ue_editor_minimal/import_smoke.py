# -*- coding: utf-8 -*-
"""
Import USD (USDA) into Content via USD Stage Editor API — assets under /Game/houdini_camera/...

Uses unreal.UsdStageEditorLibrary:
  open_stage_editor -> file_open(usda) -> actions_import(content_folder, options) -> file_close

Copy to: <YourProject>/Content/Python/import_smoke.py
Requires: manifest_smoke.py (for manifest-driven batch).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import unreal

import manifest_smoke

PREFIX = "[import_smoke]"

# Default Content path (matches student spec: houdini_camera folder under Content)
DEFAULT_CONTENT_ROOT = "/Game/houdini_camera"


def _safe_folder_segment(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_]", "_", str(name))
    return s or "Camera"


def ensure_content_dir(content_path: str) -> None:
    """Create /Game/... folder if missing."""
    if not unreal.EditorAssetLibrary.does_directory_exist(content_path):
        unreal.EditorAssetLibrary.make_directory(content_path)
        unreal.log_warning(f"{PREFIX} created Content folder: {content_path}")


def build_import_options() -> unreal.UsdStageImportOptions:
    """Defaults tuned for Houdini camera USDA (matrix + imaging), minimal geometry."""
    o = unreal.UsdStageImportOptions()
    # False: avoid mirroring /World/... prim paths as deep Content folders; assets
    # group by type (e.g. LevelSequences) under the import root instead.
    try:
        o.set_editor_property("prim_path_folder_structure", False)
    except Exception:
        pass
    # Actors + Level Sequences help camera / animation land in Content & level.
    o.set_editor_property("import_actors", True)
    o.set_editor_property("import_level_sequences", True)
    o.set_editor_property("import_geometry", False)
    o.set_editor_property("import_materials", True)
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
        unreal.log_error(f"{PREFIX} file not found: {p}")
        return False
    disk_path = str(p.resolve())

    ensure_content_dir(content_dest)
    opts = options or build_import_options()

    try:
        unreal.UsdStageEditorLibrary.open_stage_editor()
        unreal.UsdStageEditorLibrary.file_open(disk_path)
        unreal.UsdStageEditorLibrary.actions_import(content_dest, opts)
    except Exception as exc:  # noqa: BLE001
        unreal.log_error(f"{PREFIX} import failed for {disk_path}: {exc!r}")
        try:
            unreal.UsdStageEditorLibrary.file_close()
        except Exception:
            pass
        return False

    try:
        unreal.UsdStageEditorLibrary.file_close()
    except Exception:
        pass

    unreal.log_warning(f"{PREFIX} imported -> {content_dest} | source={disk_path}")
    return True


def import_manifest_cameras(
    manifest_abs_path: str,
    *,
    content_root: str = DEFAULT_CONTENT_ROOT,
    max_cameras: int = 8,
    show_dialog: bool = True,
) -> int:
    """
    For each entry in manifest cameras[], import usda into
    {content_root}/{display_name}/ via USD Stage Editor.
    Returns number of successful imports.
    """
    try:
        data = manifest_smoke.load_manifest(manifest_abs_path)
    except Exception as exc:  # noqa: BLE001
        unreal.log_error(f"{PREFIX} manifest load failed: {exc!r}")
        return 0

    errs = manifest_smoke.validate_manifest(data)
    if errs:
        for e in errs:
            unreal.log_error(f"{PREFIX} {e}")
        return 0

    base = Path(manifest_abs_path).resolve().parent
    cams = data.get("cameras") or []
    if not isinstance(cams, list):
        return 0

    ensure_content_dir(content_root)
    opts = build_import_options()
    ok = 0

    merged_rel = manifest_smoke.merged_usda_relative_for_import(data)
    if merged_rel:
        usda = base / str(merged_rel)
        if not usda.is_file():
            unreal.log_error(f"{PREFIX} merged USDA missing: {usda}")
            return 0
        # Single flat root: Level Sequences land under content_root (e.g. /Game/houdini_camera),
        # not an extra HoudiniCameraShoot / World / ... mirror (see prim_path_folder_structure).
        dest = content_root.rstrip("/")
        if import_usda_to_content(str(usda.resolve()), dest, options=opts):
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
                unreal.log_warning(f"{PREFIX} skip missing usda: {usda}")
                continue
            dest = f"{content_root.rstrip('/')}/{_safe_folder_segment(name)}"
            if import_usda_to_content(str(usda.resolve()), dest, options=opts):
                ok += 1

    unreal.log_warning(f"{PREFIX} batch done | imported={ok}")

    if show_dialog:
        try:
            merged = manifest_smoke.manifest_uses_merged_usda(data)
            hint = (
                "Merged USDA: Level Sequence(s) under import root (flat by asset type).\n"
                if merged
                else "Per-camera USDA folders.\n"
            )
            unreal.EditorDialog.show_message(
                title=unreal.Text("import smoke"),
                message=unreal.Text(
                    f"Import batches completed: {ok}\nRoot: {content_root}\n{hint}"
                    "Check Content Browser -> houdini_camera."
                ),
                message_type=unreal.AppMsgType.OK,
                default_value=unreal.AppReturnType.OK,
            )
        except Exception as exc:
            unreal.log_error(f"{PREFIX} dialog: {exc!r}")

    return ok
