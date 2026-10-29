# 按你的求职需求配置

[English](configure.md) | **简体中文**

三个文件描述你和你想要的职位。它们一开始都是空的；填好之后运行 `radar doctor`，直到它报告没有问题为止。

| 文件 | 内容 |
|---|---|
| `config/search_config.yaml` | 在哪里搜、搜什么、怎么评分，以及你所在行业的词汇 |
| `config/resume_profile.json` | 你的工作年限、技能和证书 |
| `resumes/master_resume.json` | 生成定制简历所依据的事实（[填写说明](../resumes/README.zh-CN.md)） |

然后让 workflow 和你的时区一致：把 `.github/workflows/daily-jobs.yml` 和 `linkedin-email-alerts.yml` 里的
`timezone:` 行，设成和 `search_config.yaml` 里 `timezone` 相同的值。

## 短语如何匹配

职位广告按**英文**读取。职位名称、技能、关键词和地点的 `match` 条目都是**短语**。短语按整词匹配，忽略大小写和多余空格：
`nurse` 能匹配 "Registered Nurse"，但不能匹配 "Nursery"；`c++` 能匹配 "C++ developer"。以 `re:` 开头的短语则是一个
Python 正则表达式；请用单引号括起来，这样 YAML 不会改动反斜杠：`'re:accounts?'`、`'re:tcp/?ip'`、`'re:escalat'`
（匹配 escalate、escalation、escalating）。

## `search_config.yaml`

### `timezone`

一个 [IANA 时区名称](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones)，例如 `Europe/London`、
`Asia/Kolkata`、`America/Chicago`、`Africa/Lagos` 或 `Australia/Sydney`。报告日期和早晚扫描时段都按它计算。

### `search`

