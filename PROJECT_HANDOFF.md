# refprop-to-ccm 项目交接文档

更新时间：2026-05-19

本文档用于让新对话直接接手 `E:\code\refprop-to-ccm`。只记录后续开发需要的规则、已确认事实、当前功能边界和下一步建议。

## 1. 项目规则

- 项目路径：`E:\code\refprop-to-ccm`
- 系统环境：Windows + PowerShell
- 批量删除或批量修改文件前，必须先向用户申请权限。
- 回答必须基于事实，不能编造。
- 修改或创建非代码文件时，默认使用 UTF-8。
- 代码中不能出现 API key、账号密码等隐私。
- 本项目已经是本地 Git 仓库；修改后先检查 `git status`，不要误提交生成文件。
- 测试或临时文件统一放到 `E:\code\refprop-to-ccm\temp`，每次运行后清理 `temp`，保证仓库干净。

## 2. 已确认本机环境

- REFPROP 路径：`C:\Program Files (x86)\REFPROP`
- 环境变量 `RPprefix` 指向：`C:\Program Files (x86)\REFPROP`
- REFPROP `MIXTURES` 目录存在：`R454C.MIX`
- STAR-CCM+ 版本：Simcenter STAR-CCM+ 2602 Build 21.02.007
- STAR-CCM+ 可执行文件：

```text
E:\Program Files\STAR-CCM_202602\starccm_2026\21.02.007-R8\STAR-CCM+21.02.007-R8\star\lib\win64\clang20.1vc14.2-r8\lib\starccm+.exe
```

- STAR 自带 JDK：

```text
E:\Program Files\STAR-CCM_202602\starccm_2026\21.02.007-R8\jdk\win64\jdk21.0.8\bin\javac.exe
```

## 3. 当前项目文件

