# refprop-to-ccm

把 REFPROP 物性数据导出为 STAR-CCM+ 可用的材料参数，并生成一个 Java 宏，把数据写入指定 STAR-CCM+ 项目中已有连续体的已有 gas/liquid 相材料属性。

## 当前版本做什么

1. 从界面或配置文件读取制冷剂、饱和压力或饱和温度、气态温度范围、液态属性输入方式、STAR-CCM+ 项目信息。
2. 调用 REFPROP 计算：
   - 饱和温度和饱和压力
   - 液态饱和物性：比热、标准状态温度、导热率、动力粘度、密度、分子量、标准状态焓、生成热候选值
   - 气态固定压力温度表：温度、密度、等效比热容、等效导热率、等效动力粘度、焓值
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

界面中可以先输入制冷剂名称和饱和压力，然后点击“计算饱和温度”。气态表格的温度起点必须大于饱和温度；底层生成流程也会再次校验。

液态材料属性有两种方式：

- 按饱和状态填常数：只写入饱和液体状态的常数。
- 按温度表填：按独立的液态温度起点、终点和步长生成 `liquid_properties.csv`，并让 STAR 宏尝试把液态比热、密度、导热率、动力粘度绑定到表格。液态温度终点必须小于饱和温度。

注意：如果目标 STAR-CCM+ 液相当前使用“恒密度”模型，STAR 不接受密度温度表；宏会保留饱和状态常密度，并在日志中记录密度表未绑定。比热、导热率、动力粘度是否能绑定，取决于目标材料属性当前支持的表格方法。

气态材料属性的比热来源可以选择 `Cp(T)` 表或焓表。气态和液态温度范围分别设置，互不共用。

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
  temperature_step: 1
  temperature_unit: C
```

## 重要说明

STAR-CCM+ 的 Java API 和材料属性路径会随版本、物理模型、相模型设置变化。当前宏采用反射和保守写法查找已有连续体、已有相和已有材料属性；如果某个材料模型或属性路径在具体项目中不同，宏会把失败项写入日志。

截图中的“生成热”当前按用户要求使用 REFPROP 饱和状态比焓写入：气态材料使用饱和气体焓，液态材料使用饱和液体焓。它不是严格化学标准生成焓。

R454C 已在当前 REFPROP 安装目录中检测到 `MIXTURES\R454C.MIX`，工具会优先按 REFPROP 混合工质文件加载。若其他混合工质没有 `.MIX` 文件，需要在配置中提供组分。
