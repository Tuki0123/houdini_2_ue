# -*- coding: utf-8 -*-
"""
Houdini → UE 摄像机管线导出面板。

**货架 / 脚本（单例浮动窗）**：重复调用会先关闭旧窗口再打开新实例并置顶，避免叠多个对话框。

::

    import sys
    if "HoudiniUeCameraPipelinePanel" in sys.modules:
        del sys.modules["HoudiniUeCameraPipelinePanel"]
    from HoudiniUeCameraPipelinePanel import show_pipeline_panel
    show_pipeline_panel()

    # 与上等价（便于与课程其它命名统一）：
    # from HoudiniUeCameraPipelinePanel import run_panel
    # run_panel()

**Houdini Python Panel**：在面板脚本里把 ``createInterface`` 指到本模块的 ``createInterface``（见 SideFX 文档
`Python Panel Editor`），由编辑器嵌入控件；该路径**每次返回新实例**，与上面单例浮动窗分流。

界面与导出详细日志为英文；本模块内**函数说明**为中文文档字符串。
"""

from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import hou
from PySide2 import QtCore, QtWidgets

from houdini_ue_camera.coords import DEFAULT_EXPORT_METERS_PER_UNIT
from houdini_ue_camera.usd_writer import (
    MERGED_USDA_FILENAME,
    export_merged_cameras_for_ue55,
    list_cameras_for_ui,
    _safe_segment,
)
from houdini_ue_camera.version import LAST_MODIFIED, VERSION

MANIFEST_NAME = "houdini_ue_camera_manifest.json"
_CAM_TOKEN = re.compile(r"^[A-Za-z0-9_]+$")

# 货架/脚本打开的「单例」浮动面板；与 ``createInterface`` 嵌入路径分离（见 ``createInterface`` 说明）。
_pipeline_panel_instance: HoudiniUeCameraPipelinePanel | None = None


def _camera_basename(path: str) -> str:
    """从完整节点路径取最后一段作为相机短名（用于文件名与 manifest）。"""
    return path.strip().split("/")[-1] or path


def _is_valid_camera_name(path: str) -> bool:
    """判断 basename 是否仅含字母数字下划线（与 USD prim 安全段、需求文档一致）。"""
    return bool(_CAM_TOKEN.match(_camera_basename(path)))


def _default_frame_end() -> int:
    """取播放条当前播放范围右端点作为默认结束帧（整数）。"""
    try:
        return int(hou.playbar.playbackRange()[1])
    except Exception:
        return 24


def _node_world_translate_meters(n: hou.Node) -> tuple[float, float, float] | None:
    """
    读取节点世界变换的平移分量（米），用于 Pivot「从选中读取」。

    :return: ``(tx, ty, tz)`` 或读取失败时 ``None``。
    """
    try:
        m = n.worldTransform()
        if hasattr(m, "extractTranslates"):
            t = m.extractTranslates()
            return (float(t[0]), float(t[1]), float(t[2]))
    except Exception:
        pass
    return None


def _frame_range_hint(cam_path: str) -> str:
    """
    在相机列表每行右侧显示的帧范围提示（占位；完整「每机独立范围」见需求 C12）。

    :param cam_path: 相机路径（当前未用，保留与后续 C12 扩展签名一致）。
    """
    del cam_path  # 预留：每机独立帧范围
    try:
        f1 = _default_frame_end()
        return f"1-{f1} (playbar default)"
    except Exception:
        return "-"