核心源码在 `refprop_to_ccm\`：

```text
__init__.py
__main__.py
cli.py
config.py
core.py
gui.py
models.py
refprop_client.py
starccm.py
tables.py
units.py
```

其他保留文件：

```text
.gitignore
README.md
PROJECT_HANDOFF.md
requirements.txt
run_gui.bat
examples\config.r454c.yaml
```

已清理或忽略的内容：

- `out/`、`temp/`、`build/`、`dist/`、`release/`、`no-use/`、`*.sim`、`*.sim~`、`*.log` 都不应进入 Git。
- `RefpropToCcm.spec` 和 `refprop_to_ccm_gui.py` 已删除；以后如果要重新打包 exe，应重新生成打包文件。
- 旧打包输出和运行输出可再生，不是核心源码。

## 4. 当前工具目标和边界

目标：用户输入制冷剂名称、饱和压力或饱和温度、气态/液态温度范围、STAR-CCM+ 项目路径等，调用 REFPROP 生成制冷剂物性，并生成 STAR-CCM+ Java 宏写入指定 `.sim`。

当前重要边界：

- 当前宏只写入已有连续体、已有相和已有材料属性。
- 当前宏不新建连续体、不选择连续体模型、不新建相、不重命名相。
- 目标连续体名、气相名、液相名必须与 `.sim` 中实际对象一致。
- 相名默认：
  - `gas`
  - `liquid`

GUI 已支持：

- 输入制冷剂名称，默认 `R454C`
- 输入饱和压力 MPa 或饱和温度 C
- 计算饱和温度
- 气态温度范围和步长
- 液态温度范围和步长
- 气态比热来源选择：`Cp(T)` 表或焓表
- 液态材料属性选择：按饱和状态填常数，或按温度表填
- 选择原始 `.sim`、另存 `.sim` 和 STAR-CCM+ 程序
- 输入目标连续体名、液相名、气相名
- 保存/载入界面 JSON 配置
- 可选生成后立即运行 STAR-CCM+

底层校验：

- 气态温度起点必须大于饱和温度。
- 液态表模式下，液态温度终点必须小于饱和温度。
- 温度步长必须大于 0。
- 温度终点不能小于温度起点。
- 目标连续体名不能为空。

## 5. 常用命令

启动 GUI：

```powershell
cd /d E:\code\refprop-to-ccm
.\run_gui.bat
```

或：

```powershell
cd /d E:\code\refprop-to-ccm
python -m refprop_to_ccm --gui
```

只生成物性文件和 STAR 宏，不运行 STAR：

```powershell
cd /d E:\code\refprop-to-ccm
python -m refprop_to_ccm --config .\examples\config.r454c.yaml --no-run-star
```

生成后运行 STAR：

```powershell
cd /d E:\code\refprop-to-ccm
python -m refprop_to_ccm --config .\examples\config.r454c.yaml
```

语法检查：

```powershell
cd /d E:\code\refprop-to-ccm
python -m compileall .\refprop_to_ccm
```

## 6. REFPROP 计算和输出

默认单位：

- 温度：C
- 压力：MPa

R454C 加载方式：

- 优先使用 `C:\Program Files (x86)\REFPROP\MIXTURES\R454C.MIX`

饱和状态：

- 支持按压力求饱和温度。
- 支持按温度求饱和压力。
- 标准状态温度按用户要求等于饱和温度。
- 标准状态焓按用户要求等于对应饱和状态焓。
- 生成热按用户要求等于对应饱和状态焓。
- 密度温度导数按用户要求填常数 `0`。

气态表字段：

```text
Temperature (C)
Density (kg/m3)
Equivalent Specific Heat (J/kg-K)
Equivalent Thermal Conductivity (W/m-K)
Equivalent Dynamic Viscosity (Pa-s)
Enthalpy (J/kg)
```

液态表字段与气态表相同，仅在 `liquid_table.mode: table` 时生成。

默认输出目录：`out`

可能生成：

```text
out\liquid_properties.json
out\liquid_properties.csv
out\vapor_properties.csv
out\summary.json
out\apply_refprop_to_star.java
out\starccm_run.log
```

## 7. STAR-CCM+ 写入逻辑

宏执行流程：

1. STAR 打开原始 `.sim`。
2. 执行生成的 Java 宏。
3. 查找指定连续体。
4. 查找 `gas` 和 `liquid` 相。
5. 查找已有相材料对象。
6. 导入气态表；液态表模式下导入液态表。
7. 写材料属性。
8. 另存为新 `.sim`。

气态写入重点：

- 饱和温度
- 标准状态温度
- 标准状态焓
- 分子量
- 密度温度导数常数 `0`
- 生成热
- 用户自定义 EOS 密度表
- 用户自定义 EOS 焓表
- 比热表或焓表
- 导热率表
- 动力粘度表

液态写入重点：

- 饱和温度
- 比热
- 标准状态温度
- 标准状态焓
- 导热率
- 动力粘度
- 密度，优先多项式密度，失败时写恒密度
- 分子量
- 生成热
- 液态表模式下尝试绑定比热、密度、导热率、动力粘度表

已验证限制：

- 如果目标液相使用“恒密度”模型，STAR 不接受密度温度表；宏会保留饱和状态常密度。
- 比热、导热率、动力粘度能否绑定表，取决于目标材料属性当前支持的方法。
- 气态表导入失败必须停止保存；液态表模式下液态表导入失败也必须停止保存。

## 8. 已做过的 STAR 验证

曾用 `out\star-try.sim` 做过真实 STAR 测试；该输出后来可能被清理。

当时验证的目标对象：

- 连续体名：`R454C`
- 相名：`gas`、`liquid`
- gas 相模型：湍流、气体、用户自定义 EOS
- liquid 相模型：湍流、液体、恒密度

表格模式真实运行结果：

- STAR 找到连续体 `R454C`
- 液体表和气体表导入成功
- 液态比热、导热率、动力粘度表绑定成功
- 液态密度表未绑定，原因是测试文件液相为“恒密度”模型
- 气态用户自定义 EOS 密度表、焓表、比热表绑定成功
- 最终成功另存 `.sim`

## 9. R454C 冷凝器 STAR 设置建议

R454C 是非共沸混合工质，有温度滑移。冷凝器冷凝过程建议优先用：

```text
多相 + 混合多相流 MMP + 多相相互作用 + 基于传热的沸腾/冷凝
```

不建议把“两相热力学平衡”作为主模型；它会强制两相热平衡/同温，通常不利于表达 R454C 冷凝温度滑移。

连续体建议启用：

- 三维
- 定常，先跑通；流型波动明显时再改隐式非定常
- 多相
- 混合多相 MMP
- 多相相互作用
- 分离流
- 分离多相温度
- 分离流体焓或对应能量/焓模型
- 湍流
- 雷诺平均纳维-斯托克斯
- K-Epsilon 湍流
- 可实现的 K-Epsilon 两层模型
- 两层全 y+ 壁面处理
- 壁面距离
- 梯度
- 重力，尤其是水平管、竖直管、分层流、液体聚集时
- 单元质量校正，网格质量一般或复杂管道可选

一般不选：

- 分离流体等温
- 求解插值，除非做旧结果/旧网格映射
- 液膜，除非明确做壁面液膜模型
- 多孔介质，除非把芯体等效成多孔区
- 拉格朗日多相、离散多相 DMP
- 自适应网格、网格变形
- 壁面成核沸腾，冷凝器冷凝不应作为第一版选择
- 相替换，属于数值修补类模型，不是物理冷凝模型
- 交界面湍流阻尼，第一版先不选；后续若大界面湍流过强再评估

相间相互作用建议：

- `MMP-MMP 相间相互作用`
- `滑移速度`
- `相互作用面积密度`
- `相互作用长度尺度`
- `多相材料`
- `基于传热的沸腾/冷凝`

关键相设置：

```text
主相：liquid
次相：gas
```

边界条件建议：

- 冷凝器入口：质量流量入口，gas 体积分数 1，入口温度高于对应压力下 R454C 露点温度。
- 出口：压力出口，回流相分数和回流温度要合理设置。
- 压力：核对绝压/表压，不要混用。
- 壁面：优先共轭传热；简化时可用固定壁温、固定热流或对流换热系数，但不要给互相矛盾的热边界。

## 10. 板式换热器前处理工具规划

参考表格：

```text
E:\download\0518板换\副本03-板换冷凝热力学计算.xlsx
```

已读取到的事实：

- 工作簿包含 `冷凝-R134A` 和 `冷凝-R454C`。
- 每个工作表范围约为 `A1:O546`。
- 工作簿依赖外部链接 `C:\Program Files (x86)\REFPROP\REFPROP.XLA`。
- `冷凝-R454C` 工作表中约有 4031 个 REFPROP 公式。
- `冷凝-R454C` 中 `J47:L109` 有 `#VALUE!`，原因是气态表从冷凝温度附近开始取点，R454C 露点/泡点之间是两相区，REFPROP 对两相区部分单相物性会报错。

