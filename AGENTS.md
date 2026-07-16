# refprop-to-ccm 项目协作说明

这份文件是本项目的持续开发和发布说明。新对话开始前先阅读本文件，再检查工作区状态。回答和判断必须以当前代码、测试输出和命令结果为依据，不要把未验证的假设说成已验证事实。

## 项目边界

- 主项目是 `refprop-to-ccm`，用于调用本机 REFPROP 生成制冷剂物性，并生成 STAR-CCM+ 数据或 Java 宏。
- 当前源码版本基线是 `v1.1.11`，版本号位于 `refprop_to_ccm/__init__.py`。
- 根目录下的 `RefEquiv/` 是单独的外部项目副本，不属于本项目的正常源码范围。除非用户明确要求，不要把它的文件混入主项目提交。
- `PROJECT_HANDOFF.md` 是历史交接文档，可能存在编码或内容过时问题。需要记录新的开发流程时，优先更新本文件，不要覆盖用户未提交的历史文件。

## 环境约定

- 操作系统：Windows。
- Windows 下优先使用 Python Launcher：`py`，不要假设 `python` 命令一定可用。
- REFPROP 根目录优先从环境变量 `RPprefix` 读取，默认路径是 `C:\Program Files (x86)\REFPROP`。
- 目标电脑必须自行安装 REFPROP，并确保 Python/ctREFPROP 与 REFPROP DLL 的位数匹配。REFPROP 的授权文件和 DLL 不打进本项目的 exe。
- REFPROP 兼容代码位于 `refprop_to_ccm/refprop_client.py`。不要只修改调用端而绕过这个客户端的单位转换和错误处理。

## REFPROP 兼容性基线

当前兼容层已经覆盖已知的 REFPROP 9.1 问题：

1. 不直接假定 `RP.MASS_BASE_SI` 一定存在；会尝试属性、`GETENUMdll`、`MASS SI` 和旧枚举值 `2`。
2. `REFPROPdll` 不可加载时，PQ 查询会回退到 `PQFLSHdll`。
3. 回退路径使用 `SETUPdll` 加载 `.FLD`，必要时使用 `SETMIXTUREdll` 加载 `.MIX`。
4. 回退路径使用 `THERMdll` 和 `TRNPRPdll` 计算比热、导热系数和黏度，并把 REFPROP 的摩尔基单位转换为项目使用的质量基 SI 单位。
5. 这些处理不能修复 DLL 本身无法加载、32/64 位不匹配、缺少 REFPROP 数据文件或错误 REFPROP 路径。遇到这类错误，先检查目标电脑环境。

修改这部分代码后，至少运行：

```powershell
py -m pytest tests/test_refprop_client_units.py -q
py -m pytest -q
```

## 每次写完代码必须做什么

### 1. 修改前

先查看工作区，不要覆盖用户已有改动：

```powershell
git status --short
git diff --stat
```

先阅读相关模块和现有测试，再确定最小修改范围。涉及行为变化时，优先补充能够复现问题的回归测试。

### 2. 修改后

按风险从小到大执行验证：

```powershell
# 针对性测试，替换为实际相关测试文件
py -m pytest tests/test_xxx.py -q

# 全量测试
py -m pytest -q

# 编译检查
py -m compileall .\refprop_to_ccm .\egasp\src\egasp

# 检查补丁格式和未预期改动
git diff --check
git status --short
```

如果修改了 GUI，还要运行：

```powershell
py -c "import refprop_to_ccm.gui; print('gui import ok')"
```

如果修改了打包入口、依赖、GUI或运行时加载逻辑，还必须重新打包并做一次exe冒烟测试，不能只依赖 Python 测试。

最终汇报必须明确写出：修改了哪些文件、测试命令及结果、是否完成exe验证、还有哪些未验证的环境条件。

## exe 打包流程

### 首次准备

在项目根目录执行：

```powershell
py -m pip install -r requirements.txt
py -m pip install pyinstaller pytest
```

`requirements.txt`提供运行时依赖；PyInstaller和pytest是开发/验证依赖，不要把 REFPROP 安装包复制进虚拟环境或仓库。

### 正式打包

项目当前使用根目录的 `refprop-to-ccm.spec`，不要只凭旧 README 重新拼接一条命令：

```powershell
py -m PyInstaller --noconfirm --clean .\refprop-to-ccm.spec
New-Item -ItemType Directory -Force .\release | Out-Null
Copy-Item .\dist\refprop-to-ccm.exe .\release\refprop-to-ccm.exe -Force
```

打包完成后检查：

```powershell
Test-Path .\release\refprop-to-ccm.exe
Get-Item .\release\refprop-to-ccm.exe | Select-Object FullName,Length,LastWriteTime
Get-FileHash .\release\refprop-to-ccm.exe -Algorithm SHA256
```

当前 spec 的特点：

- 入口是 `gui_launcher.py`。
- 输出是无控制台窗口的单文件 GUI exe。
- 会把项目内 EGASP 数据文件打进exe。
- 不会把 REFPROP DLL、FLUIDS 或 MIXTURES 打进exe。
- `build/`、`dist/`、`release/`、`out/`和日志是构建或运行产物，不应作为普通源码提交。

### exe 冒烟测试

在开发电脑上启动：

```powershell
.\release\refprop-to-ccm.exe
```

至少确认：GUI能启动、版本号正确、能进入相关页面、配置能保存；如果测试 REFPROP 功能，还要使用实际 REFPROP 路径完成一次最小计算。测试结束后检查 `git status --short`，不要把生成的配置、日志、Excel、sim文件或临时目录混入提交。

在另一台电脑上测试时，exe只负责程序本身；目标电脑仍需要：

- 已安装 REFPROP；
- 正确的 REFPROP 根目录；
- 与程序位数匹配的 REFPROP DLL和Python运行环境（如果运行源码）；
- 对应的 `FLUIDS`/`MIXTURES` 数据文件；
- STAR-CCM+路径和`.sim`文件（只有运行STAR写入功能时需要）。

## 版本和发布流程

每次重新打包并交付 EXE 都视为发布新版本，必须执行版本递增和发布流程。用户未明确指定主版本或次版本变更时，只递增版本号的最后一位，例如 `1.1.9` 变为 `1.1.10`。

1. 修改 `refprop_to_ccm/__init__.py` 的 `__version__`。
2. 运行针对性测试、全量测试、编译检查。
3. 使用 `refprop-to-ccm.spec`重新打包。
4. 做exe冒烟测试并记录SHA-256。
5. 检查 `git diff --check`、`git status --short`，确认没有生成物和隐私信息。
6. 提交源码，创建对应标签，例如 `v1.1.9`，再推送分支和标签。
7. 在 GitHub Release 中上传文件名严格为 `refprop-to-ccm.exe` 的exe。更新检查逻辑依赖这个文件名和版本标签。

不要把REFPROP授权文件、用户的`.sim`文件、个人路径、日志中的隐私信息、API key、账号密码或token写入代码、测试、文档和提交。

## Git 提交前检查

```powershell
git status --short
git diff --stat
git diff --check
py -m pytest -q
```

提交说明应包含实际行为，例如：`Fix REFPROP 9.1 compatibility fallback`，不要只写`fix`或`update`。如果工作区有用户未提交的改动，必须保留并在汇报中说明，不要使用 `git reset --hard` 或 `git checkout --` 清理。