| 键 | 含义 |
|---|---|
| `sites` | JobSpy 搜索的招聘网站：`indeed`，以及[你的国家](#你的国家)可用的其他网站。 |
| `country_indeed` | Indeed 和 Glassdoor 搜索的国家：`UK`、`USA`、`Canada`、`India`、`Australia`…… |
| `queries` | 输入招聘网站搜索框的内容，宽泛一些也没关系。留空则搜索 `titles`。 |
| `titles` | 你想要的职位名称。职位名称中（按整词）包含其中之一的，职位名称一项得满分。变体可以用正则：`'re:accounts? assistant'`。 |
| `exclude_title_terms` | 你永远不想要的职位名称：和你的职位共用某个词、但并不是你要的。它们会在搜索时被丢弃，来自 LinkedIn 的也会被排除。 |
| `locations` | 在哪里搜索，以及每个地点值多少分（见下文）。 |
| `results_wanted_per_query`、`hours_old`、`fetch_description`、`pause_seconds_between_queries` | 每次搜索抓取多少内容。默认值即可。 |

每个 `locations` 条目：

| 键 | 含义 |
|---|---|
| `name` | 显示在报告里（"Toronto location"）。 |
| `query` | 填进招聘网站地点框的内容。 |
| `remote_only` | `true` 表示只向招聘网站要远程职位。这样的条目永远不会给非远程职位加地点分，即使它的 `match` 短语匹配上了。 |
| `distance` | 以 `query` 为中心的搜索半径，单位是英里。默认用招聘网站自己的半径（Indeed 是 50 英里，远远超出大多数城市的范围）。 |
| `score` | 职位地点匹配时得到的地点分（满分 5）。默认 5。 |
| `match` | 表示职位位于这个地点的短语。默认是 `name`。 |
| `linkedin` | `radar linkedin-search` 使用的地点文字（[linkedin.md](linkedin.md)，英文）。可选。 |

一个职位取它匹配到的所有条目中最高的 `score`；远程职位得 `ranking.remote_score`；一个都没匹配上则得 1 分。
对非远程职位，只有没设 `remote_only` 的条目才算。

### `ranking`

| 键 | 默认值 | 含义 |
|---|---|---|
| `good_match_threshold` | 65 | 高匹配：一个指派给你的 Issue 和一份定制简历。仓库变量 `GOOD_MATCH_THRESHOLD` 会覆盖它。 |
| `good_requires_matched_skill` | true | 高匹配还要求职位广告里出现至少一项你的技能；否则只算可能匹配（[scoring.md](scoring.md#verdicts)，英文）。 |
| `possible_match_threshold` | 55 | 可能匹配：有 Issue，但没有简历。 |
| `max_good_matches` | 10 | 每次扫描最多为多少个高匹配职位创建 Issue 和简历（0 表示不限）。其余的列在报告里，下次扫描再出现。 |
| `max_possible_matches` | 5 | 每次扫描最多为多少个可能匹配职位创建 Issue。 |
| `fresh_hours` | 24 | 发布时间在这么多小时以内的职位，发布时间一项得满分。 |
| `remote_score` | 5 | 远程职位的地点分。 |
| `hard_reject_unrelated_titles` | true | 排除既不在 `titles` 里、也和 `matching` 无关的职位名称。 |
| `hard_reject_title_terms` | | 排除包含这些词的职位名称，例如 `senior`、`manager`。缩写也要加上（`sr`、`snr`）：职位名称里常用。 |
| `hard_reject_min_years` | 5 | 排除要求这么多年及以上经验的职位。 |

### `matching`

你所在行业的词汇。评分时会在职位广告里查找它们，并和你的档案比较。

| 键 | 含义 |
|---|---|
| `skills` | 每项技能，以及表示职位要求这项技能的短语。没有短语的技能（`wound care: []`）按它自己的名称查找；普通列表里的每个名称（`- wound care`）也一样。 |
| `soft_skills` | 几乎每个职位广告都会提到的技能名称。它们不算核心要求：缺少时列在可选差距里。 |
| `certifications` | 每个证书或执照，以及表示职位要求它的短语。 |
| `related_title_keywords` | 不在你的 `titles` 里时，让一个职位名称算作相关的词。 |
| `context_title_keywords`、`context_words` | 只有和某个上下文词同时出现时才算相关的词。 |

**怎么选技能。** 读十个你会申请的职位广告，列出它们要求的工具、技术和知识，包括你还没有的。你没有的技能也应该放进
`matching.skills`：这样职位的这项要求才会显示为缺失。然后把你真正具备的，用同样的名称写进 `resume_profile.json`。

## 你的国家

只要职位广告是英文的，Job Radar 在任何国家都能用。Indeed 覆盖的国家最多，并且能从 GitHub 的服务器访问。把
`country_indeed` 设成以下之一：Argentina, Australia, Austria, Bahrain, Belgium, Brazil, Canada, Chile, China,
Colombia, Costa Rica, Czech Republic, Denmark, Ecuador, Egypt, Finland, France, Germany, Greece, Hong Kong, Hungary,
India, Indonesia, Ireland, Israel, Italy, Japan, Kuwait, Luxembourg, Malaysia, Mexico, Morocco, Netherlands,
New Zealand, Nigeria, Norway, Oman, Pakistan, Panama, Peru, Philippines, Poland, Portugal, Qatar, Romania,
Saudi Arabia, Singapore, South Africa, South Korea, Spain, Sweden, Switzerland, Taiwan, Thailand, Türkiye, Ukraine,
United Arab Emirates, UK, USA, Uruguay, Venezuela 或 Vietnam（请照原样写英文名）。你还可以往 `sites` 里加：

| 网站 | 覆盖地区 |
|---|---|
| `glassdoor` | 上面的许多国家（如果你的国家不在其中，`radar doctor` 会提醒） |
| `google` | Google Jobs，凡是它提供服务的地方 |
| `naukri` | 印度 |
| `bayt` | 海湾地区和中东 |
| `bdjobs` | 孟加拉国 |

`queries`、`titles`、技能和证书都用英文写。如果大多数职位广告是其他语言，只有英文的那些能匹配得好：工作年限（"3+ years"）
和 "nice to have" 部分只能识别英文，简历的标题也是英文。

招聘网站会改变它们允许的访问方式；如果某个网站一直失败，扫描报告的 "Collector warnings" 会写明，其他网站照常运行。
GitHub 上永远不会搜索 LinkedIn：请用它的提醒邮件或 `radar linkedin-search`（[linkedin.md](linkedin.md)，英文）。

## `resume_profile.json`

| 键 | 含义 |
|---|---|
| `experience_years` | 你在本行业的工作年限（整数），和职位要求的年限比较。 |
| `skills` | 你真正具备的技能，名称和 `matching.skills` 里的一致。 |
| `certifications` | 你持有的证书，名称和 `matching.certifications` 里的一致。 |
| `profile_name` | 给自己的一个标签；不参与评分。 |

只在确实具备时才添加技能。为了提高分数而添加，只会生成你无法为之负责的简历。

## 一个示例

`config/search_config.yaml` 自带一个伦敦会计的注释示例。下面是另一个：多伦多的一名注册护士，在本地和全加拿大远程找工作：

```yaml
timezone: America/Toronto

search:
  sites: [indeed]
  country_indeed: Canada
  queries: [Registered Nurse, RN]
  titles: [Registered Nurse, Staff Nurse, Charge Nurse]
  exclude_title_terms: [nursing assistant, veterinary]
  locations:
    - {name: Toronto, query: "Toronto, ON", score: 5, match: [toronto, mississauga], linkedin: "Toronto, Ontario, Canada"}
    - {name: Ontario, query: Ontario, score: 4, match: [ontario, 're:,\s*on\b']}
    - {name: Remote, query: Canada, remote_only: true, score: 3, match: [canada], linkedin: Canada}

ranking:
  hard_reject_title_terms: [manager, director]

matching:
  skills:
    patient assessment: [patient assessment, assess patients]
    medication administration: [medication administration, administer medication]
    epic: [epic, epic emr]
    wound care: []
    communication: []
  soft_skills: [communication]
  certifications:
    BLS: [bls, basic life support]
    ACLS: [acls]
  related_title_keywords: [nurse, nursing, rn]
  context_title_keywords: [care]
  context_words: [patient, clinical]
```

```json
{
  "profile_name": "Registered Nurse",
  "experience_years": 2,
  "skills": ["patient assessment", "medication administration", "wound care", "communication"],
  "certifications": ["BLS"]
}
```

按这个配置，一个当天发布、位于多伦多的 "Registered Nurse - Medical/Surgical" 职位，如果要求两年经验、patient assessment、
medication administration、wound care 和 BLS，得 100 分。如果还要求 Epic 和 ACLS，得 86 分，并把这两项列为缺失。
（没有发布日期时，两者都少 3 分。）
