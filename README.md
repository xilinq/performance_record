# 业绩追踪系统

当前版本：**v1.3.1**。应用使用 PyQt5、SQLite 和 Matplotlib 录入、维护并可视化分时期业绩数据；SQLite 是唯一业务主库。

## Win7 零安装便携版

正式发布目标是 Windows 7 SP1 64 位，且系统必须已具备加载器更新 KB2533623。除此之外，目标电脑不需要安装 Python、Conda、PyQt5、Matplotlib、NumPy、VC Redistributable 或 UCRT 更新，运行时也不需要管理员权限；其余 DLL 全部随便携目录分发。

这是 Python 3.8 的系统级硬要求，应用本地 DLL 无法替代 Kernel32 提供的加载器 API。若目标机没有该更新，“Python 3.8.10 且完全零系统补丁”的组合不可实现；参见 [Python 3.8 Windows 文档](https://docs.python.org/3.8/using/windows.html) 和 [Microsoft AddDllDirectory 文档](https://learn.microsoft.com/en-us/windows/win32/api/libloaderapi/nf-libloaderapi-adddlldirectory)。

使用方法：

1. 获取正式包 `PerformanceApp_v1.3.1-win7-x64-portable.zip` 及其 `.sha256` 文件；Win11 交叉构建包名称会额外包含 `win11-crossbuild-candidate`，仅供 Win7 实机测试。
2. 完整解压整个目录到当前用户可写位置，例如 `D:\Apps\业绩追踪系统`。
3. 运行目录内的 `PerformanceApp_v1.3.1.exe`。

不要在 ZIP 内直接运行，不要只复制 EXE，也不要删除、改名或移动同目录 DLL。不要放入 `Program Files` 等普通用户不可写目录。

### 启动诊断

在便携目录执行：

```bat
PerformanceApp_v1.3.1.exe --diagnose
```

诊断不会打开或创建业务数据库，会逐项检测 PyQt5、Matplotlib Qt5Agg、NumPy 原生运算、`qwindows.dll` 和 SQLite。结果写入 `startup_diagnostic.log`；普通启动失败写入 `startup_error.log`。程序目录不可写时日志回退到 `%TEMP%`。

冻结程序不再提示“请安装依赖”。失败提示会明确指出便携包缺失或运行库不兼容，并记录底层 DLL 错误、退出码和 traceback。若 PyInstaller bootloader 在 Python 启动前即失败，则无法生成应用日志，应重新完整解压并校验 ZIP/EXE SHA-256。

`--smoke-test` 使用临时数据目录检查 NumPy、SQLite、CSV 和图表链路，不接触正式业务数据：

```bat
PerformanceApp_v1.3.1.exe --smoke-test
```

## 数据边界

- `performance.db` 是唯一业务主库；运行时查询、写入和增长率计算均以 SQLite 已提交数据为准。
- CSV 只保存原始数据，用于自动镜像、手动备份和显式导入/导出，不参与运行时查询或业务计算。
- `performance_backup.csv` 只镜像 SQLite 已提交状态；离线修改必须通过“导入 CSV”预检并确认后才会进入主库，启动时不会自动同步。
- CSV v3 不保存编号、增长率等派生字段；增长率由应用重新计算。姓名库和职级库的启停状态会随原始数据一并备份。
- `QSettings` 只保存窗口、筛选、列宽和图表显示设置，不保存业务数据。

数据、备份、锁文件和启动日志均位于便携目录；源码运行时位于项目根目录。主要文件包括：

| 文件 | 用途 |
| --- | --- |
| `performance.db` | SQLite 主库 |
| `performance_backup.csv` | 已提交数据的自动 CSV 镜像 |
| `backup_*.csv` | 手动备份 |
| `backups/pre_import_*.csv` | 导入前恢复快照 |
| `.performance_record.lock` | 单实例锁 |
| `settings.ini` | 便携版界面与筛选设置，不写注册表 |

## 主要操作

- 数据管理支持按时期、按人员两种录入视图，以及人员新增、重命名和时期管理；导入数据中的停用人员仍可安全显示历史记录。
- 职级由职级库统一管理，默认包含“准营销经理、营销经理、高级营销经理、资深营销经理”；可在两个录入页面打开“管理职级库”新增或停用职级。历史记录中的停用职级不会丢失。
- 姓名、职级、时期和图表筛选等所有下拉框均禁用悬停滚轮切换，需展开后点击选项，避免误操作。
- 切换筛选、标签页、刷新或关闭前会处理未保存内容；活动单元格编辑器会先同步到表格。
- `Ctrl+S` 保存，`F5` 重载；`Insert`、`Ctrl+Delete`、`Alt+↑/↓` 仅在表格获得焦点且未编辑时生效。
- CSV 导入流程为：选择文件 → 无副作用预检 → 查看统计和警告 → 确认覆盖 → 原子导入。
- 个人趋势折线图支持 X/Y 轴滑杆缩放和双向左键拖动；时期对比图只支持 X 轴缩放和横向拖动。
- 数据标签和坐标轴字体均通过 `8–24 pt` 滑杆调整。

## Win11 源码开发与测试

`performance_record` Conda 环境只用于 Win11 开发和回归测试，禁止用它生成 Win7 发布包。

```bat
conda activate performance_record
python -m pip install -r requirements.txt
python main.py
run_tests.bat
python main.py --diagnose
python main.py --smoke-test
```

也可从未激活的终端执行：

```bat
conda run --no-capture-output -n performance_record python run_tests.py
```

不要直接调用 Conda 环境目录中的绝对 `python.exe`；这可能遗漏 `Library\bin` 并触发 `0xC06D007F`。请先激活环境或使用 `conda run`。

## Win7 发布构建

正式构建只能在独立 Win7 SP1 x64 虚拟机中进行，固定基线如下：

- Python.org CPython 3.8.10 x64
- PyQt5 5.15.9、PyQt5-Qt5 5.15.2、PyQt5-sip 12.12.2
- Matplotlib 3.7.3、NumPy 1.24.4
- PyInstaller 5.13.2、pyinstaller-hooks-contrib 2023.8
- Windows 7 SP1 已安装 KB2533623
- Windows SDK 10.0.14393 `ucrt\DLLs\x64` 完整应用本地 UCRT 目录
- VC142 14.29.30153 包中的 x64 应用本地运行库（DLL `FileVersion` 为 `14.29.30157.0`）

### 1. 准备离线 wheelhouse

在联网准备机上使用空目录：

```bat
python tools\win7_portable.py prepare-wheelhouse ^
  --wheelhouse D:\release-inputs\wheelhouse ^
  --requirements requirements-win7-build.txt
```

该命令只下载 CPython 3.8 `win_amd64` 二进制 wheel，校验传递依赖闭包，并根据真实 wheel 字节生成：

- `wheelhouse-manifest.json`
- `requirements-win7-resolved.txt`（包含每个 wheel 的 SHA-256）

把项目、完整 wheelhouse、SDK UCRT 目录和 VC Runtime 目录离线复制到构建虚拟机。不要手工修改锁或混入其他 wheel。

### 2. 在 Win7 构建虚拟机打包

```bat
set WIN7_WHEELHOUSE=D:\release-inputs\wheelhouse
set WIN7_UCRT_ROOT=D:\release-inputs\ucrt-10.0.14393-x64
set WIN7_VC_RUNTIME_ROOT=D:\release-inputs\vc142-14.29-x64
pyinstall.bat
```

构建入口会强制检查 Win7 SP1 x64、KB2533623、Python.org 3.8.10、非 Conda、离线哈希锁、运行库版本和完整性；随后创建隔离 venv、运行全量测试、执行 onedir 构建、检查 PE 依赖闭包和污染 DLL，并对成品运行 `--diagnose`/`--smoke-test` 后再生成候选清单及哈希。

构建阶段只输出候选包，不生成正式同名 ZIP：

```text
dist\PerformanceApp_v1.3.1-win7-x64-portable\
dist\PerformanceApp_v1.3.1-win7-x64-portable-candidate.zip
dist\PerformanceApp_v1.3.1-win7-x64-portable-candidate.zip.sha256
dist\PerformanceApp_v1.3.1.exe.sha256
dist\WIN7_ACCEPTANCE_v1.3.1.json
```

便携目录内的 `PORTABLE_MANIFEST.json` 记录依赖版本、构建系统、运行库来源摘要、PE 审计和文件清单；`SHA256SUMS.txt` 记录目录内文件哈希。`PerformanceApp.spec` 是唯一有效构建配置，采用 onedir/`COLLECT`、关闭 UPX，并显式收集 Matplotlib、Qt 平台插件和应用本地运行库。

构建工具会拒绝 Conda DLL、错误版本的 UCRT/VC Runtime、ICU 75、MKL 2025 以及未解析的非系统 DLL。Win7 版本只发布 onedir 便携 ZIP，不发布单文件 EXE。

### Win11 交叉构建候选包

如需先在当前 Win11 主机生成供 Win7 实机排障的 ZIP，可在官方 Python 3.8.10、锁定 wheelhouse、SDK 14393.795 UCRT 和 VC142 14.29 输入齐全时，为 `build` 增加 `--allow-win11-cross-build`。该模式仍执行全量测试、PE/DLL 审计和成品冒烟，但输出会明确命名为：

```text
dist\PerformanceApp_v1.3.1-win7-x64-portable-win11-crossbuild-candidate.zip
```

其 manifest 状态为 `experimental_win11_cross_build_requires_win7_runtime_test`，不能执行 `finalize`，也不能标记为正式 Win7 发布包。复制到 Win7 后必须完整解压，先运行 `--diagnose` 和 `--smoke-test`，再启动界面。

### 3. 发布验收

候选 ZIP 必须在仅具备 Win7 SP1 与 KB2533623、但无 Python、Conda、VC Redistributable 和 UCRT 更新的干净 Win7 x64 虚拟机中，以普通用户、离线状态、中文可写路径完整解压并验收：

- `--diagnose` 和 `--smoke-test` 返回 0，且诊断前后不生成 `performance.db`。
- 首次启动、增删改查、图表缩放、CSV 导入导出、备份、单实例和重启恢复正常。
- 同一候选 ZIP 在 Win11 完成回归。
- ZIP/EXE SHA-256 与随包文件一致。

验收完成后填写 `dist\WIN7_ACCEPTANCE_v1.3.1.json` 中的测试人、时间及全部确认项，再回到同一 Win7 构建虚拟机执行：

```bat
py -3.8-64 tools\win7_portable.py finalize ^
  --project-root "%CD%" ^
  --acceptance-record dist\WIN7_ACCEPTANCE_v1.3.1.json
```

`finalize` 会校验验收记录与候选 manifest 摘要、确认候选目录没有增加或修改任何文件，再把 manifest 标记为已验收，并生成正式文件：

```text
dist\PerformanceApp_v1.3.1-win7-x64-portable.zip
dist\PerformanceApp_v1.3.1-win7-x64-portable.zip.sha256
```

缺少任一 Win7/Win11 验收项时不会生成正式 ZIP。

## 项目结构

| 路径 | 作用 |
| --- | --- |
| `main.py` | 启动、运行时探测、日志、数据目录、单实例和冒烟测试 |
| `runtime_bootstrap.py` | 源码/冻结模式原生 DLL 搜索路径引导 |
| `database.py` | SQLite Repository、事务和数据服务 |
| `csv_codec.py` | CSV v1/v2 兼容读取、v3 写出、校验和原子替换 |
| `ui/` | 数据录入、图表、姓名/职级管理对话框和 Qt5/Win7 主题 |
| `tests/`、`run_tests.py` | 隔离回归测试入口 |
| `requirements.txt` | Win11 源码开发依赖 |
| `requirements-win7-build.txt` | Win7 发布构建固定依赖 |
| `tools/win7_portable.py` | wheelhouse、构建、PE 审计、清单、哈希和 ZIP 工具 |
| `PerformanceApp.spec` | v1.3.1 Win7 onedir 构建配置 |

版本变化见 [CHANGELOG.md](CHANGELOG.md)。
