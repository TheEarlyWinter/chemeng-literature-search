# 记录级证据、元数据核验与去重

## 候选记录格式

把每条论文候选标准化。未知字段保持空值，不能根据常识或模型记忆补全：

```json
{
  "title": "",
  "authors": [""],
  "year": 2025,
  "venue": "",
  "doi": "10.xxxx/xxxxx",
  "ids": {"openalex": "", "semantic_scholar": "", "arxiv": "", "pmid": "", "handle": "", "cnki": "", "wanfang": ""},
  "urls": ["https://..."],
  "abstract": "",
  "document_type": "journal-article|review|preprint|conference|thesis|other",
  "relevance_basis": "title|abstract|fulltext",
  "verification_status": "confirmed|provisional|conflict",
  "evidence": [
    {
      "provider": "openalex",
      "source_type": "scholarly_index|bibliographic_database|registry|publisher|domain_database|repository|citation_map|search_engine|other",
      "role": "discovery|verification|content|attribute",
      "supports": ["identity", "relevance", "claim", "citation_count", "oa_status", "ranking"],
      "locator": "https://具体记录页或API端点；无结果页的查询用 urn:search:provider:q-唯一编号",
      "query_or_relation": "完整实际检索式，或 cited_by/reference/similar",
      "accessed_at": "YYYY-MM-DD"
    }
  ],
  "claims": [
    {
      "text": "报告中准备使用的具体方法、结果或数值",
      "basis": "abstract|fulltext",
      "locator": "https://支持该结论的摘要或全文页面",
      "evidence_excerpt": "支持该结论的原始摘要/全文逐字摘录"
    }
  ]
}
```

`evidence` 保存的是记录级证据，不只是报告顶部的一串数据库名称。若某篇论文无法指出它是从哪里发现、在哪里核验的，它就没有通过真实性门槛。查询URN只能承担发现角色。claim必须引用`role=content`的HTTP证据，且`basis=abstract|fulltext`与证据`supports`中的同名能力精确对应；仅支持`relevance`的发现线索不能承载事实性claim。

## 硬筛契约

当任务同时包含文献类型、直接主题实证、期刊分区等硬条件时，账本使用顶层对象：

```json
{
  "screening_contract": {
    "allowed_document_classes": ["original-research", "review"],
    "document_class_trusted_hosts": ["doi.org", "pubs.example.org"],
    "required_criteria": [
      {
        "id": "direct_storage",
        "evidence_policy": "direct_result_not_candidate",
        "applies_to_classes": ["original-research"],
        "trusted_hosts": ["doi.org", "pubs.example.org"]
      },
      {
        "id": "journal_attribute",
        "evidence_policy": "exact_attribute",
        "trusted_hosts": ["ranking.example.edu"],
        "expected_attributes": {
          "ranking_system": "CAS 2025 upgraded major category",
          "ranking_year": 2025,
          "zone": "1",
          "top": true
        }
      }
    ]
  },
  "records": [
    {
      "document_class": "original-research",
      "eligibility_checks": [
        {
          "criterion": "document_class",
          "passed": true,
          "source_label": "Article",
          "locator": "https://出版社原始页面",
          "evidence_excerpt": "Document type: Article"
        },
        {
          "criterion": "direct_storage",
          "passed": true,
          "locator": "https://原始摘要或全文",
          "evidence_excerpt": "...energy-storage density of 123 J/g...",
          "measured_value": 123,
          "unit": "J/g",
          "measurement_context": "energy density measured for the target material"
        },
        {
          "criterion": "journal_attribute",
          "passed": true,
          "locator": "https://指定年份属性表",
          "evidence_excerpt": "2025大类1区，Top=是",
          "observed_attributes": {
            "ranking_system": "CAS 2025 upgraded major category",
            "ranking_year": 2025,
            "zone": "1",
            "top": true
          }
        }
      ]
    }
  ]
}
```

