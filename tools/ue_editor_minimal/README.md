# UE 编辑器 Python：清单校验与 USDA 导入

在 **UE 5.4 / 5.5** 中启用相关插件 **Editor Python** 与 **USD Importor**。
本目录提供 **Python 脚本** 与**Editor Utility Widget（EUW）蓝图资产**，用于从固定清单导入 Houdini 导出的 USDA。

---

## 0. 含 EUW 的一键安装

交付物在 **`tools/ue_editor_minimal/`** 内按 **与 UE 工程 `Content` 根对齐** 的目录树摆放（例如内含 **`Content/Python/`** 下的三个 `.py`，以及 **`.uasset`** EUW 蓝图）。使用时：

1. **合并到工程 Content**  
   在资源管理器中将本包里的 **`Content`** 文件夹**整体合并**到目标 UE 工程的 **`YourProject/Content/`**（与工程自带 `Content` 根并列合并，不要多套一层导致路径变成 `Content/ue_editor_minimal/Content/...` 除非你刻意如此）。  
   - **必须**：三个脚本最终出现在 **`Content/Python/`**（`manifest_smoke.py`、`import_smoke.py`、`houdini_camera_euw_api.py`）。UE 默认从该路径加载编辑器 Python。

2. **打开 EUW 并编译**  
   在 UE **Content Browser** 中双击打开 **Editor Utility Widget** 蓝图 → 若提示未编译，点击 **Compile** → **Save**。

3. **运行**  
   在 EUW 蓝图编辑器工具栏使用 **Run Utility Widget**（或你为该 Widget 注册的编辑器入口）。在窗口中点击 **导入** 等按钮即可调用 `import_cameras()`。

4. **插件**  
   确认 **Edit → Plugins** 中已启用 **Python Editor Script Plugin**、**Editor Scripting Utilities**、**USD Importor**。修改后按提示重启编辑器。

---

---

## 1. 路径约定（Houdini 与 UE 对齐）

| 内容 | 位置 |
|------|------|
| **清单 JSON** | 固定 **`$HOUDINI_USER_PREF_DIR/houdini_ue_camera_manifest.json`**（每次 Houdini 导出**覆盖**）。与仓库根 **`installHouPackage.py`** 里 `houdini_locations` + 版本号 **`20.5`** 推导的「用户区根」一致；在 Houdini 内以 **`HOUDINI_USER_PREF_DIR`** 为准。 |
| **合并 USDA** | 用户在面板 **Export directory** 下选择的目录（默认占位仍为 **`…/ue_camera_export`**），仅 **`.usda`** 写在此处。 |
| **UE 如何找 USDA** | 读清单里的 **`export.merged_usda_absolute`**（磁盘绝对路径），不依赖「与 manifest 同目录」。 |

**未传路径时的默认清单位置**（`manifest_smoke.default_fixed_manifest_abs_path()`，与上表「用户区根」同规则）：

- **Windows**：`%USERPROFILE%\Documents\houdini20.5\houdini_ue_camera_manifest.json`
- **Linux**：`~/houdini20.5/houdini_ue_camera_manifest.json`
- **macOS**：`~/Library/Preferences/houdini/20.5/houdini_ue_camera_manifest.json`

若本机 Houdini 主版本不是 **20.5**，须同时改 **`installHouPackage.py`**、**`houdini_ue_camera/pipeline_paths.py`** 与 **`manifest_smoke.DEFAULT_HOUDINI_USER_AREA_VERSION`**（及插件 C++ 里 `GetDefaultFixedManifestPath` 中的路径段），四处保持一致。