class HoudiniUeCameraPipelinePanel(QtWidgets.QDialog):
    """主面板：导出目录、相机多选、帧/FPS/采样、Pivot、日志与导出。"""

    def __init__(self, parent=None):
        """创建窗口部件、连接信号，并执行首次相机列表扫描。"""
        super().__init__(parent)
        self.setWindowTitle(f"Houdini -> UE camera export  v{VERSION}")
        self.resize(720, 640)

        self._cam_checkboxes: dict[str, QtWidgets.QCheckBox] = {}
        self._cam_rows: dict[str, QtWidgets.QWidget] = {}

        root = QtWidgets.QVBoxLayout(self)

        dir_row = QtWidgets.QHBoxLayout()
        dir_row.addWidget(QtWidgets.QLabel("Export directory:"))
        self._export_dir = QtWidgets.QLineEdit()
        default_dir = (Path(hou.getenv("HOUDINI_USER_PREF_DIR") or "") / "ue_camera_export").as_posix()
        self._export_dir.setPlaceholderText(default_dir)
        self._export_dir.setText(default_dir)
        dir_row.addWidget(self._export_dir, 1)
        btn_browse = QtWidgets.QPushButton("Browse...")
        btn_browse.clicked.connect(self._browse_export_dir)
        dir_row.addWidget(btn_browse)
        root.addLayout(dir_row)

        root.addWidget(QtWidgets.QLabel("Cameras (/obj, basename must match [A-Za-z0-9_]+):"))
        head = QtWidgets.QHBoxLayout()
        self._chk_select_all = QtWidgets.QCheckBox("Select all (valid names only)")
        self._chk_select_all.toggled.connect(self._on_select_all)
        head.addWidget(self._chk_select_all)
        head.addStretch(1)
        btn_refresh = QtWidgets.QPushButton("Refresh list")
        btn_refresh.clicked.connect(self._refresh_cameras)
        head.addWidget(btn_refresh)
        root.addLayout(head)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(180)
        self._cam_host = QtWidgets.QWidget()
        self._cam_layout = QtWidgets.QVBoxLayout(self._cam_host)
        self._cam_layout.addStretch(1)
        scroll.setWidget(self._cam_host)
        root.addWidget(scroll)

        fr = QtWidgets.QHBoxLayout()
        fr.addWidget(QtWidgets.QLabel("Start frame:"))
        self._f0 = QtWidgets.QSpinBox()
        self._f0.setRange(-100000, 100000)
        self._f0.setValue(1)
        fr.addWidget(self._f0)
        fr.addWidget(QtWidgets.QLabel("End frame:"))
        self._f1 = QtWidgets.QSpinBox()
        self._f1.setRange(-100000, 100000)
        self._f1.setValue(_default_frame_end())
        fr.addWidget(self._f1)
        fr.addWidget(QtWidgets.QLabel("FPS:"))
        self._fps = QtWidgets.QDoubleSpinBox()
        self._fps.setRange(1.0, 1000.0)
        self._fps.setDecimals(3)
        self._fps.setValue(float(hou.fps()))
        fr.addWidget(self._fps)
        fr.addStretch(1)
        root.addLayout(fr)

        samp = QtWidgets.QHBoxLayout()
        samp.addWidget(QtWidgets.QLabel("Sampling:"))
        self._sample_mode = QtWidgets.QComboBox()
        self._sample_mode.addItem("Every frame", "all")
        self._sample_mode.addItem("Step (every N frames)", "step")
        samp.addWidget(self._sample_mode)
        samp.addWidget(QtWidgets.QLabel("N:"))
        self._frame_step = QtWidgets.QSpinBox()
        self._frame_step.setRange(1, 10000)
        self._frame_step.setValue(1)
        samp.addWidget(self._frame_step)
        samp.addStretch(1)
        self._sample_mode.currentIndexChanged.connect(self._on_sample_mode)
        root.addLayout(samp)
        self._on_sample_mode()

        pv = QtWidgets.QHBoxLayout()
        pv.addWidget(QtWidgets.QLabel("Pivot (world, meters):"))
        self._pvx = QtWidgets.QDoubleSpinBox()
        self._pvy = QtWidgets.QDoubleSpinBox()
        self._pvz = QtWidgets.QDoubleSpinBox()
        for w in (self._pvx, self._pvy, self._pvz):
            w.setRange(-1e9, 1e9)
            w.setDecimals(6)
            w.setValue(0.0)
            pv.addWidget(w)
        btn_pv = QtWidgets.QPushButton("Read world translate from selection")
        btn_pv.clicked.connect(self._pivot_from_selection)
        pv.addWidget(btn_pv)
        pv.addStretch(1)
        root.addLayout(pv)

        # 进阶选项：不出现在布局中，但导出仍读取（与 manifest 中布尔/ mpu 一致）
        self._chk_ue = QtWidgets.QCheckBox(self)
        self._chk_ue.setChecked(False)
        self._chk_ue.setVisible(False)
        self._chk_transpose = QtWidgets.QCheckBox(self)
        self._chk_transpose.setChecked(True)
        self._chk_transpose.setVisible(False)
        self._src_mpu = QtWidgets.QDoubleSpinBox(self)
        self._src_mpu.setRange(0.0001, 1000.0)
        self._src_mpu.setDecimals(6)
        self._src_mpu.setValue(1.0)
        self._src_mpu.setVisible(False)

        root.addWidget(QtWidgets.QLabel("Log:"))
        self._log = QtWidgets.QTextBrowser()
        self._log.setMinimumHeight(160)
        self._log.setOpenExternalLinks(False)
        root.addWidget(self._log, 1)

        btn_row = QtWidgets.QHBoxLayout()
        self._btn_export = QtWidgets.QPushButton("Export manifest + USD")
        self._btn_export.clicked.connect(self._do_export)
        btn_row.addWidget(self._btn_export)
        btn_close = QtWidgets.QPushButton("Close")
        btn_close.clicked.connect(self.close)
        btn_row.addWidget(btn_close)
        root.addLayout(btn_row)

        self._log_line(f"[houdini_ue_camera] v{VERSION} | last modified: {LAST_MODIFIED}", "info")
        self._refresh_cameras()

    def _on_sample_mode(self) -> None:
        """采样模式下拉变更：仅「按步长」时启用 N  spinbox。"""
        step_en = self._sample_mode.currentData() == "step"
        self._frame_step.setEnabled(step_en)
        if not step_en:
            self._frame_step.setValue(1)

    def _browse_export_dir(self) -> None:
        """弹出目录选择，更新导出路径文本框。"""
        d = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "Select export directory",
            self._export_dir.text().strip() or "",
        )
        if d:
            self._export_dir.setText(Path(d).as_posix())

    def _log_line(self, text: str, level: str = "info") -> None:
        """
        向日志区追加一行 HTML 着色文本。

        :param text: 原始文本（会 HTML 转义）。
        :param level: ``info`` / ``warn`` / ``err`` 控制颜色。
        """
        color = {"info": "#333", "warn": "#a60", "err": "#c00"}.get(level, "#333")
        esc = html.escape(text, quote=True)
        self._log.append(f"<span style='color:{color};'>{esc}</span>")

    def _clear_cam_widgets(self) -> None:
        """移除当前相机列表行的所有控件并重置内部映射。"""
        for w in list(self._cam_rows.values()):
            self._cam_layout.removeWidget(w)
            w.deleteLater()
        self._cam_checkboxes.clear()
        self._cam_rows.clear()

    def _refresh_cameras(self) -> None:
        """扫描 ``/obj`` 下相机，合法名进列表，非法名仅打红字日志。"""
        self._clear_cam_widgets()
        paths = list_cameras_for_ui("obj", None)
        invalid = []
        valid = []
        for p in paths:
            if _is_valid_camera_name(p):
                valid.append(p)
            else:
                invalid.append(p)

        for p in sorted(invalid):
            self._log_line(f"[invalid name] skipped: {p}", "err")
        for p in sorted(valid):
            row = QtWidgets.QWidget()
            h = QtWidgets.QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            cb = QtWidgets.QCheckBox()
            cb.setChecked(False)
            name = _camera_basename(p)
            lbl = QtWidgets.QLabel(
                f"<b>{html.escape(name)}</b> &mdash; <code>{html.escape(p)}</code>"
            )
            lbl.setTextFormat(QtCore.Qt.RichText)
            info = QtWidgets.QLabel(f"frames {_frame_range_hint(p)}")
            h.addWidget(cb)
            h.addWidget(lbl, 1)
            h.addWidget(info)
            self._cam_layout.insertWidget(self._cam_layout.count() - 1, row)
            self._cam_checkboxes[p] = cb
            self._cam_rows[p] = row

        self._log_line(
            f"[cameras] valid: {len(valid)}, invalid (excluded): {len(invalid)}.",
            "info",
        )

    def _on_select_all(self, checked: bool) -> None:
        """「全选」勾选框：同步所有合法相机的勾选状态。"""
        for cb in self._cam_checkboxes.values():
            cb.setChecked(checked)

    def _pivot_from_selection(self) -> None:
        """将当前选中第一个节点的世界平移（米）写入 Pivot 三个 spinbox。"""
        sel = hou.selectedNodes()
        if not sel:
            self._log_line("[Pivot] No node selected.", "warn")
            return
        tr = _node_world_translate_meters(sel[0])
        if tr is None:
            self._log_line("[Pivot] Could not read world translate; enter pivot manually.", "warn")
            return
        self._pvx.setValue(tr[0])
        self._pvy.setValue(tr[1])
        self._pvz.setValue(tr[2])
        self._log_line(f"[Pivot] from {sel[0].path()}: {tr}", "info")

    def _selected_cam_paths(self) -> list[str]:
        """返回当前勾选的相机完整路径列表。"""
        return [p for p, cb in self._cam_checkboxes.items() if cb.isChecked()]

    def _confirm_cleanup(self, paths_to_remove: list[Path]) -> bool:
        """
        导出前确认是否删除将覆盖的 manifest 与 usda。

        :param paths_to_remove: 拟删除文件路径列表。
        :return: 用户选 Yes 为 ``True``。
        """
        if not paths_to_remove:
            return True
        lines = "\n".join(f"  - {p.as_posix()}" for p in paths_to_remove[:20])
        more = "" if len(paths_to_remove) <= 20 else f"\n  ... ({len(paths_to_remove)} files total)"
        ret = QtWidgets.QMessageBox.question(
            self,
            "Overwrite export",
            "The following files managed by this tool will be deleted, then re-written:\n"
            + lines
            + more
            + "\n\nContinue?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        return ret == QtWidgets.QMessageBox.Yes

    def _collect_export_cleanup_paths(self, out_dir: Path) -> list[Path]:
        """
        收集本次合并导出会覆盖的已有文件：清单 + 合并 ``USDA``（不再按台删除多个 ``.usda``）。

        :param out_dir: 导出目录。
        """
        rm: list[Path] = []
        man = out_dir / MANIFEST_NAME
        if man.is_file():
            rm.append(man)
        merged = out_dir / MERGED_USDA_FILENAME
        if merged.is_file():
            rm.append(merged)
        return rm

    def _do_export(self) -> None:
        """
        执行导出：删旧 manifest/合并 USDA → ``export_merged_cameras_for_ue55`` → 写清单。

        多台相机写入**单个** ``USDA``，UE 侧一次导入 ``/Game/houdini_camera``（或所选 ``content_root``）以得到 Level Sequence。
        """
        out_dir_s = self._export_dir.text().strip()
        if not out_dir_s:
            QtWidgets.QMessageBox.warning(self, "Export", "Please set an export directory.")
            return
        out_dir = Path(out_dir_s)
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            self._log_line(f"[error] cannot create directory: {exc!r}", "err")
            QtWidgets.QMessageBox.critical(self, "Export", str(exc))
            return

        cams = self._selected_cam_paths()
        if not cams:
            QtWidgets.QMessageBox.warning(self, "Export", "Select at least one camera.")
            return

        f0, f1 = self._f0.value(), self._f1.value()
        if f1 < f0:
            QtWidgets.QMessageBox.warning(self, "Export", "End frame must be >= start frame.")
            return

        step = self._frame_step.value() if self._sample_mode.currentData() == "step" else 1
        step = max(1, int(step))

        to_clean = self._collect_export_cleanup_paths(out_dir)
        if to_clean and not self._confirm_cleanup(to_clean):
            self._log_line("[cancel] user cancelled cleanup.", "warn")
            return
        for p in to_clean:
            try:
                if p.is_file():
                    p.unlink()
            except Exception as exc:
                self._log_line(f"[warn] could not delete {p}: {exc!r}", "warn")

        pivot = (self._pvx.value(), self._pvy.value(), self._pvz.value())
        fps = float(self._fps.value())
        export_mpu = float(DEFAULT_EXPORT_METERS_PER_UNIT)
        src_mpu = float(self._src_mpu.value())

        manifest_cameras = []
        for cam_path in cams:
            name = _camera_basename(cam_path)
            manifest_cameras.append(
                {
                    "obj_path": cam_path,
                    "display_name": name,
                    "usd_prim_path": f"/World/{_safe_segment(name)}",
                }
            )

        def log_cb(msg: str):
            """将导出库传入的英文日志行追加到面板（小号灰色）。"""
            esc = html.escape(msg, quote=True)
            self._log.append(f"<span style='color:#555;font-size:10pt;'>{esc}</span>")

        merged_path = out_dir / MERGED_USDA_FILENAME
        self._log_line(f"[export merged] cameras={len(cams)} -> {merged_path.as_posix()}", "info")
        try:
            export_merged_cameras_for_ue55(
                str(merged_path),
                camera_obj_paths=cams,
                frame_start=f0,
                frame_end=f1,
                frame_step=step,
                fps=fps,
                export_meters_per_unit=export_mpu,
                source_meters_per_unit=src_mpu,
                apply_ue_post_matrix=self._chk_ue.isChecked(),
                pivot_world_meters=pivot,
                log=log_cb,
                transpose_xform_for_ue_import=self._chk_transpose.isChecked(),
            )
        except Exception as exc:
            self._log_line(f"[error] merged export: {exc!r}", "err")
            QtWidgets.QMessageBox.critical(self, "Export failed", str(exc))
            return

        manifest = {
            "schema_version": 1,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "houdini": {"panel": "HoudiniUeCameraPipelinePanel", "package_version": VERSION},
            "export": {
                "fps": fps,
                "frame_start": f0,
                "frame_end": f1,
                "frame_step": step,
                "export_meters_per_unit": export_mpu,
                "source_meters_per_unit": src_mpu,
                "pivot_world_meters": list(pivot),
                "transpose_xform_for_ue_import": self._chk_transpose.isChecked(),
                "apply_ue_post_matrix": self._chk_ue.isChecked(),
                "merged_usda_relative": MERGED_USDA_FILENAME,
            },
            "cameras": manifest_cameras,
        }
        man_path = out_dir / MANIFEST_NAME
        man_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        self._log_line(f"[done] manifest: {man_path.as_posix()}", "info")
        QtWidgets.QMessageBox.information(
            self,
            "Export",
            f"Wrote merged USDA + manifest.\n{merged_path}\n{man_path}",
        )


def show_pipeline_panel() -> None:
    """
    显示非模态管线面板：全局最多保留一个浮动实例。

    若已有旧实例则先 ``close`` + ``deleteLater``（借鉴课程单例写法），再创建新实例、
    ``show`` / ``raise_`` / ``activateWindow``，避免货架连点堆叠窗口。
    """
    global _pipeline_panel_instance

    if _pipeline_panel_instance is not None:
        try:
            _pipeline_panel_instance.close()
            _pipeline_panel_instance.deleteLater()
        except Exception:
            pass
        _pipeline_panel_instance = None

    parent = hou.ui.mainQtWindow()
    _pipeline_panel_instance = HoudiniUeCameraPipelinePanel(parent=parent)
    _pipeline_panel_instance.show()
    _pipeline_panel_instance.raise_()
    _pipeline_panel_instance.activateWindow()


def run_panel() -> None:
    """与 ``show_pipeline_panel`` 行为相同；命名与常见课程脚本一致。"""
    show_pipeline_panel()


def createInterface():
    """
    Houdini **Python Panel** 约定入口：返回嵌入编辑器用的面板控件。

    由 Houdini 面板系统持有生命周期；**不使用**模块级 ``_pipeline_panel_instance``，
    以免与货架浮动单例互相 ``close``。未传父窗口，便于由宿主设置父级。
    参考：SideFX — *Working with Python Panel* / panel interface file.
    """
    return HoudiniUeCameraPipelinePanel(parent=None)
