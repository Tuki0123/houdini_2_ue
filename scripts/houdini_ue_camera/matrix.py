# -*- coding: utf-8 -*-
"""
Houdini `hou.Matrix4` 与 OpenUSD `Gf.Matrix4d` 的互转。

背景：Houdini 常用行向量右乘 ``v' = v * M``，USD 的 ``UsdGeom.Xformable`` 按列向量
``v' = M * v`` 解释矩阵（见 OpenUSD 变换说明：
https://openusd.org/release/wp_intro_to_usd.html#transformations ）。
此处将 Houdini 世界矩阵转置后写入 ``Gf.Matrix4d``，使平移落在右列，避免导出后
平移/旋转与长度缩放错乱。
"""

import hou


def hou_matrix4_to_gf(m4: hou.Matrix4, gf_module) -> object:
    """
    将 Houdini 4×4 矩阵转为 ``pxr.Gf.Matrix4d``，并按列向量约定转置。

    :param m4: Houdini 节点 ``worldTransform()`` 等得到的矩阵。
    :param gf_module: 传入 ``Gf`` 模块（由调用方 ``from pxr import Gf``），避免循环导入。
    :return: ``Gf.Matrix4d`` 实例。
    """
    Gf = gf_module
    m = Gf.Matrix4d(
        m4.at(0, 0),
        m4.at(0, 1),
        m4.at(0, 2),
        m4.at(0, 3),
        m4.at(1, 0),
        m4.at(1, 1),
        m4.at(1, 2),
        m4.at(1, 3),
        m4.at(2, 0),
        m4.at(2, 1),
        m4.at(2, 2),
        m4.at(2, 3),
        m4.at(3, 0),
        m4.at(3, 1),
        m4.at(3, 2),
        m4.at(3, 3),
    )
    return m.GetTranspose()


def world_transform_at_frame(node: hou.Node, frame: int, gf_module) -> object:
    """
    读取 OBJ（或其它）节点在指定整数帧的世界变换矩阵（已转为 USD 友好的 ``Gf.Matrix4d``）。

    :param node: 已解析的 Houdini 节点。
    :param frame: 时间轴帧号（整数）；内部会 ``hou.setFrame``。
    :param gf_module: ``Gf`` 模块引用。
    :return: ``Gf.Matrix4d``。
    """
    hou.setFrame(int(frame))
    return hou_matrix4_to_gf(node.worldTransform(), gf_module)
