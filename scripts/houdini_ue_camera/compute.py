# -*- coding: utf-8 -*-
"""
相机矩阵计算链：从采样得到的源世界矩阵到最终写入 USDA 的 xform 矩阵。

含 **导出 Stage 的 metersPerUnit** 与 ``compose_export_matrix``（仅缩放平移、旋转保持正交），
以及 pivot、可选 UE 转置等步骤。OpenUSD 舞台长度单位说明：
https://openusd.org/release/glossary.html#usdglossary-metersperunit

设计：新增能力时在 ``camera_xform_pipeline`` 中插入步骤即可；读取参数仍在 ``sampling`` / 面板，写出属性仍在 ``usd_writer``。
"""

from __future__ import annotations

# 导出 Stage 的 metersPerUnit：0.01 ⇒ 1 USD 单位 = 1 厘米（与 UE 世界单位常见约定一致）
DEFAULT_EXPORT_METERS_PER_UNIT = 0.01


def compose_export_matrix(
    world_gf,
    source_meters_per_unit: float,
    export_meters_per_unit: float,
    Gf,
):
    """
    将「源世界矩阵（米）」合成到导出 Stage：仅缩放平移，旋转 3×3 保持正交。

    假定 ``world_gf`` 已为列向量约定（与 ``matrix.hou_matrix4_to_gf`` 输出一致）。

    :param world_gf: 源世界 ``Gf.Matrix4d``。
    :param source_meters_per_unit: 源长度单位。
    :param export_meters_per_unit: 导出 Stage ``metersPerUnit``。
    :param Gf: ``pxr.Gf``。
    :return: 导出用 ``Gf.Matrix4d``。
    """
    # 平移缩放：源/导出 Stage 的 metersPerUnit 之比（见 OpenUSD 舞台长度单位）。
    f = float(source_meters_per_unit) / float(export_meters_per_unit)
    m = Gf.Matrix4d(world_gf)
    rot3 = m.ExtractRotationMatrix()
    # 列向量平移在第 4 列；勿用 ExtractTranslation()（易与底行混淆）
    trans = Gf.Vec3d(m[0][3], m[1][3], m[2][3])
    ts = Gf.Vec3d(trans[0] * f, trans[1] * f, trans[2] * f)
    return Gf.Matrix4d(
        rot3[0][0],
        rot3[0][1],
        rot3[0][2],
        ts[0],
        rot3[1][0],
        rot3[1][1],
        rot3[1][2],
        ts[1],
        rot3[2][0],
        rot3[2][1],
        rot3[2][2],
        ts[2],
        0.0,
        0.0,
        0.0,
        1.0,
    )


def _matrix4d_translation_column_vec(Gf, tx: float, ty: float, tz: float):
    """
    列向量约定 ``p' = M p`` 下的纯平移矩阵（平移写在 **第 4 列**）。

    ``Gf.Matrix4d`` 的 16 元构造为 **行主序** 填入行；勿依赖 ``SetTranslate``：在部分
    Houdini 内嵌 pxr 版本上 ``Matrix4d(1.0); SetTranslate(Vec3d)`` 曾出现**平移未写入**、
    ``t_inv`` 仍为恒等，导致 ``after_pivot`` 与 RAW 完全一致、pivot 形同未生效。
    """
    return Gf.Matrix4d(
        1.0,
        0.0,
        0.0,
        tx,
        0.0,
        1.0,
        0.0,
        ty,
        0.0,
        0.0,
        1.0,
        tz,
        0.0,
        0.0,
        0.0,
        1.0,
    )


def apply_pivot_translation(world_gf, pivot_world_meters, Gf):
    """
    对相机世界矩阵左乘 pivot 的逆平移（仅平移、世界米）。

    等价于相对 ``pivot_world_meters`` 原点表达相机运动。
    背景：OpenUSD 变换组合 https://openusd.org/release/wp_intro_to_usd.html#transformations

    :param world_gf: 源世界 ``Gf.Matrix4d``（列向量约定）。
    :param pivot_world_meters: ``(x,y,z)`` 或 ``None``。
    :param Gf: ``pxr.Gf``。
    :return: 左乘 ``T(-pivot)`` 后的 ``Gf.Matrix4d``。
    """
    if pivot_world_meters is None:
        return world_gf
    px, py, pz = (float(pivot_world_meters[0]), float(pivot_world_meters[1]), float(pivot_world_meters[2]))
    if abs(px) + abs(py) + abs(pz) < 1e-12:
        return world_gf
    t_inv = _matrix4d_translation_column_vec(Gf, -px, -py, -pz)
    return t_inv * Gf.Matrix4d(world_gf)


def apply_transpose_for_ue_import(m_out, transpose_xform_for_ue_import: bool):
    """
    可选写入转置矩阵，供 UE 按行向量读 ``matrix4d`` 时与列向量 USD 约定对齐。

    :param m_out: 逻辑列向量矩阵。
    :param transpose_xform_for_ue_import: 为真则 ``m_out.GetTranspose()``。
    """
    return m_out.GetTranspose() if transpose_xform_for_ue_import else m_out


def camera_xform_pipeline(
    raw_world_gf,
    *,
    pivot_world_meters,
    source_meters_per_unit: float,
    export_meters_per_unit: float,
    Gf,
    transpose_xform_for_ue_import: bool,
):
    """
    主计算链：依次 pivot → 舞台单位 compose → UE 转置；返回终矩阵与各步中间结果便于日志。

    后续例如 FOV 对齐：在 ``apply_transpose_for_ue_import`` 之前插入新函数即可。

    :return: ``(m_final, steps)``，其中 ``steps`` 为 ``(步骤名, 矩阵)`` 列表。
    """
    steps: list[tuple[str, object]] = []

    m_after_pivot = apply_pivot_translation(raw_world_gf, pivot_world_meters, Gf)
    steps.append(("after_pivot_world_m", m_after_pivot))

    m_compose = compose_export_matrix(
        m_after_pivot,
        float(source_meters_per_unit),
        float(export_meters_per_unit),
        Gf,
    )
    steps.append(("compose_export_stage_m", m_compose))

    m_write = apply_transpose_for_ue_import(m_compose, transpose_xform_for_ue_import)
    steps.append(("usd_xformOp_matrix_written", m_write))

    return m_write, steps
