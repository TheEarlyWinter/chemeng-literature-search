# chemeng-literature-search

面向 **HanaAgent / Agent Skills** 的化学工程学术文献检索、筛选、核验与种子论文扩展 Skill。

它默认熟悉染料、偶氮体系与相变材料，也覆盖催化、反应工程、分离、膜、吸附、精馏、传递过程、过程强化、能源化工、环境化工和生物化工等方向。

> 核心原则：模型记忆只能帮助生成检索词，不能生成最终引文。正式文献必须来自本轮真实检索，并通过记录级证据与身份核验。

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB)
![Tests](https://img.shields.io/badge/tests-61%20passing-brightgreen)
![Version](https://img.shields.io/badge/version-0.3.1-6f42c1)

## 为什么做这个 Skill

普通的“帮我找几篇论文”很容易出现几类问题：

- 根据模型记忆补出看似合理、实际不存在的题名；
- 把真实 DOI 拼给错误题名、作者或期刊；
- 把搜索摘要中的“可能用于储能”扩写成“已测得储能性能”；
- 把 Crossref 的 `journal-article` 容器类型误当成出版社的原创 Article；
- 用无法追溯的估算数字描述命中、排除和去重数量；
- 仅因学位论文没有 DOI 就误判为不真实。

`chemeng-literature-search` 将检索拆成发现、身份核验、内容证据、去重和资格筛选几层，并为严格任务提供可执行的机器审计脚本。

## 主要能力

### 三种检索模式

| 模式 | 适用场景 | 默认行为 |
|---|---|---|
| 快速检索 | 找几篇入门或近期论文 | 使用最轻的足够来源，逐篇核验，不伪装成系统综述 |
| 系统检索 | 开题、综述、尽量全面的检索 | 多来源、多轮查询，保存检索式、结果集、筛选与去重记录 |
| 种子扩展 | 从一篇 DOI/题名寻找上下游研究 | 分开追踪参考文献、前向被引和相似主题，引用关系不冒充支持关系 |

### 真实性与证据门

- DOI 经 Crossref、DataCite或 DOI CSL-JSON内容协商实时核验；
- 同时核对规范化题名、作者组、出版年份、期刊和容器级文献类型；
- DOI侧车绑定完整记录指纹、输入数量、索引和硬筛契约指纹；
- 空 DOI 记为 `not_applicable`，交给受控替代 ID 路径；
- 非空非法 DOI 记为 `invalid_doi`，严格模式硬失败；
- 支持 PMID、PMCID、arXiv、Handle、OpenAlex、Semantic Scholar、Lens、CNKI、万方、维普及可信机构仓储永久URL；
- 替代 ID 必须匹配provider规定的记录路径，query与fragment不参与身份匹配；
- Claim必须回指当前记录的可信摘要或全文证据，并保留原文摘录。

### 严格硬筛

当任务同时要求文献类别、直接实证、期刊分区等条件时：

- 使用独立冻结的 `screening-contract.json`；
- 外部契约、账本内嵌副本和 DOI侧车契约指纹必须一致；
- Perspective、Viewpoint、Editorial不会混入原创Article；
- 直接储热/释热实证必须有结构化数值、单位、测量语境和原文摘录；
- `potential`、`promising`、`may`、`有望`等候选性措辞不能单独通关；
- 期刊属性按体系、年份、分区和 Top等字段逐项匹配，并绑定当前期刊。

### 冲突安全去重

- DOI优先；
- 受控替代 ID次之；
- 题名与年份仅用于保守合并或疑似重复提示；
- 同题名但 DOI冲突时不自动合并；
- 缺失年份的同名记录不静默合并；
- 保留多来源摘要、引用指标和来源轨迹。

## 安装

### 方式一：安装 Release 中的 `.skill`

从仓库的 [Releases](https://github.com/TheEarlyWinter/chemeng-literature-search/releases) 下载最新的：

```text
chemeng-literature-search.skill
```

然后在 HanaAgent 中导入该文件。

### 方式二：从源码使用

```bash
git clone https://github.com/TheEarlyWinter/chemeng-literature-search.git
```

将整个 `chemeng-literature-search` 目录放入兼容 Agent Skills规范的技能目录中。

脚本仅依赖 Python 3.10+ 标准库；在线 DOI核验需要网络访问。

## 快速开始

安装后可直接向 HanaAgent提问：

```text
帮我找近三年低共熔相变材料用于热能储存的中英文论文。
```

```text
以 DOI 10.1039/D5GC03447G 为种子，分别找前置研究、后续引用和相似主题论文。
```

```text
严格找2024年至今偶氮MOST论文，只要原创Article和Review，原创论文必须报告直接储能或释热结果。
```

Skill会根据任务自动选择快速检索、系统检索或种子扩展模式。

## 严格审计工作流

### Windows PowerShell

```powershell
py -3 scripts\dedupe_records.py input.json --output merged.json
py -3 scripts\verify_doi_records.py merged.json --output doi-check.json --strict
py -3 scripts\audit_records.py merged.json `
  --doi-verification doi-check.json `
  --output audit.json `
  --strict
```

### macOS / Linux

```bash
python3 scripts/dedupe_records.py input.json --output merged.json
python3 scripts/verify_doi_records.py merged.json --output doi-check.json --strict
python3 scripts/audit_records.py merged.json \
  --doi-verification doi-check.json \
  --output audit.json \
  --strict
```

严格硬筛任务增加外部契约：

```powershell
py -3 scripts\verify_doi_records.py records.json --output doi-check.json --strict
py -3 scripts\audit_records.py records.json `
  --doi-verification doi-check.json `
  --require-screening-contract `
  --screening-contract screening-contract.json `
  --output audit.json `
  --strict
```

> 在混合候选集中，只要有记录被排除或降级，`audit_records.py --strict` 返回退出码 `2` 是预期行为。最终正式表只能取 `computed_status=confirmed` 的子集。

## 最小记录示例

```json
{
  "title": "A verified chemical engineering paper",
  "authors": ["Researcher, Alice"],
  "year": 2025,
  "venue": "Journal of Verifiable Results",
  "doi": "10.1000/example",
  "document_type": "journal-article",
  "relevance_basis": "abstract",
  "verification_status": "confirmed",
  "evidence": [
    {
      "provider": "openalex",
      "source_type": "scholarly_index",
      "role": "discovery",
      "supports": ["identity", "relevance"],
      "locator": "https://openalex.org/W123456789",
      "accessed_at": "2026-08-09"
    },
    {
      "provider": "publisher",
      "source_type": "publisher",
      "role": "content",
      "supports": ["claim", "abstract"],
      "locator": "https://doi.org/10.1000/example",
      "accessed_at": "2026-08-09"
    }
  ],
  "claims": [
    {
      "text": "The measured latent heat was 200 J/g.",
      "basis": "abstract",
      "locator": "https://doi.org/10.1000/example",
      "evidence_excerpt": "The measured latent heat was 200 J/g."
    }
  ]
}
```

完整字段和硬筛契约示例见：

- [`references/verification-and-dedup.md`](references/verification-and-dedup.md)
- [`references/output-templates.md`](references/output-templates.md)
- [`references/source-strategy.md`](references/source-strategy.md)
- [`references/chemeng-routing.md`](references/chemeng-routing.md)

## 测试

```bash
python -m unittest discover -s tests -q
python -m py_compile \
  scripts/audit_records.py \
  scripts/dedupe_records.py \
  scripts/verify_doi_records.py
```

当前版本：

```text
61/61 tests passed
```

真实场景回归：

- 无 DOI / CNKI学位论文：4/4 `confirmed`；
- 偶氮 MOST硬筛候选：5/5身份核验通过，最终3篇 `confirmed`、2篇按类型或直接实证条件降级；
- query参数伪装 PMID/DOI 的三类对抗 PoC均被拒绝。

## 项目结构

```text
chemeng-literature-search/
├── SKILL.md
├── README.md
├── LICENSE
├── evals/
│   └── evals.json
├── references/
│   ├── chemeng-routing.md
│   ├── output-templates.md
│   ├── source-strategy.md
│   └── verification-and-dedup.md
├── scripts/
│   ├── audit_records.py
│   ├── dedupe_records.py
│   └── verify_doi_records.py
└── tests/
    ├── test_audit_records.py
    ├── test_dedupe_records.py
    └── test_verify_doi_records.py
```

## 数据库与访问边界

- WoS、Scopus、SciFinder、Reaxys、CNKI和万方完整站内检索依赖用户的合法权限；
- 不绕过验证码、付费墙或反爬机制；
- 不使用Sci-Hub等非法全文来源；
- 未实际访问的数据库不会写成“已检索”；
- 搜索引擎结果页不能冒充数据库站内检索。

## 安全边界

该Skill显著提高题名—DOI拼接、元数据错配、假来源、候选性措辞升级和硬筛错纳的发现概率，但不承诺“零幻觉”或密码学防篡改。

当前账本、摘录和侧车仍是本地JSON。若执行者拥有任意文件修改权限，且平台不提供HTTP响应哈希、工具调用签名或不可编辑日志，本地脚本无法证明摘录和侧车从未被联合伪造。

更强的不可抵赖审计需要平台层支持：

- 原始HTTP响应或响应哈希；
- 工具调用日志签名；
- 同进程强制核验；
- 不可编辑的证据快照。

## 许可证

[MIT License](LICENSE)
