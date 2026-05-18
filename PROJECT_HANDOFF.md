# refprop-to-ccm 项目交接文档

更新时间：2026-05-19

本文档用于在新对话中快速恢复上下文，继续完成 `E:\code\refprop-to-ccm` 项目。

## 1.用户要求和项目规则

- 项目路径：`E:\code\refprop-to-ccm`
- 系统环境：Windows + PowerShell
- 用户要求：
  - 如果需要批量删除或批量修改文件，必须先向用户申请权限。
  - 所有回答必须基于事实，不能编造。
  - 修改或创建非代码文件时，默认使用 UTF-8。
  - 所有代码中不能出现 API key、账号密码等隐私。
- 当前目录已经是本地 Git 仓库；仍然不能随意批量删除或批量修改文件，必须按用户规则先确认。

## 2.本机已确认环境

- REFPROP 路径：`C:\Program Files (x86)\REFPROP`
- 环境变量 `RPprefix` 指向：`C:\Program Files (x86)\REFPROP`
- REFPROP `MIXTURES` 目录中存在：`R454C.MIX`
- STAR-CCM+ 可执行文件：

```text
E:\Program Files\STAR-CCM_202602\starccm_2026\21.02.007-R8\STAR-CCM+21.02.007-R8\star\lib\win64\clang20.1vc14.2-r8\lib\starccm+.exe
```

- STAR-CCM+ 版本：Simcenter STAR-CCM+ 2602 Build 21.02.007
- STAR 自带 JDK：

```text
E:\Program Files\STAR-CCM_202602\starccm_2026\21.02.007-R8\jdk\win64\jdk21.0.8\bin\javac.exe
```

## 3.当前保留的主项目文件

核心源码：

```text
refprop_to_ccm\__init__.py
refprop_to_ccm\__main__.py
refprop_to_ccm\cli.py
refprop_to_ccm\config.py
refprop_to_ccm\core.py
refprop_to_ccm\gui.py
refprop_to_ccm\models.py
refprop_to_ccm\refprop_client.py
refprop_to_ccm\starccm.py
refprop_to_ccm\tables.py
refprop_to_ccm\units.py
```

其他文件：

```text
README.md
PROJECT_HANDOFF.md
requirements.txt
run_gui.bat
examples\config.r454c.yaml
.gitignore
```

说明：

- `RefpropToCcm.spec` 和 `refprop_to_ccm_gui.py` 曾用于打包探索，后来已按用户确认删除；如果以后重新打包 exe，应重新生成所需打包文件。
- `build`、`dist`、`release` 曾按用户确认删除过；如果现在又出现，是后续构建重新生成的。
- `out`、`temp` 和 `refprop_to_ccm\__pycache__` 是运行/测试生成内容，可再生，不是核心源码。
- 当前目录下可能有 `RefEquiv`、`Polynomial-Fitter` 等其他目录，不属于本项目主工具，除非用户明确要求，否则不要处理它们。

## 4.工具目标

做一个工具，用户输入：

- 制冷剂名称
- 饱和压力或饱和温度
- 气态温度范围和步长
- 液态材料属性方式
- STAR-CCM+ 原始 `.sim` 和另存 `.sim`
- STAR-CCM+ 程序路径
- 目标连续体名、气相名、液相名

工具自动调用 REFPROP 生成 R454C 等制冷剂物性，并生成 STAR-CCM+ Java 宏，把物性写入指定 `.sim` 中已有连续体的已有材料属性。

重要：当前宏不新建连续体、不选择模型、不创建相，只往用户指定的已有连续体、已有 `gas` 和 `liquid` 相材料属性里填数。

## 5.启动和常用命令

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

代码语法检查：

```powershell
cd /d E:\code\refprop-to-ccm
python -m compileall .\refprop_to_ccm
```

## 6.当前功能状态

GUI 已支持：

- 输入制冷剂名称，默认 `R454C`
- 输入饱和压力 MPa 或饱和温度 C
- 按钮“计算饱和温度”
- 气态温度范围和步长
- 气态压力默认等于饱和压力，也可单独指定
- 气态比热来源可选：
  - `Cp(T)` 表
  - 焓表
- 液态材料属性可选：
  - 按饱和状态填常数
  - 像气体一样按温度表填
- 液态和气态温度范围分别设置，互不共用
- 选择原始 `.sim` 文件和另存 `.sim` 文件
- 选择 STAR-CCM+ 程序
- 输入目标连续体名、液相名、气相名
- 勾选“生成后立即运行 STAR-CCM+”
- 保存/载入界面 JSON 配置
- 打开输出目录

