# -*- coding: utf-8 -*-
"""
Editor Utility Widget（蓝图）极简入口：只调本文件里的函数。

**职责**：按固定清单路径校验并从 **manifest** 解析 **USDA**，调用 ``import_smoke.import_manifest_cameras`` 导入到 ``/Game/houdini_camera``。
**Pivot / 关卡序列位置** 由你在 **EUW 蓝图**（例如导入后 Delay 再 ``Get Actor`` / ``Set Actor Location``）自行处理；本模块**不再**读写 pivot 或改关卡序列。

**日志**：``_trace`` → ``unreal.log_warning``（搜 ``[HoudiniCameraEUW]``）。**仅失败**时 ``_dialog``。

EUW **导入**请调 ``import_cameras()``；勿只调 ``import_smoke.import_manifest_cameras()`` 若你希望统一弹窗与 ``[HoudiniCameraEUW]`` 日志链（两者导入行为一致，仅入口不同）。

复制到： ``<YourProject>/Content/Python/houdini_camera_euw_api.py``
"""

from __future__ import annotations

from pathlib import Path

import unreal

import import_smoke
import manifest_smoke

PREFIX = "[HoudiniCameraEUW]"


def _trace(msg: str) -> None:
    unreal.log_warning(f"{PREFIX} {msg}")


def _dialog(message: str, *, error: bool = False) -> None:
    title = "Houdini 相机" + (" — 错误" if error else "")
    try:
        unreal.EditorDialog.show_message(
            title=unreal.Text(title),
            message=unreal.Text(message),
            message_type=unreal.AppMsgType.OK,
            default_value=unreal.AppReturnType.OK,
        )
    except Exception as exc:  # noqa: BLE001
        unreal.log_error(f"{PREFIX} dialog failed: {exc!r}")
        _trace(message)


def _fixed_manifest_path() -> str:
    return manifest_smoke.default_fixed_manifest_abs_path()


def purge_only() -> None:
    """
    仅 ``import_smoke.purge_houdini_camera_import_before_reimport``（不读 USDA、不导入）。
    """
    try:
        data = manifest_smoke.load_manifest(_fixed_manifest_path())
    except Exception:
        data = None
    import_smoke.purge_houdini_camera_import_before_reimport(
        import_smoke.DEFAULT_CONTENT_ROOT,
        manifest=data,
    )
    _trace(
        f"purge_only: done content_root={import_smoke.DEFAULT_CONTENT_ROOT!r} "
        f"manifest_read_ok={data is not None}"
    )


def import_cameras() -> bool:
    """
    固定清单 → **JSON 校验 + USDA 存在性检查** → ``import_manifest_cameras``（purge + USD 导入）。
    """
    _trace(
        "import_cameras: begin (manifest schema + USDA checks; pivot/LSA placement is blueprint-only)"
    )
    mp = _fixed_manifest_path()
    p = Path(mp)
    if not p.is_file():
        _trace(f"import_cameras: ABORT manifest not found path={p}")
        _dialog(
            "未找到清单文件，已中止操作。\n\n"
            f"期望路径（固定）：\n{p}\n\n"
            "请先在 Houdini 中完成导出；若路径不对，请检查本机 Houdini 用户目录是否与 "
            "manifest_smoke.DEFAULT_HOUDINI_USER_AREA_VERSION（默认 20.5）一致。",
            error=True,
        )
        return False
    try:
        data = manifest_smoke.load_manifest(mp)
    except Exception as exc:  # noqa: BLE001
        _trace(f"import_cameras: ABORT manifest JSON error {exc!r}")
        _dialog(f"清单无法读取或 JSON 无效，已中止。\n\n{exc}", error=True)
        return False
    errs = manifest_smoke.validate_manifest(data)
    if errs:
        _trace(f"import_cameras: ABORT manifest validation errors={len(errs)}")
        _dialog("清单内容校验失败，已中止。\n\n" + "\n".join(errs[:24]), error=True)
        return False
    missing = manifest_smoke.check_usda_files(mp, data)
    if missing:
        _trace(f"import_cameras: ABORT missing USDA count={len(missing)}")
        _dialog(
            "以下 USDA 路径无效或文件不存在，已中止。\n\n" + "\n".join(missing[:24]),
            error=True,
        )
        return False
    _trace(
        f"import_cameras: calling import_manifest_cameras "
        f"content_root={import_smoke.DEFAULT_CONTENT_ROOT!r}"
    )
    n = import_smoke.import_manifest_cameras(
        mp,
        content_root=import_smoke.DEFAULT_CONTENT_ROOT,
        show_dialog=False,
    )
    if n <= 0:
        _trace("import_cameras: ABORT import_manifest_cameras returned n<=0 (see [import_smoke] in Output Log)")
        _dialog(
            "导入未成功完成（批次数为 0）。\n"
            "请查看 Output Log 中带 [import_smoke]、[manifest_smoke] 的日志。",
            error=True,
        )
        return False
    merged = manifest_smoke.manifest_uses_merged_usda(data)
    mode = "合并 USDA" if merged else "逐相机 USDA"
    _trace(
        f"import_cameras: OK batches={n} mode={mode!r} "
        f"content_root={import_smoke.DEFAULT_CONTENT_ROOT!r}"
    )
    return True


def reload_cameras() -> bool:
    """与 ``import_cameras`` 相同。"""
    return import_cameras()


def validate_manifest() -> None:
    """可选调试：``run_manifest_smoke``（固定路径）。日常可只依赖 ``import_cameras`` 内校验。"""
    _trace("validate_manifest: begin (fixed manifest path)")
    ok = manifest_smoke.run_manifest_smoke(None, show_dialog=True, show_success_dialog=False)
    if ok:
        _trace("validate_manifest: OK (no success dialog; see [manifest_smoke] lines above)")
    else:
        _trace("validate_manifest: FAILED (error dialog may have been shown)")
