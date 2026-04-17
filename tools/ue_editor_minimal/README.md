# UE 编辑器 Python：清单校验与 USDA 导入

在 **UE 5.4 / 5.5** 中启用 **Editor Python** 与 **USD（含 USD Stage Editor）**，将本目录的 **`manifest_smoke.py`**、**`import_smoke.py`** 复制到工程的 **`Content/Python/`**，在 **Output Log → Python** 里调用即可。

带 Slate 窗口的插件版见仓库 **`Plugins/HoudiniUeCameraImporter/`**（内含同逻辑 **`Content/Python/`** 副本）。

---

## 1. 插件

**Edit → Plugins** 启用：

- **Python Editor Script Plugin**
- **Editor Scripting Utilities**（若 EUW 里用 **Execute Python Script**）
- **Universal Scene Description (USD)**（含 **USD Importer**、**USD Stage**、**USD Stage Editor**；`UsdStageEditorLibrary.actions_import` 依赖 Stage Editor）

改完后按提示重启编辑器。

---

## 2. 安装脚本

不要用资源浏览器去 **Import** `.py`（会报未知扩展名）。在资源管理器里复制到：

```text
<YourProject>/Content/Python/manifest_smoke.py
<YourProject>/Content/Python/import_smoke.py
```

**合并清单**（`usd_prim_path` + `export.merged_usda_relative`、无有效逐机 `usda_relative`）需使用当前仓库版本的上述脚本，否则校验可能误判。

---

## 3. 清单与 USDA 所在目录（与 Houdini 面板一致）

**`HoudiniUeCameraPipelinePanel`** 里 **Export directory** 的默认值与占位符为：

```text
$HOUDINI_USER_PREF_DIR/ue_camera_export
```

在 Windows 上展开后通常为（版本号随本机 Houdini 变化）：

```text
C:\Users\<用户名>\Documents\houdini<主版本>\ue_camera_export\
```

该目录在导出成功后应包含：

| 文件 | 说明 |
|------|------|
| `houdini_ue_camera_manifest.json` | 清单（传给下面 Python 的**绝对路径**） |
| `houdini_cameras_merged.usda` | 合并 USDA（与清单同目录，文件名由 `export.merged_usda_relative` 指定） |

在 UE 的 Python 里请写**本机绝对路径**，例如（请改成你的用户名与 `houdini20.5` 等实际目录）：

```text
C:\Users\<用户名>\Documents\houdini20.5\ue_camera_export\houdini_ue_camera_manifest.json
```

---

## 4. Output Log → Python 示例

**自检**

```python
import unreal
unreal.log_warning("[ue_editor_minimal] Python OK")
```

**校验清单**

```python
import manifest_smoke
manifest_smoke.run_manifest_smoke(
    r"C:\Users\<用户名>\Documents\houdini20.5\ue_camera_export\houdini_ue_camera_manifest.json"
)
```

成功时日志含 **`[manifest_smoke] OK`**；缺 USDA 多为 Warning + 弹窗摘要。

**按清单导入 Content**

```python
import import_smoke
import_smoke.import_manifest_cameras(
    r"C:\Users\<用户名>\Documents\houdini20.5\ue_camera_export\houdini_ue_camera_manifest.json"
)
```

默认导入根路径为 **`/Game/houdini_camera`**；可选参数：`content_root`、`max_cameras`（逐机模式）、`show_dialog`。

**单 USDA 调试**

```python
import import_smoke
import_smoke.import_usda_to_content(
    r"C:\Users\<用户名>\Documents\houdini20.5\ue_camera_export\houdini_cameras_merged.usda",
    "/Game/houdini_camera",
)
```

---

## 5. 行为摘要

- **合并清单**：一次 `actions_import` 到 `content_root`；`prim_path_folder_structure=False`，减轻按 USD prim 路径镜像深层目录（具体资产布局仍以 USD 导入器为准）。
- **逐机清单**：每台相机导入到 `{content_root}/{display_name}/`（最多 `max_cameras` 台）。

内部调用顺序：`open_stage_editor` → `file_open` → `actions_import` → `file_close`。日志前缀 **`[import_smoke]`** / **`[manifest_smoke]`**。

---

## 6. Editor Utility Widget

在 **Execute Python Script** 中粘贴 §4 同款代码，仅将 manifest / usda 路径换成本机绝对路径即可。

---

## 7. 常见问题

| 现象 | 处理 |
|------|------|
| 找不到 `manifest_smoke` | 确认两脚本在 **`Content/Python/`** 且文件名正确；重启 UE。 |
| `cameras[i].usda_relative missing`（旧逻辑） | 使用当前仓库 **`manifest_smoke.py`**；合并行允许 `usda_relative` 为 `null`/空串。 |
| 无 Python 输入框 | 启用 Python 插件；Output Log 左下角选 **Python**。 |

---

*与仓库 `tools/ue_editor_minimal/` 同步维护。*
