# -*- coding: utf-8 -*-
"""
Read and validate houdini_ue_camera_manifest.json (same schema as Houdini pipeline panel).

Copy to: <YourProject>/Content/Python/manifest_smoke.py

Usage (Output Log → Python):
    import manifest_smoke
    manifest_smoke.run_manifest_smoke(r"C:\\path\\to\\folder\\houdini_ue_camera_manifest.json")
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import unreal

MANIFEST_FILENAME = "houdini_ue_camera_manifest.json"
# 与 Houdini ``houdini_ue_camera.usd_writer.MERGED_USDA_FILENAME`` 一致（UE 侧不 import 该包）
DEFAULT_MERGED_USDA_RELATIVE = "houdini_cameras_merged.usda"


def _effective_usda_relative(cam: dict[str, Any]) -> str | None:
    """每台相机的 USDA 相对路径；``null`` / 缺省 / 空串视为无（走合并 USDA）。"""
    if "usda_relative" not in cam:
        return None
    v = cam.get("usda_relative")
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def manifest_uses_merged_usda(data: dict[str, Any]) -> bool:
    """
    是否按「合并 USDA」管线：``export.merged_usda_relative`` 非空，或每台相机行
    具备 ``usd_prim_path`` 且 **无有效** ``usda_relative``（兼容键存在但为 ``null`` / ``""`` 的 JSON）。
    """
    exp = data.get("export")
    if isinstance(exp, dict) and str(exp.get("merged_usda_relative") or "").strip():
        return True
    cams = data.get("cameras") or []
    if not isinstance(cams, list) or not cams:
        return False

    def _cam_row_is_merged_style(c: Any) -> bool:
        if not isinstance(c, dict):
            return False
        if _effective_usda_relative(c) is not None:
            return False
        return "obj_path" in c and "display_name" in c and "usd_prim_path" in c

    return all(_cam_row_is_merged_style(c) for c in cams)


def merged_usda_relative_for_import(data: dict[str, Any]) -> str | None:
    """若合并模式，返回应导入的 USDA 相对路径字符串；否则 ``None``。"""
    if not manifest_uses_merged_usda(data):
        return None
    exp = data.get("export") or {}
    if not isinstance(exp, dict):
        return DEFAULT_MERGED_USDA_RELATIVE
    rel = exp.get("merged_usda_relative")
    return str(rel).strip() if rel else DEFAULT_MERGED_USDA_RELATIVE


def _as_path(manifest_abs: str) -> Path:
    p = Path(os.path.expandvars(manifest_abs.strip().strip('"')))
    if not p.is_absolute():
        raise ValueError(f"manifest path must be absolute: {manifest_abs!r}")
    return p


def load_manifest(manifest_abs: str) -> dict[str, Any]:
    """Load JSON from disk; raises on missing file or invalid JSON."""
    path = _as_path(manifest_abs)
    if not path.is_file():
        raise FileNotFoundError(f"manifest not found: {path}")
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("manifest root must be a JSON object")
    return data


def validate_manifest(data: dict[str, Any]) -> list[str]:
    """Return list of error strings; empty means OK."""
    errors: list[str] = []
    ver = data.get("schema_version")
    if ver != 1:
        errors.append(f"schema_version must be 1, got {ver!r}")

    exp = data.get("export")
    if not isinstance(exp, dict):
        errors.append("missing or invalid 'export' object")
    else:
        for key in (
            "fps",
            "frame_start",
            "frame_end",
            "frame_step",
            "export_meters_per_unit",
        ):
            if key not in exp:
                errors.append(f"export.{key} missing")

    merged = manifest_uses_merged_usda(data)

    cams = data.get("cameras")
    if not isinstance(cams, list) or len(cams) == 0:
        errors.append("'cameras' must be a non-empty list")
    else:
        for i, c in enumerate(cams):
            if not isinstance(c, dict):
                errors.append(f"cameras[{i}] must be object")
                continue
            if merged:
                for k in ("obj_path", "display_name", "usd_prim_path"):
                    if k not in c:
                        errors.append(f"cameras[{i}].{k} missing")
            else:
                for k in ("obj_path", "display_name"):
                    if k not in c:
                        errors.append(f"cameras[{i}].{k} missing")
                if _effective_usda_relative(c) is None:
                    errors.append(f"cameras[{i}].usda_relative missing or empty")

    return errors


def check_usda_files(manifest_path: str, data: dict[str, Any]) -> list[str]:
    """Return warnings for each missing .usda next to manifest (merged or per-camera)."""
    warnings: list[str] = []
    base = _as_path(manifest_path).parent
    if manifest_uses_merged_usda(data):
        rel = merged_usda_relative_for_import(data) or DEFAULT_MERGED_USDA_RELATIVE
        fp = base / str(rel)
        if not fp.is_file():
            warnings.append(f"missing merged file: {fp}")
        return warnings

    cams = data.get("cameras") or []
    if not isinstance(cams, list):
        return warnings
    for c in cams:
        if not isinstance(c, dict):
            continue
        rel = c.get("usda_relative")
        if not rel:
            continue
        fp = base / str(rel)
        if not fp.is_file():
            warnings.append(f"missing file: {fp}")
    return warnings


def run_manifest_smoke(manifest_abs_path: str, *, show_dialog: bool = True) -> bool:
    """
    Load manifest, validate schema, check sibling .usda files, log summary.
    Returns True if validation passed (missing .usda only warns, still True if schema OK).
    """
    prefix = "[manifest_smoke]"
    try:
        data = load_manifest(manifest_abs_path)
    except Exception as exc:  # noqa: BLE001
        unreal.log_error(f"{prefix} load failed: {exc!r}")
        if show_dialog:
            try:
                unreal.EditorDialog.show_message(
                    title=unreal.Text("manifest smoke"),
                    message=unreal.Text(f"Load failed:\n{exc}"),
                    message_type=unreal.AppMsgType.OK,
                    default_value=unreal.AppReturnType.OK,
                )
            except Exception:
                pass
        return False

    errs = validate_manifest(data)
    if errs:
        for e in errs:
            unreal.log_error(f"{prefix} {e}")
        if show_dialog:
            try:
                unreal.EditorDialog.show_message(
                    title=unreal.Text("manifest smoke"),
                    message=unreal.Text("Validation failed:\n" + "\n".join(errs[:12])),
                    message_type=unreal.AppMsgType.OK,
                    default_value=unreal.AppReturnType.OK,
                )
            except Exception:
                pass
        return False

    missing = check_usda_files(manifest_abs_path, data)
    for w in missing:
        unreal.log_warning(f"{prefix} {w}")

    exp = data.get("export") or {}
    cams = data.get("cameras") or []
    unreal.log_warning(
        f"{prefix} OK | cameras={len(cams)} | "
        f"frames={exp.get('frame_start')}..{exp.get('frame_end')} step={exp.get('frame_step')} "
        f"fps={exp.get('fps')} mpu={exp.get('export_meters_per_unit')}"
    )

    if show_dialog:
        try:
            msg = (
                f"Manifest OK.\n"
                f"Cameras: {len(cams)}\n"
                f"Frames: {exp.get('frame_start')}-{exp.get('frame_end')} step={exp.get('frame_step')}\n"
                f"Missing usda files: {len(missing)}"
            )
            unreal.EditorDialog.show_message(
                title=unreal.Text("manifest smoke"),
                message=unreal.Text(msg),
                message_type=unreal.AppMsgType.OK,
                default_value=unreal.AppReturnType.OK,
            )
        except Exception as exc:
            unreal.log_error(f"{prefix} dialog: {exc!r}")

    return True
