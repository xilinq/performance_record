# 业绩追踪系统

当前版本为 v1.3.0。这是一个基于 PyQt5、SQLite 和 Matplotlib 的 Windows 桌面应用，用于录入、维护和可视化人员分时期业绩数据。源码开发环境为 Windows 11，发布目标兼容 Windows 7 SP1 64 位。

## 数据边界

- `performance.db` 是唯一业务主库，运行时查询、修改和增长率计算均以 SQLite 中已提交的数据为准。
- CSV 只承载原始数据，用于自动镜像、手动备份和显式导入/导出；程序启动时不会从 CSV 自动同步或覆盖 SQLite。
- CSV v3 保存姓名、时期、职级、左右区业绩、左右区订单、排序、总结和人员启停状态，不保存编号、增长率等派生值。
- `performance_backup.csv` 是程序维护的已提交数据镜像，不应作为运行中的编辑稿。外部修改只有通过“导入 CSV”预检并确认后才会进入主库。
- 增长率由应用根据原始业绩重新计算；SQLite 中现有增长率列仅作为内部缓存。
- `QSettings` 只保存窗口、筛选、列宽和图表显示设置，不保存业务数据。

## 主要功能

- 按时期和按人员两种视图录入业绩、订单、职级及本期总结。
- 使用年月与上/下半月选择器管理 `2020–2099` 年的时期。
- 新增、停用和重命名人员；重命名为已有姓名时，无冲突时期可合并，同期冲突会拒绝覆盖。
- 自动计算左区、右区和总业绩增长率，并保持原始数值精度。
- 对业绩数字、订单整数、千分位、非有限值和 int64 越界进行原位校验。
- 在切换时期、人员、页面、刷新或关闭前处理未保存内容。
- 展示个人业绩趋势折线图和时期业绩对比横向柱状图。
- 对 CSV 执行无副作用预检、摘要校验、导入前快照和原子写入。
- 限制同一数据目录只运行一个实例，并在启动时检查目录是否可写。

## 环境与启动

Win7 发布基线固定为：

- Windows 7 SP1 64 位，并安装 Universal CRT 相关系统更新
- Python 3.8.20
- PyQt5 5.15.9 / Qt 5.15.8
- Matplotlib 3.7.3
- NumPy 1.24.4
- PyInstaller 6.17.0

推荐直接创建锁定版本的 Conda 环境：

```bat
conda env create -f environment-win7.yml
conda activate performance_record
python main.py
```

已有 Python 3.8.20 环境也可按 [requirements.txt](requirements.txt) 安装依赖，但 Win7 构建和验收应优先使用 [environment-win7.yml](environment-win7.yml) 中的完整基线。

## 操作说明

### 数据管理

1. 在“按时期”页选择年月和上/下半月，或在“按人员”页选择已有人员。
2. 通过明确的“新增人员”入口建立姓名，再录入职级、业绩和订单。
3. 在表格工具栏新增、删除或调整记录顺序；停用人员会显示为灰色“姓名（停用）”。
4. 保存按钮只在存在更改时启用。切换上下文时可选择保存、放弃或取消。
5. 保存、重载和跨视图刷新后会尽量恢复当前单元格、滚动位置和有效筛选项。

常用快捷键：

| 快捷键 | 功能 | 生效范围 |
| --- | --- | --- |
| `Ctrl+S` | 保存当前视图 | 数据管理页 |
| `F5` | 重新加载当前视图 | 数据管理页 |
| `Insert` | 新增记录 | 表格获得焦点且未编辑单元格时 |
| `Ctrl+Delete` | 删除记录 | 表格获得焦点且未编辑单元格时 |
| `Alt+↑` / `Alt+↓` | 调整排序 | 表格获得焦点且未编辑单元格时 |
| `Ctrl+Shift+E` | 导出 CSV | 主窗口 |
| `Ctrl+I` | 导入 CSV | 主窗口 |
| `Ctrl+B` | 立即备份 | 主窗口 |

### 图表操作

- “数据标签字体”和“坐标轴字体”使用 `8–24 pt` 滑杆调整，设置会被记忆。
- X/Y 缩放滑杆范围均为 `100%–400%`，步长 `10%`；缩放比例只在本次运行中保留。
- 个人业绩趋势图支持 X、Y 双轴缩放；放大后按住左键可同时拖动水平和垂直显示区域。
- 时期业绩对比图只支持 X 轴缩放；Y 轴滑杆会禁用，按住左键只能横向拖动。
- 在图表上按 `Ctrl+滚轮` 可缩放 X 轴，并尽量保持鼠标指向的数据位置不跳动。
- 放大后滚动条按需出现；对比图人员较多时，普通滚轮仍用于纵向浏览。
- “重置”恢复当前图表支持的轴到 `100%`，并将显示区域移回起点。

### CSV 导入、导出与备份