底层校验：

- 气态温度起点必须大于饱和温度。
- 液态温度表模式下，液态温度终点必须小于饱和温度。
- 气态/液态温度步长必须大于 0。
- 温度终点不能小于温度起点。
- 目标连续体名必须填写，因为宏只写入已有连续体。

## 7.REFPROP 计算逻辑

默认单位：

- 温度：C
- 压力：MPa

R454C：

- 优先按 REFPROP 混合工质文件加载：`MIXTURES\R454C.MIX`

饱和状态：

- 支持按压力求饱和温度。
- 支持按温度求饱和压力。

液态饱和参数：

- 饱和温度
- 饱和压力
- 比热
- 标准状态温度
- 导热率
- 动力粘度
- 密度
- 分子量
- 饱和液体焓
- 饱和气体焓
- 液态标准状态焓
- 气态标准状态焓
- 液态生成热候选值
- 气态生成热候选值
- 密度温度导数，按用户要求填常数 `0`

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

## 8.输出文件

默认输出目录：`out`

可能生成：

```text
out\liquid_properties.json
out\liquid_properties.csv       # 仅液态表模式生成
out\vapor_properties.csv
out\summary.json
out\apply_refprop_to_star.java
out\starccm_run.log             # 仅运行 STAR 时生成
```

注意：`out` 是生成目录，可删除后重新生成。

## 9.STAR-CCM+ 写入逻辑

当前 `starccm.py` 的策略：

- STAR 打开原始 `.sim`
- 执行生成的 Java 宏
- 查找指定连续体
- 查找指定相：
  - `gas`
  - `liquid`
- 查找已有相材料对象
- 导入气态表
- 如果液态选择表模式，导入液态表
- 写材料属性
- 另存为新 `.sim`

宏不做：

- 不新建连续体
- 不选择连续体模型
- 不新建相
- 不重命名相
- 不直接修改 `.sim` 二进制

气态写入：

- 饱和温度
- 标准状态温度，等于饱和温度
- 分子量
- 密度温度导数，常数 0
- 生成热，按用户要求等于饱和气体焓
- 用户自定义 EOS 密度表
- 用户自定义 EOS 焓表
- 气态比热：
  - 选择 `cp_table` 时绑定 Cp(T) 表
  - 选择 `enthalpy_table` 时以焓表作为主要能量输入
- 导热率表
- 动力粘度表

液态写入：

- 饱和温度
- 比热
- 标准状态温度，等于饱和温度
- 导热率
- 动力粘度
- 密度，优先多项式密度，失败时写恒密度
- 分子量
- 生成热，按用户要求等于饱和液体焓
- 液态选择表模式时，尝试绑定：
  - 比热表
  - 密度表
  - 导热率表
  - 动力粘度表

已验证限制：

- 如果目标 STAR-CCM+ 液相使用“恒密度”模型，STAR 不接受密度温度表；宏会保留饱和状态常密度，并在日志中记录密度表未绑定。
- 比热、导热率、动力粘度是否能绑定表，取决于目标材料属性当前支持的表格方法。
- 宏已经设置：气态表导入失败必须停止保存；液态选择表模式时液态表导入失败也必须停止保存。

## 10.真实 STAR 验证结果

曾用 `out\star-try.sim` 做过真实 STAR 测试。

只读检查确认该测试 `.sim` 中：

- 连续体名：`R454C`
- 相名：
  - `gas`
  - `liquid`
- gas 相模型包括：
  - 湍流
  - 气体
  - 用户自定义 EOS
- liquid 相模型包括：
  - 湍流
  - 液体
  - 恒密度

表格模式真实运行结果：

- STAR 找到连续体 `R454C`
- 导入液体表成功
- 导入气体表成功
- 液态比热表绑定成功
- 液态导热率表绑定成功
- 液态动力粘度表绑定成功
- 液态密度表未绑定，原因是测试文件液相为“恒密度”模型
- 气态用户自定义 EOS 密度表、焓表、比热表绑定成功
- 最终成功另存 `.sim`

注意：这些验证输出后来可能被清理；必要时重新运行命令生成。

## 11.示例配置重点

`examples\config.r454c.yaml` 当前应包含：

