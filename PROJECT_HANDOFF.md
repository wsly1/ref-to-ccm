# refprop-to-ccm 项目交接文档

更新时间：2026-05-21

本文档只保留当前继续开发需要的事实、入口、边界和验证命令。旧的阶段性规划、已清理文件和过时背景已删除。

## 1. 项目规则

- 项目路径：`E:\code\refprop-to-ccm`
- 系统环境：Windows + PowerShell
- 批量删除或批量修改文件前，必须先向用户申请权限。
- 回答和判断必须基于项目文件、命令输出或用户明确提供的信息，不能编造。
- 修改或创建非代码类文件时，默认使用 UTF-8。
- 代码中不能写入 API key、账号、密码、token 等隐私信息。
- 生成文件不要误提交；提交前检查 `git status`。

## 2. 当前功能

本项目现在包含两个主要功能：

1. REFPROP 到 STAR-CCM+
   - 从 GUI 或 YAML 配置读取制冷剂、饱和条件、温度表范围和 STAR-CCM+ 项目信息。
   - 调用 REFPROP 生成液相/气相物性输出和 STAR-CCM+ Java 宏。
   - 可选调用 STAR-CCM+ 批处理执行宏。

2. 防冻液物性计算
   - 使用本地最小 EGASP 数据源计算乙二醇水溶液防冻液物性。
   - 物性查询温度独立输入。
   - 支持体积浓度或质量浓度输入，默认体积浓度 `0.5`。
   - 支持三种计算方式：
     - `heat`：已知体积流量、入口温度、出口温度，计算换热量。
     - `outlet-temperature`：已知体积流量、入口温度、换热量，反算出口温度。
     - `volume-flow`：已知入口温度、出口温度、换热量，反算体积流量。
   - 输出 Excel 文件格式参考 `E:\download\0518板换\codex参考.xlsx` 的防冻液区域，当前覆盖 `Sheet1!A14:F18`。

## 3. 主要入口

启动 GUI：

```powershell
python -m refprop_to_ccm --gui
```

或：

```powershell
.\run_gui.bat
```

GUI 启动后先进入“功能选择”主页，包含：

```text
REFPROP 到 STAR-CCM+
防冻液物性计算
```

REFPROP 命令行：

```powershell
python -m refprop_to_ccm --config .\examples\config.r454c.yaml --no-run-star
```

防冻液命令行示例：

```powershell
python -m refprop_to_ccm --coolant-xlsx --coolant-temperature 57 --coolant-volume-flow-l-min 25 --coolant-inlet-temperature 42 --coolant-outlet-temperature 66.5 --coolant-output .\out\coolant_properties.xlsx
```

反算出口温度：

```powershell
python -m refprop_to_ccm --coolant-xlsx --coolant-solve outlet-temperature --coolant-temperature 57 --coolant-volume-flow-l-min 25 --coolant-inlet-temperature 42 --coolant-heat-transfer-w 36832.8048795 --coolant-output .\out\coolant_properties_outlet.xlsx
```

反算体积流量：

```powershell
python -m refprop_to_ccm --coolant-xlsx --coolant-solve volume-flow --coolant-temperature 57 --coolant-inlet-temperature 42 --coolant-outlet-temperature 66.5 --coolant-heat-transfer-w 36832.8048795 --coolant-output .\out\coolant_properties_flow.xlsx
```

## 4. 当前源码结构

核心源码：

```text
refprop_to_ccm\__main__.py
refprop_to_ccm\cli.py
refprop_to_ccm\config.py
refprop_to_ccm\core.py
refprop_to_ccm\egasp_client.py
refprop_to_ccm\gui.py
refprop_to_ccm\models.py
refprop_to_ccm\refprop_client.py
refprop_to_ccm\starccm.py
refprop_to_ccm\tables.py
refprop_to_ccm\units.py
```

最小 EGASP 运行文件：

```text
egasp\LICENSE
egasp\src\egasp\core.py
egasp\src\egasp\validate.py
egasp\src\egasp\data\egasp_data.py
```

`egasp_client.py` 通过文件路径加载上述 EGASP 最小子集，不依赖 `egasp.__init__`，避免触发 `rich_argparse` 等 CLI 依赖。

## 5. 依赖

`requirements.txt` 当前包含：

```text
ctREFPROP>=0.10.5
PyYAML>=6.0
numpy>=2.0.0
```

`numpy` 用于 EGASP 插值计算。

## 6. 已确认环境

- REFPROP 默认路径：`C:\Program Files (x86)\REFPROP`
- 环境变量 `RPprefix` 应指向 REFPROP 根目录。
- R454C 在当前 REFPROP 安装中可通过 `MIXTURES\R454C.MIX` 加载。
- STAR-CCM+ 调用仍依赖用户提供的 `.sim`、连续体名、相名和 STAR 可执行文件路径。

## 7. 重要边界

- STAR-CCM+ 宏只写入已有连续体、已有相和已有材料属性。
- 宏不新建连续体、不选择模型、不新建相、不重命名相。
- 防冻液功能当前只生成参数表，不直接写入 STAR-CCM+。
- 防冻液计算不硬编码参考表样例数值，按 EGASP 数据实时计算。
- 参考表样例中的部分数值可能不等于默认体积浓度 50% 的计算结果。

## 8. 常用验证

编译检查：

```powershell
python -m compileall .\refprop_to_ccm .\egasp\src\egasp
```

GUI 导入检查：

```powershell
python -c "import refprop_to_ccm.gui; print('ok')"
```

GUI 页面切换检查：

```powershell
@'
from refprop_to_ccm.gui import RefpropToCcmApp
app = RefpropToCcmApp()
try:
    app.update_idletasks()
    app._show_refprop_page()
    app.update_idletasks()
    app._show_coolant_page()
    app.update_idletasks()
    app._show_home_page()
    app.update_idletasks()
    print('gui page switch ok')
finally:
    app.destroy()
'@ | python -
```

防冻液表生成检查：

```powershell
python -m refprop_to_ccm --coolant-xlsx --coolant-temperature 57 --coolant-volume-flow-l-min 25 --coolant-inlet-temperature 42 --coolant-outlet-temperature 66.5 --coolant-output .\out\coolant_properties.xlsx
```

REFPROP 输出检查：

```powershell
python -m refprop_to_ccm --config .\examples\config.r454c.yaml --no-run-star
```

## 9. 提交前清理

以下目录/文件是生成物，不应提交：

```text
out\
temp\
build\
dist\
release\
__pycache__\
*.pyc
*.class
*.log
*.sim
*.sim~
```

`.gitignore` 已覆盖常见生成物。验证命令运行后会重新生成 `out\` 和 `__pycache__\`，提交前需要清理。
