# -*- coding: utf-8 -*-
"""
从 Houdini OBJ 相机或 Solaris LOP 上的 USD Camera 读取逐帧世界矩阵与成像参数。

面向 ``usd_writer.export_camera_for_ue55``；抛给用户的异常信息保持英文，便于面板日志显示。
"""

from __future__ import annotations

import hou
from pxr import Gf, Usd, UsdGeom

from .matrix import world_transform_at_frame


def _parm_eval_float(node: hou.Node, names: tuple[str, ...], default: float | None = None) -> float | None:
    """
    按候选参数名顺序读取第一个存在的 float 型参数值。

    :param node: Houdini 节点。
    :param names: 参数名元组（如 ``("focal",)``）。
    :param default: 全部不存在时的默认值。
    :return: 求值结果或 ``default``。
    """
    for n in names:
        p = node.parm(n)
        if p is not None:
            return float(p.eval())
    return default


def _parm_eval_exists(node: hou.Node, name: str) -> bool:
    """判断节点上是否存在名为 ``name`` 的参数。"""
    p = node.parm(name)
    return p is not None


def _obj_render_resolution_xy(node: hou.Node) -> tuple[float | None, float | None]:
    """
    读取 OBJ 相机「渲染分辨率」宽高（像素）。

    官方参数为 ``res``（tuple）；另尝试常见备用名。与 ``aspect``（像素宽高比）一起用于
    按 Houdini 公式 ``ap_y = (res_y * ap_x) / (res_x * pixel_aspect)`` 推算垂直光圈。
    """
    pt = node.parmTuple("res")
    if pt is not None and len(pt) >= 2:
        try:
            rx, ry = float(pt[0].eval()), float(pt[1].eval())
            if rx > 1e-9 and ry > 1e-9:
                return rx, ry
        except Exception:
            pass
    for rx_name, ry_name in (
        ("resx", "resy"),
        ("res1", "res2"),
        ("xres", "yres"),
        ("sizex", "sizey"),
    ):
        rx = _parm_eval_float(node, (rx_name,), None)
        ry = _parm_eval_float(node, (ry_name,), None)
        if rx is not None and ry is not None and rx > 1e-9 and ry > 1e-9:
            return float(rx), float(ry)
    return None, None


def obj_camera_world_matrix(node_path: str, frame: int):
    """
    读取 ``/obj/...`` 相机节点在指定帧的世界矩阵（``Gf.Matrix4d``，列向量约定）。

    :param node_path: 相机节点路径。
    :param frame: 帧号。
    :raises ValueError: 节点不存在。
    """
    n = hou.node(node_path)
    if n is None:
        raise ValueError(f"Node not found: {node_path}")
    return world_transform_at_frame(n, frame, Gf)


def obj_camera_intrinsics(node_path: str, frame: int) -> dict:
    """
    读取 OBJ 相机常用成像参数，返回字典（焦距/光圈为毫米，裁剪/正交宽度为米）。

    水平光圈来自 ``aperture``（毫米）。垂直光圈按 Houdini 与 Mantra 一致的关系由分辨率与
    **像素宽高比** ``aspect``（非图像宽高比）推算：
    ``vertical = horizontal * res_y / (res_x * pixel_aspect)``。
    若读不到分辨率则退回 ``vertical = horizontal``（与旧版错误行为在 PAR=1 时相同，仅作兜底）。

    正交判定：``orthowidth`` > 0。

    :param node_path: 相机节点路径。
    :param frame: 设置当前帧后求值。
    :return: 内含 ``projection``、``focal_length_mm``、裁剪、可选 ``focus_distance_m`` 等键。
    :raises ValueError: 节点不存在。
    """
    hou.setFrame(int(frame))
    n = hou.node(node_path)
    if n is None:
        raise ValueError(f"Node not found: {node_path}")

    focal_mm = _parm_eval_float(n, ("focal",), 35.0)
    hap_mm = _parm_eval_float(n, ("aperture",), 36.0)
    # 官方文档：View → Pixel aspect ratio，参数名 ``aspect``（IFD image:pixelaspect）
    pixel_aspect = _parm_eval_float(n, ("aspect",), 1.0)
    if pixel_aspect is None or pixel_aspect < 1e-9:
        pixel_aspect = 1.0
    resx, resy = _obj_render_resolution_xy(n)
    if resx is not None and resy is not None:
        vap_mm = float(hap_mm) * float(resy) / (float(resx) * float(pixel_aspect))
    else:
        vap_mm = float(hap_mm)

    near_m = _parm_eval_float(n, ("near", "vnear"), 0.01)
    far_m = _parm_eval_float(n, ("far", "vfar"), 10000.0)
    focus_m = _parm_eval_float(n, ("focus",), None)
    fstop = _parm_eval_float(n, ("fstop",), None)
    temp_k = None
    for tname in ("colortemperature", "temperature", "whitebalance", "wb_temperature"):
        if _parm_eval_exists(n, tname):
            temp_k = _parm_eval_float(n, (tname,), None)
            break

    ortho_w = _parm_eval_float(n, ("orthowidth",), 0.0)
    ortho = ortho_w is not None and ortho_w > 1e-9

    return {
        "projection": "orthographic" if ortho else "perspective",
        "focal_length_mm": float(focal_mm),
        "horizontal_aperture_mm": float(hap_mm),
        "vertical_aperture_mm": float(vap_mm),
        "clip_near_m": float(near_m),
        "clip_far_m": float(far_m),
        "focus_distance_m": focus_m,
        "f_stop": fstop,
        "color_temperature_K": temp_k,
        "ortho_width_m": float(ortho_w) if ortho else None,
        "source": "houdini_obj",
        "source_path": n.path(),
    }