导入流程为：选择文件 → 无副作用预检 → 查看记录数量和警告 → 确认覆盖 → 应用预检快照。预检后若文件发生变化，摘要校验会拒绝导入；导入失败不会修改当前 SQLite 数据。

- 支持读取 CSV v1、v2 和 v3；旧版增长率列会被忽略并重新计算。
- 高于当前支持版本的 CSV 会直接拒绝，避免未知字段丢失。
- 导入前会创建不可覆盖的恢复快照；快照失败时不会修改主库。
- SQLite 提交成功但镜像刷新失败时，程序会明确区分两种结果，不会把已提交的数据报告为未保存。
- 导出、备份和导入前都会先处理当前未保存内容。

## 数据文件位置

源码运行时，数据位于项目根目录；单文件 EXE 运行时，数据位于 EXE 所在目录，不受启动工作目录影响：

- `performance.db`：唯一业务主库。
- `performance_backup.csv`：SQLite 已提交状态的自动 CSV 镜像。
- `backup_YYYYMMDD_HHMMSS_ffffff.csv`：手动备份，文件名不会重复覆盖。
- `backups/pre_import_YYYYMMDD_HHMMSS_ffffff_<唯一后缀>.csv`：导入前恢复快照。
- `.performance_record.lock`：运行期单实例锁文件。

因此不要把 EXE 放在 `Program Files` 等普通用户无写权限的目录；推荐放在用户拥有写权限的独立文件夹中。

## 项目结构

| 路径 | 作用 |
| --- | --- |
| `main.py` | 应用入口、高 DPI 初始化、数据目录检查、单实例锁和冒烟测试 |
| `database.py` | SQLite 查询、事务、增长率计算和 CSV 操作编排 |
| `csv_codec.py` | 独立 CSV v1/v2 兼容读取、v3 写出、校验和原子替换 |
| `runtime_bootstrap.py` | Windows/Conda 原生 DLL 搜索路径初始化 |
| `ui/main_window.py` | 主窗口、菜单、未保存保护及设置恢复 |
| `ui/data_entry_tab.py` | 双视图数据录入、校验、人员和时期管理 |
| `ui/charts_tab.py` | 图表筛选、字体滑杆、双轴缩放与拖动浏览 |
| `ui/import_preview_dialog.py` | CSV 导入预检确认对话框 |
| `ui/rename_person_dialog.py` | 人员重命名与即时校验对话框 |
| `ui/theme.py` | Qt5/Win7 兼容的全局浅色主题 |
| `tests/`、`run_tests.py` | 自动化回归测试和 Windows DLL 安全的隔离测试入口 |
| `previous_data_process.py` | 旧版分区明细 CSV 到 v3 快照的一次性转换工具 |
| `PerformanceApp.spec` | 当前唯一有效的单文件 Windows 构建配置 |

## 测试

完整测试应在 `performance_record` 环境中运行：

```bat
run_tests.bat
```

无批处理环境时：

```bat
conda run --no-capture-output -n performance_record python run_tests.py
```

运行单个测试模块：

```bat
run_tests.bat tests/test_charts_ui.py
```

源码冒烟测试会使用临时数据目录，并覆盖 NumPy 原生运算、SQLite、CSV 和图表启动链路：

```bat
conda run --no-capture-output -n performance_record python main.py --smoke-test
```

不要通过绝对路径直接调用 Conda 环境中的 `python.exe` 运行 NumPy、Qt 或 Matplotlib 测试。该方式不会完整注入 `Library\bin`，可能触发 Windows 异常 `0xC06D007F`；请使用上面的批处理或 `conda run` 入口。

## 构建与验收

```bat
pyinstall.bat
dist\PerformanceApp_v1.3.0.exe --smoke-test
```

[PerformanceApp.spec](PerformanceApp.spec) 是唯一维护的构建配置：单文件、无控制台、关闭 UPX，并显式收集 Matplotlib 数据和 Qt Windows 平台插件。

正式 Win7 发布包应在安装了 Universal CRT 更新的干净 Win7 SP1 x64 虚拟机中构建并验收，同时在 Win7/Win11、`1024×768` 与 `1920×1080`、100%/125%/150% 缩放下检查首次启动、中文路径、增删改查、图表、CSV、备份和重启恢复。

## 常见问题

- 出现 `0xC06D007F`：使用 `run_tests.bat`、`pyinstall.bat` 或 `conda run`，不要直接启动环境目录下的 `python.exe`；重新构建时只使用当前 `PerformanceApp.spec`。
- 提示数据目录不可写：将整个 EXE 和数据文件移动到当前用户可写目录。
- 提示程序已在运行：关闭使用同一数据目录的现有实例后再启动。
- CSV 预检失败：根据对话框中的版本、时期、数字、排序或缺失数据段提示修正源文件；失败不会修改主库。
- 提示 SQLite 已提交但镜像失败：主库修改已经成功，应修复目录权限或文件占用后再执行备份。

版本变化见 [CHANGELOG.md](CHANGELOG.md)。