```yaml
fluid:
  name: R454C

saturation:
  type: pressure
  value: 0.8
  unit: MPa

gas_table:
  pressure:
  pressure_unit: MPa
  temperature_start: 30
  temperature_end: 120
  temperature_step: 2
  temperature_unit: C
  specific_heat_source: cp_table

liquid_table:
  mode: saturation
  temperature_start: 0
  temperature_end: 9
  temperature_step: 1
  temperature_unit: C

starccm:
  sim_file: E:\case\input.sim
  output_sim_file: E:\case\input_refprop.sim
  continuum_name: R454C
  liquid_phase_name: liquid
  vapor_phase_name: gas
  starccm_exe: E:\Program Files\STAR-CCM_202602\starccm_2026\21.02.007-R8\STAR-CCM+21.02.007-R8\star\lib\win64\clang20.1vc14.2-r8\lib\starccm+.exe

output:
  directory: .\out
```

液态表模式时改：

```yaml
liquid_table:
  mode: table
  temperature_start: 0
  temperature_end: 9
  temperature_step: 1
  temperature_unit: C
```

## 12.冷凝器中 R454C 连续体模型建议

R454C 是 zeotropic blend，有温度滑移。做冷凝器冷凝过程时，推荐路线：

```text
多相 + 混合多相流 MMP + 多相相互作用 + 基于传热的沸腾/冷凝
```

不建议把“两相热力学平衡”作为主模型，因为它更像把两相强制热平衡/同温的近似，不能很好表达 R454C zeotropic blend 的冷凝温度滑移。

连续体建议启用：

- 三维
- 定常，先跑通；若流型波动明显，再改隐式非定常
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
- 多孔介质，除非把翅片区/芯体等效成多孔区
- 拉格朗日多相
- 离散多相 DMP
- 自适应网格
- 网格变形
- 湍流抑制模型
- 涡流抑制模型
- 湍流粘度用户缩放
- Casting
- 协同仿真
- 声学模态分析
- 文件传输
- 气动声学
- 电化学
- 电磁
- 虚拟体
- 虚拟盘体
- 被动标量
- 重定位
- 间隙闭合

## 13.多相相互作用模型建议

对 `gas-liquid` 相间相互作用：

必须或建议保留：

- `MMP-MMP 相间相互作用`
- `滑移速度`
- `相互作用面积密度`
- `相互作用长度尺度`
- `多相材料`
- `基于传热的沸腾/冷凝`

可选：

- `表面张力`
  - 小通道、微通道、液膜、分层流、液滴分布重要时建议选。
  - 需要填 R454C 气液表面张力和壁面接触角。

先不要选：

- `壁面成核沸腾`
  - 这是壁面沸腾模型，适合加热壁面产生气泡；冷凝器冷凝不应选。
- `相替换`
  - 这是数值修补类模型，不是物理冷凝模型。
- `交界面湍流阻尼`
  - 第一版先不选；如果后续大界面附近湍流过强、环状流/分层流明显，再考虑。

关键：

- `基于传热的沸腾/冷凝` 要求液体是主相、气体是次相。
- 即相间相互作用应设置为：

```text
主相：liquid
次相：gas
```

## 14.边界条件建议

冷凝器入口：

- 质量流量入口
- gas 体积分数 1
- liquid 体积分数 0 或很小
- 入口温度高于对应压力下 R454C 露点温度
- 压力应使用绝对压力思路核对，不要混淆表压/绝压

出口：

- 压力出口
- 回流相分数要合理设置，不能全默认
- 回流温度设为接近出口液相或两相温度

壁面：

- 最好做共轭传热：制冷剂流道 + 管壁固体 + 外侧空气/水侧
- 简化时可用固定壁温、固定热流或对流换热系数，但不要同时给互相矛盾的热边界

## 15.资料来源链接

STAR-CCM+ 文档页：

- 基于传热的沸腾/冷凝：
  - `https://starccm.jachwang.co.uk/GUID-2E3A0977-2042-4DFA-9942-21859DDE79C9.html`
- MMP 模型：
  - `https://starccm.jachwang.co.uk/GUID-85905021-3B1E-4577-944B-1104CD63DF88.html`
- MMP 中沸腾和冷凝建模：
  - `https://starccm.jachwang.co.uk/GUID-08213632-E978-45A1-875D-C234BBAB6A08.html`
- 两相热力学平衡：
  - `https://starccm.jachwang.co.uk/GUID-507DD300-0C60-439F-9A00-15FAB5600150.html`

R454C 资料：

- Honeywell Solstice 454C 技术数据表：
  - `https://www.solstice.com/content/dam/advancedmaterials/en/documents/document-lists/refrigerants/technical/Technical-Data-Sheet-Solstice-454C.pdf`

## 16.新对话继续工作建议

新对话可以按这个顺序继续：

