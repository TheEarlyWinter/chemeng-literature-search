# 化学工程主题路由与检索词扩展

## 通用拆解

把自然语言主题拆成四层，每层选最有区分度的词组合成 2–4 个查询：

| 层 | 问题 | 示例 |
|---|---|---|
| 对象/体系 | 研究什么物质、材料或物流？ | azo chromophore, phase change material, CO2, dye wastewater |
| 过程/现象 | 发生什么？ | photothermal conversion, adsorption, catalytic degradation, solid-liquid transition |
| 方法/结构/设备 | 如何实现？ | microencapsulation, membrane, fixed-bed reactor, ring-opening polymerization |
| 指标/机理 | 优化或解释什么？ | latent heat, selectivity, kinetics, thermal cycling stability |

宽检索可先用前两层；精确检索再加入后两层。不要把所有同义词和排除词塞进一个查询。

## 分支路由

### 染料、颜料与发色体系

先判断语境，不确定时保留多条支路：

- 合成与结构：dye synthesis, chromophore, auxochrome, azo dye, anthraquinone dye, polymethine/cyanine dye
- 光物理与刺激响应：absorption spectrum, fluorescence, photoisomerization, thermochromism, solvatochromism, photochromism
- 材料应用：smart coating, sensor, textile coloration, photothermal material, optical switching
- 环境处理：dye wastewater, adsorption, photocatalytic degradation, advanced oxidation, membrane separation

`dye` 容易召回生物染色、食品色素或纯艺术内容。根据课题加入 chemical engineering、polymer、photothermal、wastewater、adsorption 等锚点。只有可靠来源确认时才扩展具体 CAS 号和化合物别名。

### 相变与储热材料

至少考虑：

- phase change material / PCM
- latent heat thermal energy storage / LHTES
- solid-liquid transition
- shape-stabilized PCM / form-stable PCM
- microencapsulated PCM / MPCM
- thermal conductivity enhancement
- supercooling / phase separation / leakage
- thermal cycling stability / latent heat / phase transition temperature
- photothermal phase change / solar-thermal conversion

不要默认所有“phase transition”都属于储热；聚合物玻璃化、晶型转变、液晶相变和反应相平衡可能是不同问题。

### 反应工程与催化

对象 + 反应 + 催化剂/反应器 + 指标：conversion, selectivity, yield, kinetics, deactivation, stability, mass transfer。区分均相/多相、热催化/光催化/电催化与实验室/放大尺度。

### 分离工程

对象 + 分离过程 + 材料/设备 + 指标：membrane, adsorption, distillation, extraction, crystallization；permeance/flux, selectivity, capacity, regeneration, fouling, energy consumption。

### 过程系统与安全

process simulation, optimization, process control, digital twin, techno-economic analysis, life-cycle assessment, process safety, hazard analysis。涉及“最新”时注意模型和工业案例的时间范围。

### 能源、环境与生物化工

根据交叉主题补充 PubMed/Europe PMC、环境健康或生物过程来源。污染物去除研究需要同时关注实际水样、共存离子、矿化程度、毒性和循环再生，不能只看单次去除率。

## 中英文扩展

中文课题先保留中文检索用于 CNKI/万方/维普，同时生成英文概念簇用于国际来源。术语翻译不要逐字直译；优先以综述、主题词表和高相关论文中真实使用的表达校正。

## 排除词

只排除稳定且明显无关的语境。先观察噪声再加入 NOT 条件，避免过早排除跨学科文献。每个排除词应在报告的检索式中可见。
