# 简历

[English](README.md) | **简体中文**

`master_resume.json` 保存所有定制简历所依据的事实，`jobs/` 里每个职位一个文件夹。简历如何生成和核查，见
**[docs/resumes.md](../docs/resumes.md)**（英文）。

`index.csv` 由 `radar export` 根据这些文件夹和职位 Issue 重新生成，请不要手动编辑。

## 填写 `master_resume.json`

请用**英文**填写你的简历（CV）。这个文件一开始是空的；在填好 `identity.name`、`identity.email`、
`summary.experience`，以及至少一条工作经历或教育经历之前，不会生成任何简历（`radar doctor` 会列出还缺什么）。
只写真实的内容：定制时只会重新排序和挑选这些事实，可选的 AI 步骤可能会改写措辞，但永远不会添加新内容。

| 字段 | 填什么 |
|---|---|
| `version` | 任意标签；每次修改文件时改一下，这样每份简历都会记录它来自哪个版本。 |
| `identity` | 姓名、头衔（例如 "Registered Nurse \| BLS, ACLS"）、所在地、电话（如果申请国外职位，加上国家区号）、邮箱，以及可选的 `linkedin`、`github`、`website`。空着的字段不会出现在简历上。 |
| `summary.experience` | 一句话概括你的经验，例如 "Registered Nurse with three years of acute-care experience."。 |
| `summary.credentials` | 一句话说明你的执照或证书，也可以留空。 |
| `summary.capabilities` | 带 `tags` 的短语；和职位最相关的几条会接在摘要后面。 |
| `technical_skills` | 技能行：`category`（可选）、`text`、`tags` 和 `priority`（没有标签匹配职位时，数字小的排在前面）。这一部分在简历上的标题是 "Skills"。 |
| `experience` | 工作经历：`role`、可选的 `company`、`dates`、可选的 `max_bullets`（默认 4），以及 `bullets`，每条都有 `text` 和 `tags`。 |
| `education` | `program`、`school`、`dates`，以及可选的 `bullets`。 |
| `certifications` | `text`、`tags`、`priority`。前四个会逐条列出，其余的合并成一行。 |

**标签（tags）** 决定为某个职位挑选哪些内容。使用 `config/search_config.yaml` 里 `matching.skills` 中的技能名称
（标签和职位要求的技能同名时，权重最高），再加上职位广告里可能出现的其他词。

只写你确实做过的事。培训、课程里的实操可以写进 `education` 的 `bullets`，不要写成工作经历。

一个简短的示例（内容用英文填写）：

```json
{
  "version": "2026-01",
  "identity": {"name": "Sam Rivera", "headline": "Registered Nurse | BLS, ACLS",
               "location": "Toronto, ON", "phone": "555-0100", "email": "sam@example.com"},
  "summary": {
    "experience": "Registered Nurse with three years of acute-care experience.",
    "credentials": "BLS and ACLS certified.",
    "capabilities": [
      {"text": "patient assessment", "tags": ["patient assessment"]},
      {"text": "medication administration", "tags": ["medication administration"]}
    ]
  },
  "technical_skills": [
    {"category": "Clinical", "text": "Patient assessment, wound care, IV therapy",
     "tags": ["patient assessment", "wound care"], "priority": 1}
  ],
  "experience": [
    {"role": "Registered Nurse", "company": "Example General Hospital", "dates": "2023 - Present",
     "bullets": [
       {"text": "Assessed and cared for up to six patients per shift on a medical-surgical unit.",
        "tags": ["patient assessment"]}
     ]}
  ],
  "education": [
    {"program": "Bachelor of Science in Nursing", "school": "Example University", "dates": "2019 - 2023"}
  ],
  "certifications": [
    {"text": "Basic Life Support (BLS)", "tags": ["bls"], "priority": 1}
  ]
}
```

在 GitHub 网页上编辑时，引号、逗号和方括号必须成对，并且严格按照示例的格式；改坏了 GitHub 会发邮件说 **CI failed**，
打开失败的运行就能看到出错的文件。