1. 先打开并检查：

```text
E:\code\refprop-to-ccm\refprop_to_ccm\starccm.py
E:\code\refprop-to-ccm\refprop_to_ccm\gui.py
E:\code\refprop-to-ccm\examples\config.r454c.yaml
```

2. 跑语法检查：

```powershell
cd /d E:\code\refprop-to-ccm
python -m compileall .\refprop_to_ccm
```

3. 生成默认输出：

```powershell
python -m refprop_to_ccm --config .\examples\config.r454c.yaml --no-run-star
```

4. 如果要验证 STAR 宏语法，用 STAR 自带 JDK 编译生成的 `out\apply_refprop_to_star.java`。

5. 如果要真实运行 STAR，必须确认：

- `starccm.sim_file` 指向真实存在的 `.sim`
- `starccm.continuum_name` 是 `.sim` 中真实已有连续体名
- 相名是 `gas` 和 `liquid`，或配置文件里改成真实相名
- 目标连续体已经选好模型；当前工具不会替用户选择模型

6. 如果用户再次要求打包 exe，需要重新生成 `dist`/`release`，因为旧打包输出曾被清理过。

7. 如果用户要求删除生成文件，必须先列清单并获得明确确认后再删除。

## 17.2026-05-18 本地 Git 整理记录

用户要求检查项目目录，把不需要的内容删除或放到单独文件夹，并对有用内容做本地 Git 提交。2026-05-18 初次处理采用“移动到 `no-use`，不直接删除”的方式；后续用户明确确认只删除第一清单，因此这些可再生或无关内容不应再保留在项目根目录。

第一清单内容：

```text
no-use
out
refprop_to_ccm\__pycache__
RefEquiv
Polynomial-Fitter
RefpropToCcm.spec
refprop_to_ccm_gui.py
```

说明：

- `out` 是运行生成目录，可重新生成。
- `refprop_to_ccm\__pycache__` 是 Python 缓存，可重新生成。
- `RefEquiv` 和 `Polynomial-Fitter` 是放在本项目根目录下的其他项目，不属于 `refprop-to-ccm` 主工具，所以移入 `no-use` 保存。
- `RefpropToCcm.spec` 和 `refprop_to_ccm_gui.py` 曾用于打包探索，当前实现不依赖它们。
- `.gitignore` 已加入 `no-use/`、`temp/`、`out/`、`build/`、`dist/`、`release/`、`*.sim`、`*.sim~`、`*.log`、`.env` 等规则，避免生成文件、仿真文件和无关目录进入 Git。

本地 Git 仓库应只提交主项目源码和说明文件：

```text
.gitignore
README.md
PROJECT_HANDOFF.md
requirements.txt
run_gui.bat
examples\config.r454c.yaml
refprop_to_ccm\*.py
```

## 18.2026-05-19 板式换热器仿真前处理工具规划

用户提供的参考表格：

```text
E:\download\0518板换\副本03-板换冷凝热力学计算.xlsx
```

已读取到的事实：

- 工作簿包含两个工作表：`冷凝-R134A` 和 `冷凝-R454C`。
- 每个工作表范围约为 `A1:O546`。
- 工作簿依赖外部链接 `C:\Program Files (x86)\REFPROP\REFPROP.XLA`。
- `冷凝-R454C` 工作表中约有 4031 个 REFPROP 公式。
- `冷凝-R454C` 中 `J47:L109` 有 `#VALUE!`，原因是气态表从冷凝温度附近开始取点，R454C 为非共沸混合物，露点/泡点之间为两相区，REFPROP 对两相区的部分单相物性如 Cp、导热率、粘度会报错。

Excel 表中可借鉴的计算结构：

- 防冻液侧输入体积流量、入口/出口温度、密度、比热、导热率、动力粘度。
- 防冻液侧质量流量按 `体积流量 / 1000 / 60 * 密度` 计算。
- 防冻液侧换热量按 `质量流量 * Cp * |出口温度 - 入口温度|` 计算。
- 制冷剂侧按 REFPROP 获取冷凝压力下的状态、饱和液/饱和气物性、焓差、质量流量、干度、气相体积分数和材料属性表。
- 液态制冷剂表应只取过冷液体区。
- 气态制冷剂表应只取过热气体区。
- 两相区不应作为单相材料属性表直接写给 STAR-CCM+。

用户对规划的修正要求：