def usd_stage_from_lop(lop_path: str) -> Usd.Stage:
    """
    从 Solaris LOP 节点获取已烹饪的 ``Usd.Stage``（``hou.LopNode.stage()``）。

    :param lop_path: LOP 节点路径。
    :raises ValueError: 节点不存在。
    :raises RuntimeError: 节点上无可用 stage（需先烹饪或有效 LOP 网络）。
    """
    n = hou.node(lop_path)
    if n is None:
        raise ValueError(f"LOP node not found: {lop_path}")
    st = n.stage()
    if st is None:
        raise RuntimeError(
            f"No USD stage on node (cook first / use a valid Solaris LOP): {lop_path}"
        )
    return st


def list_usd_camera_prim_paths(stage: Usd.Stage) -> list[str]:
    """
    遍历舞台上所有 ``UsdGeom.Camera`` prim，返回其路径字符串列表（排序后）。

    :param stage: USD Stage。
    """
    out: list[str] = []
    for prim in stage.Traverse():
        if prim.IsA(UsdGeom.Camera):
            out.append(prim.GetPath().pathString)
    return sorted(out)


def usd_camera_world_matrix(stage: Usd.Stage, prim_path: str, frame: int, time_code_as_float: bool = True):
    """
    计算指定 prim 在给定帧的局部到世界变换矩阵（``Gf.Matrix4d``）。

    :param stage: USD Stage。
    :param prim_path: Camera prim 路径。
    :param frame: 帧号；作为 ``Usd.TimeCode`` 传入。
    :param time_code_as_float: 是否用浮点 time code（与稀疏采样策略一致）。
    :raises ValueError: prim 无效。
    """
    prim = stage.GetPrimAtPath(prim_path)
    if not prim or not prim.IsValid():
        raise ValueError(f"Invalid prim: {prim_path}")
    xf = UsdGeom.Xformable(prim)
    tc = Usd.TimeCode(float(frame) if time_code_as_float else frame)
    return xf.ComputeLocalToWorldTransform(tc)


def usd_intrinsics_from_prim(stage: Usd.Stage, prim_path: str, frame: int) -> dict:
    """
    从 USD Camera prim 读取成像参数，并换算为米制裁剪、毫米焦距/光圈等统一字典格式。

    ``focusDistance`` 等按舞台 ``metersPerUnit`` 转为米。与 ``obj_camera_intrinsics`` 返回结构对齐，
    供 ``usd_writer`` 写入 USDA。

    :param stage: USD Stage。
    :param prim_path: Camera prim 路径。
    :param frame: 采样帧。
    :raises ValueError: prim 不存在或无效。
    """
    prim = stage.GetPrimAtPath(prim_path)
    if not prim or not prim.IsValid():
        raise ValueError(f"Invalid prim: {prim_path}")
    cam = UsdGeom.Camera(prim)
    tc = Usd.TimeCode(float(frame))

    focal = cam.GetFocalLengthAttr().Get(tc)
    hap = cam.GetHorizontalApertureAttr().Get(tc)
    vap = cam.GetVerticalApertureAttr().Get(tc)
    proj = cam.GetProjectionAttr().Get(tc)
    if focal is None:
        focal = cam.GetFocalLengthAttr().Get(Usd.TimeCode.Default())
    if hap is None:
        hap = cam.GetHorizontalApertureAttr().Get(Usd.TimeCode.Default())
    if vap is None:
        vap = cam.GetVerticalApertureAttr().Get(Usd.TimeCode.Default())

    mpu = float(UsdGeom.GetStageMetersPerUnit(stage))

    near_far = None
    cr = cam.GetClippingRangeAttr()
    if cr:
        near_far = cr.Get(tc)
        if near_far is None:
            near_far = cr.Get(Usd.TimeCode.Default())

    focus_m = None
    fd = cam.GetFocusDistanceAttr() if hasattr(cam, "GetFocusDistanceAttr") else None
    if fd:
        raw_fd = fd.Get(tc)
        if raw_fd is None:
            raw_fd = fd.Get(Usd.TimeCode.Default())
        if raw_fd is not None:
            focus_m = float(raw_fd) * mpu

    fstop_val = None
    fs = cam.GetFStopAttr() if hasattr(cam, "GetFStopAttr") else None
    if fs:
        fstop_val = fs.Get(tc)
        if fstop_val is None:
            fstop_val = fs.Get(Usd.TimeCode.Default())

    ow = None
    ow_attr = cam.GetOrthographicWidthAttr() if hasattr(cam, "GetOrthographicWidthAttr") else None
    if ow_attr:
        ow = ow_attr.Get(tc)
        if ow is None:
            ow = ow_attr.Get(Usd.TimeCode.Default())

    projection = "perspective"
    if proj == UsdGeom.Tokens.orthographic:
        projection = "orthographic"
    elif proj == UsdGeom.Tokens.perspective:
        projection = "perspective"

    near_m = far_m = None
    if near_far is not None:
        near_m = float(near_far[0]) * mpu
        far_m = float(near_far[1]) * mpu

    return {
        "projection": projection,
        "focal_length_mm": float(focal) if focal is not None else 35.0,
        "horizontal_aperture_mm": float(hap) if hap is not None else 36.0,
        "vertical_aperture_mm": (
            float(vap)
            if vap is not None
            else (float(hap) * 24.0 / 36.0 if hap is not None else 24.0)
        ),
        "clip_near_m": near_m if near_m is not None else 0.01,
        "clip_far_m": far_m if far_m is not None else 10000.0,
        "focus_distance_m": focus_m if focus_m is not None else None,
        "f_stop": float(fstop_val) if fstop_val is not None else None,
        "color_temperature_K": None,
        "ortho_width_m": float(ow) * mpu if ow is not None else None,
        "source": "houdini_usd",
        "source_path": prim_path,
    }
