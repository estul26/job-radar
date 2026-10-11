# Job Radar（职位雷达）

[English](README.md) | **简体中文**

每天两次为**任何行业、任何国家**搜索职位。它根据你的技能和经验为每个职位评分，并把有希望的职位作为
GitHub Issue 跟踪；每个高匹配职位都会获得一份经过事实核查的定制简历（CV）。你只需在三个文件里描述你的行业、
所在地和你自己，代码中没有任何只针对某一类职位或某个国家的内容。职位发布和简历均为英文。

```text
招聘网站（每天两次） ────────────┐
LinkedIn 职位提醒邮件 ───────────┤
你的 Chrome 中的 LinkedIn（Mac） ─┼─► 评分 0–100 ─► 职位 Issue ─► Job Search 看板
LinkedIn Job Review 表单 ────────┘                   │
                                                    └─► 为高匹配职位生成定制简历
```

- **发现职位。** GitHub Actions 按你的时区每天两次搜索招聘网站：覆盖约 70 个国家的 Indeed，以及 Glassdoor、
  Google Jobs 和地区性网站，如 Naukri（印度）、Bayt（中东）和 BDJobs（孟加拉国）。
  LinkedIn 职位来自 LinkedIn 自己的提醒邮件、`radar linkedin-search`（在你的 Mac 上、在你已登录的 Chrome 中手动运行），
  或 **LinkedIn Job Review** Issue 表单。
- **评分。** 确定性且可解释：根据你配置的职位名称、技能和地点，比对职位名称、经验、技能、证书、发布时间和地点。
  详见 [docs/scoring.md](docs/scoring.md)。
- **跟踪。** 每个高匹配和可能匹配的职位都是一个 Issue，高匹配的会指派给你。Issue 的 `status:*` 标签就是申请状态：
  修改标签或在看板上拖动卡片即可。每次扫描后，`data/applications.csv` 会从这些 Issue 导出。
- **简历。** 高匹配职位会获得一份基于 `resumes/master_resume.json` 生成的简历。AI 可以润色措辞，
  但只有通过事实核查的措辞才会被采用。详见 [docs/resumes.md](docs/resumes.md)。

它不会替你投递，也不会给任何人发消息。所有流程都在 GitHub Actions 上运行，因此任何电脑（Windows、Linux 或 Mac）都能使用；
只有可选的 Chrome 搜索和备用扫描触发器需要 Mac。

## 开始使用

1. 点击 **Use this template → Create a new repository**，并设为 **私有（Private）**。你的副本会保存你的简历和求职记录。
   不要 Fork：公开仓库的 Fork 必须保持公开。
2. 填写你的配置（[docs/configure.md](docs/configure.md)）：
   - `config/search_config.yaml`：时区、国家、招聘网站、职位名称、地点，以及你所在行业的技能（英文）
   - `config/resume_profile.json`：你的工作年限、技能和证书
   - `resumes/master_resume.json`：生成简历所依据的事实，用英文填写（[填写说明](resumes/README.md)）
   - `.github/workflows/daily-jobs.yml` 和 `linkedin-email-alerts.yml` 中的 `timezone:` 行
3. 检查配置：

   ```bash
   python -m venv .venv && source .venv/bin/activate   # Windows：.venv\Scripts\activate
   pip install -e ".[dev]"
   radar doctor
   ```

   在 `radar doctor` 报告没有问题之前，定时扫描会带着警告自动跳过。
4. 可选：添加 [docs/setup.md](docs/setup.md) 中的 Secrets，例如用于 AI 简历润色的 OpenAI 密钥、用于 LinkedIn 提醒的邮箱。
5. 打开 **Actions → Daily Job Radar → Run workflow** 运行一次扫描，然后查看 `reports/latest.md`。
6. 可选：[LinkedIn 提醒与 Chrome 搜索](docs/linkedin.md)、[看板同步和 Mac 扫描触发器](docs/setup.md#2-the-job-search-board)。

## 命令

| 命令 | 作用 |
|---|---|
| `radar doctor` | 检查 `config/` 和主简历是否已填写 |
| `radar scan [--fixture FILE]` | 搜索、评分并记录新职位；为高匹配职位生成简历 |
| `radar publish-scan` | 为每个高匹配和可能匹配的职位创建 Issue，并以其招聘网站命名 |
| `radar export` | 从 Issue 重建 `data/applications.csv` 和 `resumes/index.csv` |
| `radar issue N --event E [--label L] [--publish]` | 处理 Issue 的创建、编辑或打标签事件 |
| `radar email-ingest` | 导入 LinkedIn 提醒邮件 |
| `radar linkedin-search [...]` | 在你已登录的 Chrome 中搜索 LinkedIn（Mac，手动运行）并导入职位卡片 |
| `radar linkedin-import FILE` | 导入 `linkedin-search --export` 保存的卡片 |
| `radar scan-slot …`、`radar record-claim …` | `daily-jobs.yml` 的早晚扫描去重 |

离线检查你的评分：按照 `tests/fixtures/sample_jobs.json` 的格式保存几个你想申请的职位，然后对它们运行一次扫描
（会修改 `data/`、`reports/` 和 `resumes/jobs/`，不要提交结果）：

```bash
radar scan --fixture my_jobs.json
pytest && ruff check .
```

## 配置

| 内容 | 位置 |
|---|---|
| 时区、国家、招聘网站、搜索词、地点、职位过滤、阈值 | `config/search_config.yaml` |
| 你所在行业的技能、证书和职位关键词 | `config/search_config.yaml` 中的 `matching` |
| 你真正具备的技能和证书 | `config/resume_profile.json` |
| 每份简历所依据的事实 | `resumes/master_resume.json` |
| 高匹配阈值 | 仓库变量 `GOOD_MATCH_THRESHOLD` |
| 扫描时间 | `.github/workflows/daily-jobs.yml` |

只有在确实有新情况时才修改技能档案和主简历。为了提高分数而添加技能，只会生成你无法为之负责的简历。

## 文档

- [配置](docs/configure.md)：每项设置、你的国家、完整示例
- [安装设置](docs/setup.md)：Secrets、Variables、看板及其同步、Mac 扫描触发器
- [LinkedIn](docs/linkedin.md)：提醒导入、Chrome 搜索、Issue 表单、评分流程
- [简历](docs/resumes.md)：生成、AI 防护措施、审计、隐私
- [评分](docs/scoring.md)：分值、判定结果、硬性排除
- [架构](docs/architecture.md)：流水线、代码结构、状态文件

## 使用之前

- **遵守各招聘网站的条款是你自己的责任。** 招聘网站通过 [JobSpy](https://pypi.org/project/python-jobspy/) 搜索。
  `radar linkedin-search` 会操作你自己的 LinkedIn 账号，而 LinkedIn 的条款禁止这样做；它被刻意设计得规模小、速度慢，
  且只能手动运行，但风险由你自行承担。
- **发送前请通读每一份简历。** AI 措辞会对照你的主简历进行事实核查，但投递的人是你。
- **保持你的副本为私有。** 其中包含你的联系方式和求职记录。

## 局限

- 招聘网站会更改页面结构并限制访问频率；某次搜索失败不会中断整个扫描。
- 评分基于关键词，因此可解释但不理解语义，并且只认识你在 `matching` 中列出的技能。
- 自动搜索覆盖 JobSpy 支持的招聘网站。ZipRecruiter（美国和加拿大）会屏蔽 GitHub 的运行器，LinkedIn 则通过提醒邮件和 Chrome 搜索覆盖。
- 仅支持英文：其他语言的职位发布无法得到准确评分，简历标题为英文。

## 许可证

[MIT](LICENSE)