- 乙二醇水溶液物性不需要重新写代码计算，已有现成代码可用。
- 不需要完整计算制冷循环 1-2-3-4 四个点。
- 蒸发器只需要使用 4-1 点数据。
- 冷凝器只需要使用 2-3 点数据。
- 最终工具不要直接把计算结果写入 STAR-CCM+。
- 工具应拆成两个模块：
  - 模块 1：输入参数，计算 STAR-CCM+ 仿真需要的参数。
  - 模块 2：根据模块 1 输出的参数设置 STAR-CCM+。
- 以上仅为规划记录，当前不要写代码实现。

建议的工具架构：

```text
参数计算模块
  输入：防冻液参数、制冷剂参数、板换结构参数、工况类型
  输出：标准化 JSON/CSV 参数包

STAR 设置模块
  输入：参数计算模块生成的 JSON/CSV 参数包、目标 .sim、连续体/区域/边界名称
  输出：STAR-CCM+ 设置宏或执行后的另存 .sim
```

参数计算模块建议输入：

- 工况类型：`condenser` 或 `evaporator`
- 防冻液：
  - 溶液类型，例如乙二醇水溶液
  - 浓度
  - 入口温度
  - 出口温度或目标换热量
  - 体积流量或质量流量
  - 物性来源，调用现成代码，不在本工具内重新实现物性公式
- 制冷剂：
  - 名称，例如 `R454C`
  - 冷凝器工况：2 点入口、3 点出口相关参数
  - 蒸发器工况：4 点入口、1 点出口相关参数
  - 压力、温度或焓中足以确定状态的输入
  - 物性表温度范围和步长
- 板换结构：
  - 有效片数
  - 防冻液侧层数
  - 制冷剂侧层数或流程分配
  - STAR-CCM+ 中区域、边界、连续体、相名的映射

参数计算模块建议输出：

- `case_summary.json`
  - 工况类型
  - 输入摘要
  - 单位说明
  - 关键校核量
- `coolant_properties.json` 或 `coolant_properties.csv`
  - 防冻液密度、比热、导热率、动力粘度
  - 如现成代码支持温度表，可输出随温度变化表
- `refrigerant_state_points.json`
  - 冷凝器只记录 2 点和 3 点
  - 蒸发器只记录 4 点和 1 点
  - 包含温度、压力、焓、熵、相态、干度等可用字段
- `refrigerant_liquid_properties.csv`
  - 液态单相区材料属性表
- `refrigerant_vapor_properties.csv`
  - 气态单相区材料属性表
- `star_boundary_inputs.json`
  - 防冻液入口质量流量、温度、材料属性
  - 制冷剂入口质量流量、温度、压力、相体积分数
  - 出口压力或回流设置建议
  - 初始场建议值

STAR 设置模块建议职责：

- 不负责重新计算热力学。
- 只读取参数计算模块输出的 JSON/CSV。
- 在已有 STAR-CCM+ `.sim` 中查找已有连续体、区域、边界、相和材料。
- 根据参数设置：
  - 防冻液材料属性
  - 制冷剂气相材料属性
  - 制冷剂液相材料属性
  - 入口质量流量
  - 入口温度
  - 入口相体积分数
  - 出口压力
  - 必要的初始场
- 是否自动运行 STAR 可作为可选项，但模块边界上应保持“参数计算”和“STAR 设置”分离。

后续实现建议：

1. 先只做参数计算模块的输入/输出格式设计，不接 STAR。
2. 用 Excel 中 `冷凝-R454C` 的 2-3 点结果作为对照样例。
3. 修正 R454C 气态表进入两相区的问题，只生成过热气体区表。
4. 接入已有乙二醇水溶液物性代码。
5. 再做 STAR 设置模块，读取参数包并生成/执行 STAR Java 宏。

## 19.2026-05-19 临时文件和测试输出规则

用户新增要求：以后每次测试或添加临时文件，都必须在项目根目录创建或使用 `temp` 文件夹，并在每次运行后清理 `temp` 文件夹，保证仓库干净。

执行规则：

- 临时 Excel、JSON、CSV、日志、宏文件、截图、试运行输出和中间分析文件，都放到 `E:\code\refprop-to-ccm\temp`。
- 每次测试或试运行结束后，清理 `temp` 中本次生成的内容。
- 不把临时文件放到项目根目录、源码目录或长期输出目录，除非用户明确要求保存为交付物。
- `temp/` 已写入 `.gitignore`，默认不进入 Git。
- 如果某个临时结果需要长期保存，先说明原因并等待用户确认，再移动到有明确用途的目录或纳入 Git。
- 提交前检查 Git 状态，确认只包含用户要求的源码、文档、配置或删除记录。
