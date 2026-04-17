# -*- coding: utf-8 -*-
"""
写出带逐帧相机矩阵与成像属性的 USDA，供 UE 5.5 USD Stage / Sequencer 使用。

USD Camera 与成像模式说明：
https://openusd.org/release/api/usd_geom_page_front.html#usdgeom_camera
"""

from __future__ import annotations

import re

import hou
from pxr import Gf, Usd, UsdGeom

from .compute import camera_xform_pipeline
from .coords import DEFAULT_EXPORT_METERS_PER_UNIT, length_scale_factor
from .transform_log import format_pose_block
from .sampling import obj_camera_intrinsics, obj_camera_world_matrix

# 合并导出：单 USDA 文件名（与 manifest ``merged_usda_relative`` 一致）
MERGED_USDA_FILENAME = "houdini_cameras_merged.usda"


def safe_camera_prim_segment(name: str) -> str:
    """
    将显示名转为 USD prim 路径段：仅字母数字下划线，且不以数字开头。

    :param name: 原始相机名或显示名。
    :return: 安全的路径段字符串。
    """
    s = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if s and s[0].isdigit():
        s = "_" + s
    return s or "Camera"


def _log_call(log, msg: str) -> None:
    """若提供了 ``log`` 可调用对象，则写入一行（通常为面板回调）。"""
    if log:
        log(msg)


def _intrinsics_lines(intr: dict, export_mpu: float, prefix: str = "  ") -> list[str]:
    """
    把成像字典格式化为多行英文说明，写入导出日志（避免面板编码问题）。

    :param intr: ``obj_camera_intrinsics`` 的返回值。
    :param export_mpu: 导出 Stage 的 ``metersPerUnit``。
    :param prefix: 每行前缀空格。
    """
    near_usd = float(intr["clip_near_m"]) / export_mpu
    far_usd = float(intr["clip_far_m"]) / export_mpu
    proj = intr.get("projection") or "perspective"
    lines = [
        f"{prefix}[imaging] projection={proj}",
        f"{prefix}  source: focal={intr['focal_length_mm']:.6g} mm, "
        f"hap={intr['horizontal_aperture_mm']:.6g} mm, vap={intr['vertical_aperture_mm']:.6g} mm",
        f"{prefix}  source: clip_near={intr['clip_near_m']:.6g} m, clip_far={intr['clip_far_m']:.6g} m",
        f"{prefix}  -> USD: clippingRange=({near_usd:.6g}, {far_usd:.6g}) (stage length units, mpu={export_mpu})",
    ]
    fd = intr.get("focus_distance_m")
    if fd is not None:
        d_usd = float(fd) / export_mpu
        lines.append(
            f"{prefix}  source: focus_distance={float(fd):.6g} m -> focusDistance={d_usd:.6g} (stage units)"
        )
    fs = intr.get("f_stop")
    if fs is not None:
        lines.append(f"{prefix}  source: fStop={float(fs):.6g} -> USD fStop (same value)")
    ow = intr.get("ortho_width_m")
    if ow is not None and proj == "orthographic":
        ow_usd = float(ow) / export_mpu
        lines.append(
            f"{prefix}  source: ortho_width={float(ow):.6g} m -> orthographicWidth={ow_usd:.6g} (stage units)"
        )
    lines.append(f"{prefix}  source tag: {intr.get('source')} path={intr.get('source_path')!r}")
    return lines


def _clip_attr(cam: UsdGeom.Camera):
    """获取或创建相机的 ``clippingRange`` USD 属性。"""
    a = cam.GetClippingRangeAttr()
    if a and a.IsValid():
        return a
    return cam.CreateClippingRangeAttr()


