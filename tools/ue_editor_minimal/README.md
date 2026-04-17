# UE 编辑器 Python：清单校验与 USDA 导入

在 **UE 5.4 / 5.5** 中启用 **Python Editor Script Plugin**、**Editor Scripting Utilities**、**USD Importer**（名称以你安装的引擎为准）。

本目录提供 **Python 脚本**，用于从固定清单导入 Houdini 导出的 USDA；可与 **Editor Utility Widget（EUW）** 蓝图配合，在蓝图里 **Execute Python Script** 调用 `houdini_camera_euw_api` 中的函数。

---

## 0. 拷贝到工程

1. 将本目录下的 **`houdini_camera_manifest.py`**、**`houdini_camera_usd_import.py`**、**`houdini_camera_euw_api.py`** 放到目标 UE 工程的 **`Content/Python/`**（与工程 `Content` 根对齐；UE 默认从该路径加载编辑器 Python）。

2. EUW 蓝图（若使用）：在 **Execute Python Script** 中 `import houdini_camera_euw_api as api` 后调用 `api.import_cameras()` 等。

3. **Edit → Plugins**：确认已启用上述 Python / USD 相关插件；修改后按提示重启编辑器。

---

## 1. 路径约定（Houdini 与 UE 对齐）

| 内容 | 位置 |
|------|------|
| **清单 JSON** | 固定 **`$HOUDINI_USER_PREF_DIR/houdini_ue_camera_manifest.json`**（每次 Houdini 导出**覆盖**）。与仓库根 **`installHouPackage.py`** 里 `houdini_locations` + 版本号 **`20.5`** 推导的「用户区根」一致；在 Houdini 内以 **`HOUDINI_USER_PREF_DIR`** 为准。 |
| **合并 USDA** | 用户在面板 **Export directory** 下选择的目录，**`.usda`** 写在该处。 |
| **UE 如何找 USDA** | 读清单里的 **`export.merged_usda_absolute`**（磁盘绝对路径），不依赖「与 manifest 同目录」。 |

**未传路径时的默认清单位置**（`houdini_camera_manifest.default_fixed_manifest_abs_path()`，与上表「用户区根」同规则）：

- **Windows**：`%USERPROFILE%\Documents\houdini20.5\houdini_ue_camera_manifest.json`
- **Linux**：`~/houdini20.5/houdini_ue_camera_manifest.json`
- **macOS**：`~/Library/Preferences/houdini/20.5/houdini_ue_camera_manifest.json`

若本机 Houdini 主版本不是 **20.5**，须同时改 **`installHouPackage.py`**、**`houdini_ue_camera/pipeline_paths.py`** 与 **`houdini_camera_manifest.DEFAULT_HOUDINI_USER_AREA_VERSION`**，三处保持一致。

---

## 2. 模块分工

| 模块 | 职责 |
|------|------|
| **`houdini_camera_manifest`** | 固定路径、读 JSON、schema 校验、合并 USDA 路径解析、可选弹窗的 **`run_manifest_validation`**。 |
| **`houdini_camera_usd_import`** | Purge、`UsdStageEditorLibrary` 导入、**`import_cameras_from_manifest`**。 |
| **`houdini_camera_euw_api`** | EUW 用薄封装：统一 **`[HoudiniCameraEUW]`** 日志与失败弹窗；导入请优先 **`import_cameras()`**。 |

Output Log 中还可搜 **`[HoudiniCamera:Manifest]`**、**`[HoudiniCamera:Import]`** 过滤底层模块日志。
