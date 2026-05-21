# refprop-to-ccm

把 REFPROP 物性数据导出为 STAR-CCM+ 可用的材料参数，并生成一个 Java 宏，把数据写入指定 STAR-CCM+ 项目中已有连续体的已有 gas/liquid 相材料属性。

## 当前版本做什么

1. 从界面或配置文件读取制冷剂、饱和压力或饱和温度、气相表模式、液态属性输入方式、STAR-CCM+ 项目信息。
2. 调用 REFPROP 计算：
   - 饱和温度和饱和压力
   - 液态饱和物性：比热、标准状态温度、导热率、动力粘度、密度、分子量、标准状态焓、生成热候选值
   - 气态固定压力表：可按温度范围直接生成，也可在直接 REFPROP 失败的温度点用 RefEquiv 等效数据替代
   - 可选液态固定饱和压力温度表：温度、密度、等效比热容、等效导热率、等效动力粘度、焓值
3. 输出：
   - `liquid_properties.json`
   - `liquid_properties.csv`，仅在液态选择“按温度表填”时生成
   - `vapor_properties.csv`
   - `apply_refprop_to_star.java`
   - `summary.json`
4. 可选调用 STAR-CCM+，打开原始 `.sim` 并执行宏，默认另存为新 `.sim`。
5. STAR-CCM+ 宏不新建连续体、不选择模型；它会查找指定连续体、gas 相和 liquid 相，并把 REFPROP 结果写入已有材料属性。

## 安装依赖

```powershell
python -m pip install -r requirements.txt
```

本机需要已安装 REFPROP，并且 `RPprefix` 指向 REFPROP 根目录。当前机器已确认：

```text
C:\Program Files (x86)\REFPROP
```

## 使用

打开可视化界面：

```powershell
.\run_gui.bat
```

或者：

```powershell
python -m refprop_to_ccm --gui
```

界面中可以先输入制冷剂名称和饱和压力，然后点击“计算饱和温度”。计算完成后，气相温度起点会默认填为饱和温度上方 `0.001 C`，避开气液边界点；用户仍可手动修改。气相表默认使用“按温度表”模式，此时温度起点不能小于饱和温度；底层生成流程也会再次校验。

如果制冷剂是非共沸混合工质，并且直接按温度/压力从 REFPROP 取两相滑移区附近的比热、导热率或粘度会失败，可以把气相表模式切到 `equivalent_quality`。该模式会先按你输入的温度起点、终点和步长生成同一套温度点；落在泡点到露点滑移区、也就是容易出现 `#VALUE!` 的温度点，会参考 `RefEquiv` 的做法，用 `PQ` 干度路径生成等效比热容、等效导热率和等效动力粘度并替代该点。滑移区外仍使用直接 REFPROP 结果。

液态材料属性有两种方式：

- 按饱和状态填常数：只写入饱和液体状态的常数。
- 按温度表填：按独立的液态温度起点、终点和步长生成 `liquid_properties.csv`，并让 STAR 宏尝试把液态比热、密度、导热率、动力粘度绑定到表格。液态温度终点默认填为饱和温度下方 `0.001 C`，避开气液边界点；用户仍可手动修改；底层校验要求液态温度终点不能大于饱和温度。

注意：如果目标 STAR-CCM+ 液相当前使用“恒密度”模型，STAR 不接受密度温度表；宏会保留饱和状态常密度，并在日志中记录密度表未绑定。比热、导热率、动力粘度是否能绑定，取决于目标材料属性当前支持的表格方法。

气态材料属性的比热来源可以选择 `Cp(T)` 表或焓表。气态和液态温度范围分别设置，互不共用。`equivalent_quality` 模式也使用气态温度起点、终点和步长，保证替代前后的温度步长一致。

目标连续体名称必须填写为 `.sim` 中已经存在的连续体名称；宏不会自动创建或重命名连续体。

复制并修改示例配置：

```powershell
Copy-Item .\examples\config.r454c.yaml .\config.yaml
```

只生成物性文件和 STAR-CCM+ 宏：

```powershell
python -m refprop_to_ccm --config .\config.yaml --no-run-star
```

生成后直接调用 STAR-CCM+：

```powershell
python -m refprop_to_ccm --config .\config.yaml
```

## 配置字段

`gas_table.mode` 可选：

- `temperature`：原有模式，固定压力下按温度范围调用 REFPROP。
- `equivalent_quality`：混合替代模式，先按温度表直接取 REFPROP；失败温度点再用 RefEquiv 的 `PQ` 等效物性补齐。

`gas_table.temperature_step` 在两个模式下都表示输出表格的温度步长。

`gas_table.quality_points` 可填 `auto` 或大于等于 `2` 的整数。干度 Q 是质量含气率：`Q=0` 表示饱和液，`Q=1` 表示饱和气。`auto` 表示按泡点到露点之间需要替代的温度点数量自动决定；手动填整数时，作为 RefEquiv 内部干度离散密度。

`gas_table.viscosity_model` 可选：

- `cicchitti`
- `mcadams`

RefEquiv 对两个粘度模型的提示是：

- `mcadams`：调和平均，基于质量含气率 Q，适用于常规两相流压降计算。
- `cicchitti`：体积加权算术平均，基于气相体积分数，适用于高流速均匀流动，RefEquiv 推荐。

`gas_table.specific_heat_source` 可选：

- `cp_table`
- `enthalpy_table`

`liquid_table.mode` 可选：

- `saturation`
- `table`

示例：

```yaml
liquid_table:
  mode: saturation
  temperature_start: 0
  temperature_end: 9
  temperature_step: 0.1
  temperature_unit: C
```

## 重要说明

STAR-CCM+ 的 Java API 和材料属性路径会随版本、物理模型、相模型设置变化。当前宏采用反射和保守写法查找已有连续体、已有相和已有材料属性；如果某个材料模型或属性路径在具体项目中不同，宏会把失败项写入日志。

截图中的“生成热”当前按用户要求使用 REFPROP 饱和状态比焓写入：气态材料使用饱和气体焓，液态材料使用饱和液体焓。它不是严格化学标准生成焓。

R454C 已在当前 REFPROP 安装目录中检测到 `MIXTURES\R454C.MIX`，工具会优先按 REFPROP 混合工质文件加载。若其他混合工质没有 `.MIX` 文件，需要在配置中提供组分。