def _set_projection_and_lens(cam: UsdGeom.Camera, intr: dict, tc: Usd.TimeCode, export_mpu: float) -> None:
    """
    在指定 time code 上设置投影模式、焦距/光圈（毫米）及裁剪（舞台长度单位）。

    :param cam: USD Camera schema 对象。
    :param intr: 成像参数字典。
    :param tc: 采样时间码。
    :param export_mpu: 导出 ``metersPerUnit``，用于米 → 舞台单位换算。
    """
    proj = intr.get("projection") or "perspective"
    if proj == "orthographic":
        cam.GetProjectionAttr().Set(UsdGeom.Tokens.orthographic, tc)
        ow_m = intr.get("ortho_width_m")
        if ow_m is not None:
            ow_usd = float(ow_m) / export_mpu
            try:
                oa = cam.GetOrthographicWidthAttr()
                if not oa or not oa.IsValid():
                    oa = cam.CreateOrthographicWidthAttr(ow_usd)
                oa.Set(ow_usd, tc)
            except Exception:
                pass
    else:
        cam.GetProjectionAttr().Set(UsdGeom.Tokens.perspective, tc)

    cam.GetFocalLengthAttr().Set(float(intr["focal_length_mm"]), tc)
    cam.GetHorizontalApertureAttr().Set(float(intr["horizontal_aperture_mm"]), tc)
    cam.GetVerticalApertureAttr().Set(float(intr["vertical_aperture_mm"]), tc)

    near_usd = float(intr["clip_near_m"]) / export_mpu
    far_usd = float(intr["clip_far_m"]) / export_mpu
    _clip_attr(cam).Set(Gf.Vec2f(near_usd, far_usd), tc)

    fd = intr.get("focus_distance_m")
    if fd is not None:
        d_usd = float(fd) / export_mpu
        fa = cam.GetFocusDistanceAttr()
        if not fa or not fa.IsValid():
            fa = cam.CreateFocusDistanceAttr(d_usd)
        fa.Set(d_usd, tc)

    fs = intr.get("f_stop")
    if fs is not None:
        sa = cam.GetFStopAttr()
        if not sa or not sa.IsValid():
            sa = cam.CreateFStopAttr(float(fs))
        sa.Set(float(fs), tc)


def _set_sidecar_metadata(prim, intr: dict) -> None:
    """
    在 prim 的 customData 中写入 ``houdini_ue_camera`` 小块 JSON 元数据，便于 UE 侧追溯来源。

    :param prim: USD Prim。
    :param intr: 成像字典（需含 ``source`` / ``source_path``）。
    """
    payload = {
        "pipeline": "houdini_ue55",
        "source": intr.get("source"),
        "sourcePath": intr.get("source_path"),
    }
    ct = intr.get("color_temperature_K")
    if ct is not None:
        payload["colorTemperature_K"] = float(ct)
    try:
        prim.SetCustomDataByKey("houdini_ue_camera", payload)
    except Exception:
        try:
            cur = dict(prim.GetCustomData()) if prim.GetCustomData() else {}
            cur["houdini_ue_camera"] = payload
            prim.SetCustomData(cur)
        except Exception:
            pass


