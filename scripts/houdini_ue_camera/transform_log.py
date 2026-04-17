# -*- coding: utf-8 -*-
"""
将 ``Gf.Matrix4d`` 格式化为导出日志用多行英文描述（平移米 + 姿态）。

轴角由 **旋转矩阵 → 单位四元数 → 轴角** 手算（兼容 Houdini 内嵌 pxr 0.24：其 ``Gf.Rotation``
不接受 ``Matrix3d`` 构造）。Euler XYZ 仍为近似。
"""

from __future__ import annotations

import math

from pxr import Gf


def _translation_meters(m: Gf.Matrix4d) -> tuple[float, float, float]:
    """列向量布局下，平移位于第 4 列前三个元素（米）。"""
    return (float(m[0][3]), float(m[1][3]), float(m[2][3]))


def _rotation_part_mat3(m: Gf.Matrix4d) -> Gf.Matrix3d:
    """取仿射变换的 3×3 旋转/缩放部分（此处相机一般为正交旋转）。"""
    return Gf.Matrix3d(
        m[0][0],
        m[0][1],
        m[0][2],
        m[1][0],
        m[1][1],
        m[1][2],
        m[2][0],
        m[2][1],
        m[2][2],
    )


def _quaternion_wxyz_from_mat3(R: Gf.Matrix3d) -> tuple[float, float, float, float]:
    """
    旋转矩阵（列向量、正交）→ 单位四元数 ``(w, x, y, z)``。

    使用 trace 分支的稳定实现；与 ``Gf.Rotation(Matrix3d)`` 无关，避免旧版 USD Python 绑定签名缺失。
    """
    r00, r01, r02 = float(R[0][0]), float(R[0][1]), float(R[0][2])
    r10, r11, r12 = float(R[1][0]), float(R[1][1]), float(R[1][2])
    r20, r21, r22 = float(R[2][0]), float(R[2][1]), float(R[2][2])
    trace = r00 + r11 + r22
    if trace > 0.0:
        s = 0.5 / math.sqrt(trace + 1.0)
        w = 0.25 / s
        x = (r21 - r12) * s
        y = (r02 - r20) * s
        z = (r10 - r01) * s
    elif r00 > r11 and r00 > r22:
        s = 2.0 * math.sqrt(1.0 + r00 - r11 - r22)
        w = (r21 - r12) / s
        x = 0.25 * s
        y = (r01 + r10) / s
        z = (r02 + r20) / s
    elif r11 > r22:
        s = 2.0 * math.sqrt(1.0 + r11 - r00 - r22)
        w = (r02 - r20) / s
        x = (r01 + r10) / s
        y = 0.25 * s
        z = (r12 + r21) / s
    else:
        s = 2.0 * math.sqrt(1.0 + r22 - r00 - r11)
        w = (r10 - r01) / s
        x = (r02 + r20) / s
        y = (r12 + r21) / s
        z = 0.25 * s
    n = math.sqrt(w * w + x * x + y * y + z * z)
    if n < 1e-12:
        return (1.0, 0.0, 0.0, 0.0)
    return (w / n, x / n, y / n, z / n)


def _axis_angle_deg_from_quat_wxyz(w: float, x: float, y: float, z: float) -> tuple[tuple[float, float, float], float]:
    """单位四元数 ``(w,x,y,z)`` → 轴（单位向量）与角度（度）。"""
    w = max(-1.0, min(1.0, w))
    vv = math.sqrt(max(0.0, x * x + y * y + z * z))
    angle_rad = 2.0 * math.atan2(vv, w)
    if vv < 1e-12:
        return (1.0, 0.0, 0.0), 0.0
    inv = 1.0 / vv
    return (x * inv, y * inv, z * inv), math.degrees(angle_rad)


def _euler_xyz_intrinsic_deg_from_mat3(R: Gf.Matrix3d) -> tuple[float, float, float]:
    """
    内旋 XYZ（度）：R = Rx(rx) Ry(ry) Rz(rz) 的常用反解；万向锁附近误差大。

    参考：经典欧拉角与 ``atan2`` 反解（图形学教材 / https://en.wikipedia.org/wiki/Euler_angles ）。
    """
    r00, r01, r02 = float(R[0][0]), float(R[0][1]), float(R[0][2])
    r10, r11, r12 = float(R[1][0]), float(R[1][1]), float(R[1][2])
    r20, r21, r22 = float(R[2][0]), float(R[2][1]), float(R[2][2])
    if abs(r20) < 0.999999:
        ry = -math.asin(r20)
        rx = math.atan2(r21, r22)
        rz = math.atan2(r10, r00)
    else:
        rz = 0.0
        if r20 < 0:
            ry = math.pi * 0.5
            rx = math.atan2(r01, r02)
        else:
            ry = -math.pi * 0.5
            rx = math.atan2(-r01, -r02)
    return (math.degrees(rx), math.degrees(ry), math.degrees(rz))


def format_pose_block(title: str, m: Gf.Matrix4d) -> list[str]:
    """
    生成一块日志行：标题 + 绝对位置（米）+ 轴角（度）+ Euler XYZ（度）+ 基向量摘要。

    :param title: 区块标题（建议含 RAW / AFTER step 等前缀）。
    :param m: 4×4 矩阵。
    """
    tx, ty, tz = _translation_meters(m)
    r3 = _rotation_part_mat3(m)
    qw, qx, qy, qz = _quaternion_wxyz_from_mat3(r3)
    axis, ang_deg = _axis_angle_deg_from_quat_wxyz(qw, qx, qy, qz)
    ex, ey, ez = _euler_xyz_intrinsic_deg_from_mat3(r3)
    c0 = m.GetColumn(0)
    c1 = m.GetColumn(1)
    c2 = m.GetColumn(2)
    return [
        title,
        f"    position abs (m): ({tx:.6f}, {ty:.6f}, {tz:.6f})",
        f"    rotation abs (axis-angle): axis=({axis[0]:.5f},{axis[1]:.5f},{axis[2]:.5f}) angle={ang_deg:.4f} deg",
        f"    rotation abs (Euler XYZ intrinsic deg, approximate): ({ex:.4f}, {ey:.4f}, {ez:.4f})",
        f"    basis cols (column-vector M*v; for debug): x=({c0[0]:.5f},{c0[1]:.5f},{c0[2]:.5f}) "
        f"y=({c1[0]:.5f},{c1[1]:.5f},{c1[2]:.5f}) z=({c2[0]:.5f},{c2[1]:.5f},{c2[2]:.5f})",
    ]
