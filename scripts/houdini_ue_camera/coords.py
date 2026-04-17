# -*- coding: utf-8 -*-
"""
长度单位换算与导出用相机世界矩阵合成。

默认导出 ``metersPerUnit=0.01``（1 USD 长度单位 = 1 cm），与 UE 常用世界单位一致。
OpenUSD 舞台长度单位说明见：
https://openusd.org/release/glossary.html#usdglossary-metersperunit
"""

# 导出 Stage 的 metersPerUnit：0.01 ⇒ 1 USD 单位 = 1 厘米（与 UE 世界单位常见约定一致）
DEFAULT_EXPORT_METERS_PER_UNIT = 0.01


def length_scale_factor(source_meters_per_unit: float, export_meters_per_unit: float) -> float:
    """
    计算从「源空间米/单位」到「导出 Stage 米/单位」的长度比例系数。

    平移分量乘以该系数；旋转的 3×3 部分保持正交（刚体），避免整矩阵缩放导致
    UE Sequencer 把缩放误判为极大值、位置钉在 0 等问题。

    :param source_meters_per_unit: 源侧每 USD 单位多少米（Houdini OBJ 世界通常为 1.0）。
    :param export_meters_per_unit: 导出 Stage 的 ``metersPerUnit``。
    :return: ``source_meters_per_unit / export_meters_per_unit``。
    """
    if export_meters_per_unit <= 0 or source_meters_per_unit <= 0:
        raise ValueError("metersPerUnit must be positive")
    return source_meters_per_unit / export_meters_per_unit


def ensure_usd_column_affine_layout(mat_gf, Gf):
    """
    若矩阵平移误在底行（行向量布局残留），则转置为列向量仿射布局。

    USD ``matrix4d`` 作为 ``v' = M * v`` 时，平移应在第 4 列 ``m03,m13,m23``。
    参见 UsdGeom Xform 常见约定与 Gf 矩阵下标：
    https://openusd.org/dev/api/python/class/Gf_1_1Matrix4d.html

    :param mat_gf: 源 ``Gf.Matrix4d`` 或可转为其的矩阵。
    :param Gf: ``pxr.Gf`` 模块。
    :return: 列向量约定下的 ``Gf.Matrix4d``。
    """
    m = Gf.Matrix4d(mat_gf)
    col = abs(m[0][3]) + abs(m[1][3]) + abs(m[2][3])
    row = abs(m[3][0]) + abs(m[3][1]) + abs(m[3][2])
    if col < 1e-9 and row > 1e-9:
        return m.GetTranspose()
    return m


def ue55_optional_post_matrix(Gf):
    """
    可选固定后乘矩阵（用于与 UE 手性/轴向对齐实验）。默认单位阵，不改变结果。

    与 ``export_camera_for_ue55(..., apply_ue_post_matrix=True)`` 配合；需要时在实现内
    改写矩阵并勾选面板隐藏选项。
    """
    return Gf.Matrix4d(1.0)


def _translation_column_major(mat, Gf):
    """
    在列向量约定下读取平移（右列），不用 ``ExtractTranslation()``（其读底行，易混）。

    :param mat: ``Gf.Matrix4d``。
    :param Gf: ``pxr.Gf``。
    :return: ``Gf.Vec3d`` 平移。
    """
    return Gf.Vec3d(mat[0][3], mat[1][3], mat[2][3])


def compose_export_matrix(
    world_gf,
    source_meters_per_unit: float,
    export_meters_per_unit: float,
    Gf,
    apply_ue_post: bool = False,
):
    """
    将「源世界矩阵（米）」合成到导出 Stage：仅缩放平移，旋转 3×3 保持正交。

    :param world_gf: 源世界 ``Gf.Matrix4d``（采样模块已按列向量给出）。
    :param source_meters_per_unit: 源长度单位。
    :param export_meters_per_unit: 导出 Stage ``metersPerUnit``。
    :param Gf: ``pxr.Gf``。
    :param apply_ue_post: 是否在长度换算后再右乘 ``ue55_optional_post_matrix``。
    :return: 导出用 ``Gf.Matrix4d``。
    """
    f = length_scale_factor(source_meters_per_unit, export_meters_per_unit)
    m = ensure_usd_column_affine_layout(world_gf, Gf)
    rot3 = m.ExtractRotationMatrix()
    trans = _translation_column_major(m, Gf)
    ts = Gf.Vec3d(trans[0] * f, trans[1] * f, trans[2] * f)
    out = Gf.Matrix4d(
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
    if apply_ue_post:
        post = ue55_optional_post_matrix(Gf)
        out = post * out
    return out