def export_merged_cameras_for_ue55(
    output_path,
    *,
    camera_obj_paths: list[str],
    frame_start: int = 1,
    frame_end: int = 24,
    frame_step: int = 1,
    fps: float = 24.0,
    export_meters_per_unit: float = DEFAULT_EXPORT_METERS_PER_UNIT,
    source_meters_per_unit: float = 1.0,
    apply_ue_post_matrix: bool = False,
    pivot_world_meters=None,
    log=None,
    transpose_xform_for_ue_import: bool = True,
):
    """
    将多台 ``/obj`` 相机写入**单个** USDA：每台 ``UsdGeom.Camera`` 位于 ``/World/<safe_basename>``。

    与逐机多文件相比，UE 侧一次 ``actions_import`` 更易得到**一个** Level Sequence 内含多机；
    相机 prim 名使用 Houdini 节点 basename（经 ``safe_camera_prim_segment`` 清洗）。

    :param output_path: 合并 ``.usda`` 路径。
    :param camera_obj_paths: 相机节点路径列表（非空）。
    """
    if not camera_obj_paths:
        raise ValueError("camera_obj_paths must be non-empty")

    out = str(output_path)
    stage = Usd.Stage.CreateNew(out)
    UsdGeom.SetStageMetersPerUnit(stage, float(export_meters_per_unit))
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    stage.SetFramesPerSecond(float(fps))
    if hasattr(stage, "SetTimeCodesPerSecond"):
        stage.SetTimeCodesPerSecond(float(fps))

    root_layer = stage.GetRootLayer()
    try:
        root_layer.startTimeCode = float(frame_start)
        root_layer.endTimeCode = float(frame_end)
    except Exception:
        pass

    src_mpu_obj = float(source_meters_per_unit)
    exp_mpu = float(export_meters_per_unit)
    fscale = length_scale_factor(src_mpu_obj, exp_mpu)
    step = max(1, int(frame_step or 1))

    _log_call(
        log,
        "[export merged] Houdini -> UE 5.5 multi-camera single USDA\n"
        f"  output: {out}\n"
        f"  cameras: {len(camera_obj_paths)}\n"
        f"  frames: {frame_start}-{frame_end}  step={step}  fps={fps}\n"
        f"  export_metersPerUnit={exp_mpu}\n"
        f"  source_metersPerUnit={src_mpu_obj}\n"
        f"  world-matrix length scale (source -> export stage): {fscale:.10g}\n"
        f"  apply_ue_post_matrix={apply_ue_post_matrix}\n"
        f"  transpose_xform_for_ue_import={transpose_xform_for_ue_import}",
    )
    if pivot_world_meters is None:
        _log_call(log, "  pivot_world_meters=None (no pivot offset)")
    else:
        pv = tuple(float(x) for x in pivot_world_meters[:3])
        _log_call(
            log,
            f"  pivot_world_meters={pv} m — applied as T(-pivot)*M before compose_export (see per-frame after_pivot_world_m)",
        )

    UsdGeom.Xform.Define(stage, "/World")
    cams_runtime: list[tuple[str, str, UsdGeom.Camera, object]] = []
    for obj_path in camera_obj_paths:
        display = obj_path.strip().split("/")[-1] or "cam"
        seg = safe_camera_prim_segment(display)
        cam_path = f"/World/{seg}"
        cam_schema = UsdGeom.Camera.Define(stage, cam_path)
        xf = UsdGeom.Xformable(cam_schema.GetPrim())
        xop = xf.MakeMatrixXform()
        cams_runtime.append((obj_path, seg, cam_schema, xop))
        _log_call(log, f"  prim: {cam_path}  <=  {obj_path!r}")

    first_intr_done: set[str] = set()
    prev_intr_key: dict[str, tuple] = {}

    for f in range(int(frame_start), int(frame_end) + 1, step):
        tc = Usd.TimeCode(float(f))
        for obj_path, seg, cam_schema, xop in cams_runtime:
            raw_world = obj_camera_world_matrix(obj_path, f)
            intr = obj_camera_intrinsics(obj_path, f)

            if seg not in first_intr_done:
                first_intr_done.add(seg)
                _log_call(log, f"[first frame | {seg}] intrinsics summary (source -> USD):")
                for line in _intrinsics_lines(intr, exp_mpu, prefix="  "):
                    _log_call(log, line)
                _set_sidecar_metadata(cam_schema.GetPrim(), intr)

            m_write, steps = camera_xform_pipeline(
                raw_world,
                pivot_world_meters=pivot_world_meters,
                source_meters_per_unit=src_mpu_obj,
                export_meters_per_unit=export_meters_per_unit,
                Gf=Gf,
                apply_ue_post_matrix=apply_ue_post_matrix,
                transpose_xform_for_ue_import=transpose_xform_for_ue_import,
            )
            xop.Set(m_write, tc)
            _set_projection_and_lens(cam_schema, intr, tc, export_meters_per_unit)

            intr_key = (
                intr.get("projection"),
                round(float(intr["focal_length_mm"]), 6),
                round(float(intr["horizontal_aperture_mm"]), 6),
                round(float(intr["vertical_aperture_mm"]), 6),
                round(float(intr["clip_near_m"]), 6),
                round(float(intr["clip_far_m"]), 6),
            )
            intr_changed = prev_intr_key.get(seg) != intr_key
            prev_intr_key[seg] = intr_key

            _log_call(log, f"-- {seg} | frame {f} (timeCode={float(f)}) --")
            for line in format_pose_block(f"  [RAW] {seg} | source world (m)", raw_world):
                _log_call(log, line)
            for step_name, smat in steps:
                for line in format_pose_block(f"  [COMPUTED] {step_name} | {seg}", smat):
                    _log_call(log, line)
            if intr_changed:
                _log_call(log, f"  [{seg}] intrinsics changed vs previous frame:")
                for line in _intrinsics_lines(intr, exp_mpu, prefix="    "):
                    _log_call(log, line)

    world_root = stage.GetPrimAtPath("/World")
    if world_root and world_root.IsValid():
        stage.SetDefaultPrim(world_root)

    stage.GetRootLayer().documentation = (
        "Houdini merged multi-camera -> UE 5.5. metersPerUnit=%s. One import recommended for single Level Sequence."
        % export_meters_per_unit
    )
    stage.Save()
    _log_call(
        log,
        "[metadata] merged USDA saved | defaultPrim=/World | "
        f"startTimeCode={root_layer.startTimeCode} endTimeCode={root_layer.endTimeCode}",
    )
    _log_call(
        log,
        "[UE import] houdini_camera_manifest + houdini_camera_usd_import: merged_usda_relative then import into "
        "/Game/houdini_camera (or your content_root).",
    )


def list_obj_cameras_for_ui() -> list[str]:
    """
    为面板列出 ``/obj`` 下所有 ``cam`` 类型节点路径（排序）。

    :return: 路径字符串列表。
    """
    root = hou.node("/obj")
    if root is None:
        return []
    cam_type = hou.nodeType(hou.objNodeTypeCategory(), "cam")
    paths: list[str] = []
    for n in root.allSubChildren():
        if n.type() == cam_type:
            paths.append(n.path())
    return sorted(paths)