把同一`screening_contract`对象另存为独立`screening-contract.json`，并在审计命令显式传入。外部契约、账本内嵌副本和DOI侧车契约指纹必须一致。未知策略、非法适用类别、重复criterion、未列入契约的证据主机都硬失败。

`journal-article`、期刊名或DOI注册类型不能替代出版社原始`Article/Review/Perspective`标签。类型证据必须标明`supports: ["document_type"]`。要求直接储热/释热实证时，光异构化、吸收光谱、热半衰期和“有应用潜力”只能作为支撑/背景；原创研究必须有数值、单位、测量语境和储能密度/储热容量/释热/潜热/焓等直接结果，数值与单位须在原文摘录中出现。

## 两道门：存在性与相关性

### 门 A：论文存在且身份一致

正式清单中的每篇必须有稳定标识符，并满足以下一项：

1. DOI/DataCite/Crossref注册记录、出版社页面、学科数据库或可信机构仓储中，题名与标识符对应；
2. 若直接核验源不可访问，两个不同结构化学术索引中的题名、年份、作者/作者组和稳定ID一致。

受控替代标识包括 PMID、PMCID、arXiv ID、Handle、OpenAlex/Semantic Scholar记录ID、CNKI/万方/维普规范记录ID，以及能够承担身份核验的可信机构仓储永久记录URL。替代ID必须位于相应provider规定的记录路径中，并与完整路径段/Handle/DOI一致；查询参数与fragment一律不参与身份匹配。不能用子串碰撞，也不能把任意网页URL、搜索结果URL或自定义`ids`键当稳定ID。

DOI只通过正则格式检查不算核验。网页搜索片段、博客、AI摘要、社交帖子、引用管理器的孤立条目也不能单独确认存在性。

### 门 B：确实回答用户主题

相关性依据分三级：

- `fulltext`：可核验方法、实验条件、局限和复杂结论；
- `abstract`：可核验研究对象、方法、主要结果及摘要明确给出的数值；
- `title`：只能做保守主题判断，必须标注“仅按题名判断”。

题名不能支持实验条件、性能数值、机理、因果方向或“首次/最佳”等主张。搜索引擎生成摘要与 Semantic Scholar TLDR 等算法摘要不能伪装成原文摘要；使用时要注明其真实来源，关键结论仍回到原始摘要或全文。

`claims[]` 中每条方法、性能、机理或数值主张必须保存原文逐字摘录 `evidence_excerpt`。若原文只说“may enable”“offers opportunities”“有望应用”等候选性措辞，报告也只能写潜力或机会，不能扩成已测储能量、释热性能或已证实机理。

## 自动证据审计

系统模式、严格硬筛、种子扩展或需要保存中间结果时，将记录写入 JSON 后按顺序运行：

```powershell
# Windows
py -3 scripts\verify_doi_records.py records.json --output doi-check.json --strict
py -3 scripts\audit_records.py records.json --doi-verification doi-check.json --output audit.json --strict

# macOS / Linux
python3 scripts/verify_doi_records.py records.json --output doi-check.json --strict
python3 scripts/audit_records.py records.json --doi-verification doi-check.json --output audit.json --strict
```

DOI脚本先查Crossref、再查DataCite，二者均无记录时尝试DOI内容协商元数据，并比较注册题名与候选题名。空DOI状态为`not_applicable`，交给替代ID身份门；非空但格式错误为`invalid_doi`并硬失败；`conflict`或`not_found`不得进入确认清单；`unavailable`表示服务超时、限速或异常，应保持provisional并换来源核验。

严格审计会逐索引消费`doi-check.json`：同索引、同DOI、同完整记录指纹且状态为`verified`才通过。指纹绑定题名、作者、年份、期刊、ID、证据、claims、相关性依据、文献类别、资格检查和声明状态，防止核验后换记录或证据。侧车必须带受控registry、含当前DOI的registry URL和注册元数据；核验器同时对照规范化精确题名、作者组、年份、期刊和容器级文献类型，相似度只用于诊断。服务`unavailable`时严格核验返回非零。没有侧车结果、空壳verified结果或注册元数据不一致时，带DOI记录不能confirmed。