后续工具规划：

- 乙二醇水溶液物性不需要重新写代码计算，使用已有代码。
- 不需要完整计算制冷循环 1-2-3-4 四个点。
- 蒸发器只使用 4-1 点数据。
- 冷凝器只使用 2-3 点数据。
- 参数计算和 STAR 设置拆成两个模块。
- 参数计算模块输出标准化 JSON/CSV 参数包，不直接写 STAR-CCM+。
- STAR 设置模块读取参数包，再设置已有 `.sim` 中的材料、边界、初始场等。

参数计算模块建议输出：

- `case_summary.json`
- `coolant_properties.json` 或 `coolant_properties.csv`
- `refrigerant_state_points.json`
- `refrigerant_liquid_properties.csv`
- `refrigerant_vapor_properties.csv`
- `star_boundary_inputs.json`

实现顺序建议：

1. 先设计参数计算模块的输入/输出格式，不接 STAR。
2. 用 Excel 中 `冷凝-R454C` 的 2-3 点结果作为对照样例。
3. 修正 R454C 气态表进入两相区的问题，只生成过热气体区表。
4. 接入已有乙二醇水溶液物性代码。
5. 再做 STAR 设置模块，读取参数包并生成或执行 STAR Java 宏。

## 11. 新对话继续工作建议

优先查看：

```text
E:\code\refprop-to-ccm\refprop_to_ccm\starccm.py
E:\code\refprop-to-ccm\refprop_to_ccm\gui.py
E:\code\refprop-to-ccm\examples\config.r454c.yaml
```

建议验证顺序：

1. 运行 `python -m compileall .\refprop_to_ccm`。
2. 运行 `python -m refprop_to_ccm --config .\examples\config.r454c.yaml --no-run-star`。
3. 用 STAR 自带 JDK 编译生成的 `out\apply_refprop_to_star.java`。
4. 如果要真实运行 STAR，确认 `.sim`、连续体名、相名和目标模型都已经在 STAR 中设置好。
5. 如果用户再次要求打包 exe，重新生成 `dist`/`release` 和打包配置。
6. 删除生成文件前，先列清单并获得用户明确确认。

## 12. 资料来源

- STAR-CCM+ 基于传热的沸腾/冷凝：`https://starccm.jachwang.co.uk/GUID-2E3A0977-2042-4DFA-9942-21859DDE79C9.html`
- STAR-CCM+ MMP 模型：`https://starccm.jachwang.co.uk/GUID-85905021-3B1E-4577-944B-1104CD63DF88.html`
- STAR-CCM+ MMP 中沸腾和冷凝建模：`https://starccm.jachwang.co.uk/GUID-08213632-E978-45A1-875D-C234BBAB6A08.html`
- STAR-CCM+ 两相热力学平衡：`https://starccm.jachwang.co.uk/GUID-507DD300-0C60-439F-9A00-15FAB5600150.html`
- Honeywell Solstice 454C 技术数据表：`https://www.solstice.com/content/dam/advancedmaterials/en/documents/document-lists/refrigerants/technical/Technical-Data-Sheet-Solstice-454C.pdf`