有硬条件时运行：

```powershell
py -3 scripts\verify_doi_records.py records.json --output doi-check.json --strict
py -3 scripts\audit_records.py records.json --doi-verification doi-check.json --require-screening-contract --screening-contract screening-contract.json --output audit.json --strict
```

审计器会检查外部冻结契约、文献原始类别、逐条件资格证据、来源主机、结构化测量值与候选性措辞。任何脚本返回非零时，不能在报告中手工覆盖状态。

## 元数据核验优先级

1. 标识注册记录与出版社落地页：题名、作者、期刊、出版日期、版本；
2. 学科数据库与可信机构仓储：身份、版本、摘要或全文；
3. 结构化学术索引：发现、引用关系与身份交叉核验；
4. 搜索结果摘要和非学术第三方页面：仅作线索。

“官方”并不保证字段永远完整，“第三方”也不等于不可信。遇到冲突时比较字段来源与记录更新时间，保留冲突说明，不把两个来源拼成一条从未真实存在过的题录。

## 关键字段的防补写规则

- **题名、作者、年份、期刊、DOI**：只能抄录当前任务实际读取的记录字段；来源之间不一致时标冲突。
- **作者**：只见到“et al.”时就写作者组或首作者等，不能凭记忆展开完整名单。
- **DOI**：必须同时核对 DOI 和题名；不能从相似题名的另一篇文章借 DOI。
- **年份**：区分 online first、accepted、issue/volume year；跨年时并列写明。
- **文献类型**：Article、Review、Preprint、Conference 等以来源记录为准；不确定则写“未核实”。
- **数值与性能**：只有原始摘要或全文明确出现时才能写，保存 claim locator 与逐字 `evidence_excerpt`；候选性措辞不得升级为实证。
- **引用数**：注明平台和访问日期，不跨平台取最大值。
- **期刊分区/Top/收录**：单独使用带明确年份的属性源核验；JCR Q1不能替代中科院一区。
- **撤稿与更正**：条件允许时检查 Crossmark、PubMed、出版社或 Retraction Watch/Lens 的更新标记。

## 去重规则

1. DOI 统一为小写，去掉 `https://doi.org/`、`doi:`、尾随标点后完全匹配。
2. 匹配同类稳定 ID：PMID、PMCID、arXiv ID、OpenAlex ID、S2 ID。
3. 题名规范化：Unicode NFKC、大小写折叠、去标点与多余空白。
4. 只有规范化题名相同、双方年份均存在且相差不超过1年、并且不存在 DOI 冲突时，才自动合并。
5. 两条有效 DOI 不同，即使题名相同也不自动合并，标记 `doi_conflict`。
6. 题名相同但年份缺失，或仅近似题名匹配，不静默合并，进入 `possible_duplicates`。
7. 预印本与正式发表版：保留正式版本为主记录，在 `versions` 中记录预印本，不算两篇独立证据。

## 合并原则

- 非空且证据层级更高的字段优先。
- 来源、URL、ID、版本和访问证据取并集。
- 引用数按平台分别保存，不取最大值冒充统一计数。
- 摘要来源要可追溯；去重脚本把各来源摘要保存到 `abstracts[]`，不同摘要不拼接成“新摘要”。
- 字段冲突进入 `conflicts` 或人工复核队列，不静默覆盖。

去重脚本：

```powershell
py -3 scripts\dedupe_records.py input.json --output merged.json
```

## 输出资格

- `confirmed`：通过存在性门和相关性门，可进入正式文献表。
- `provisional`：有发现线索，但身份或相关性证据不足，只能进入“待核验线索”。
- `conflict`：DOI、题名、作者、年份或版本存在实质冲突，必须单列说明。

用户要求 N 篇而确认结果不足 N 篇时，返回实际确认数量。不得用 provisional 或 conflict 记录凑数。
