# 安装设置

[English](setup.md) | **简体中文**

你的副本必须是**私有**的：workflow 会提交你的简历（含联系方式），Issue 里是你的求职记录。用 **Use this template**
创建它（不要 Fork：公开仓库的 Fork 必须保持公开）。

先填好 `config/` 和 `resumes/master_resume.json`，再运行 `radar doctor`（[configure.zh-CN.md](configure.zh-CN.md)）。
在它报告没有问题之前，定时扫描会带着警告自动跳过。

## 1. Secrets 和 Variables

**Settings → Secrets and variables → Actions**

| Secret | 用途 |
|---|---|
| `OPENAI_API_KEY` | 定制简历的 AI 措辞。没有它，简历照样生成，只是不经过 AI。 |
| `LINKEDIN_IMAP_HOST`、`LINKEDIN_IMAP_USER`、`LINKEDIN_IMAP_PASSWORD` | 导入 LinkedIn 提醒邮件（[linkedin.md](linkedin.md)，英文）。 |
| `PROJECTS_TOKEN` | 只有可选的云端看板同步需要（见下文）。 |
| `TEMPLATE_UPDATE_TOKEN` | 可选：让 **Update from template** 也能更新 workflow 文件（[第 5 节](#5-从模板获取更新)）。 |

| Variable | 默认值 | 作用 |
|---|---|---|
| `GOOD_MATCH_THRESHOLD` | `config/search_config.yaml` 里的 `ranking.good_match_threshold` | 高匹配的分数线：一个指派给你的 Issue 加一份定制简历。 |
| `OPENAI_MODEL` | `gpt-6.1-sol` | 用于简历措辞及其事实核查的模型。 |
| `OPENAI_REASONING_EFFORT` | `low` | 这个模型的推理强度；`default` 表示交给模型自己决定。不支持推理设置的模型会自动去掉这个参数再请求一次。 |
| `AI_RESUME_ENABLED` | `true` | 设为 `false` 则始终生成不经过 AI 的简历。 |
| `LINKEDIN_EMAIL_ENABLED` | 关闭 | 设为 `true` 则每 4 小时导入一次邮件。 |
| `LINKEDIN_IMAP_PORT`、`LINKEDIN_IMAP_FOLDER` | `993`、`INBOX` | 邮箱的细节设置。 |

workflow 会自己创建用到的标签。分数达到 `ranking.possible_match_threshold`（55）及以上的是可能匹配。

## 2. Job Search 看板

一个个人 GitHub Project 会把每个职位 Issue 显示为一张卡片，按 **Application Status** 分组。个人 Project 需要你自己的
`gh` 登录，并带有 `project` 权限，所以设置和同步都在你的 Mac 上运行。

一次性设置：

```bash
gh auth refresh -s project
python3 tools/project_sync.py setup
```

这会创建带有所需字段的 **Job Search** project，并把它关联到仓库。重复运行也是安全的。如果没有自动创建看板视图，
请手动添加一个按 **Application Status** 分组的 **Board** 视图。

### 让看板和标签保持同步

```bash
/bin/zsh tools/mac/install-project-sync-agent.sh
```

之后，一个 launchd 代理会在 Mac 醒着的时候每 2 分钟同步一次：

- 新的职位 Issue 会变成卡片，每次填几张。
- **Issue 的 `status:*` 标签是唯一的准绳。** 同步会记住每张卡片上一次运行后的状态。如果只有卡片动了（你拖动了它），
  标签跟着变；否则卡片跟着标签变。拖动卡片和修改标签都可以，两者不会互相撤销。
- GitHub 会限制短时间内大量的 Project 写入，所以每次运行最多写 8 次。如果仍被限流，会暂停 15 分钟。

launchd 无法读取 `~/Downloads`、`~/Documents` 或 `~/Desktop`，所以安装程序会把 `tools/project_sync.py` 复制到
`~/Library/Application Support/job-radar/`，并从那里运行。**拉取到它的更新后，请重新运行安装程序。**

```bash
python3 tools/project_sync.py sync                       # 立即同步一次
tail -f ~/Library/Logs/job-radar-project-sync.log   # 查看输出
/bin/zsh tools/mac/uninstall-project-sync-agent.sh        # 卸载
```

**云端模式。** `.github/workflows/sync-project-dashboard.yml` 可以在你的 Mac 关机时，在 Actions 里运行同样的同步。
它需要一个带 `project` 权限的 classic token，保存为 `PROJECTS_TOKEN`，并在 workflow 里恢复一个定时计划。
频繁的定时任务会消耗私有仓库的 Actions 分钟数，所以默认使用 Mac 代理。

## 3. 扫描的备用触发器

GitHub 可能延迟或丢弃定时运行，而且延迟好几个小时很常见：在一个测试副本里，每次 10:13 的扫描都在 12:45 到 15:00
之间才开始。如果你在意时间，可以把 `daily-jobs.yml` 里的扫描时间提前（中午之前的定时仍然算早上的扫描），或者安装这个
备用触发器。这个 launchd 代理会在本地时间 07:20 和 16:20，以及 Mac 关机后重新登录时，请 GitHub 运行
`daily-jobs.yml`。如果你修改了 `daily-jobs.yml` 里的时间，请同步修改安装程序顶部的 `MORNING_HOUR`/`EVENING_HOUR`
（以及分钟）。

```bash
/bin/zsh tools/mac/install-radar-trigger.sh
```

每个早上或晚上的时段只扫描一次。一次成功的扫描会记录 `data/radar_<slot>_claim.txt`，之后同一时段的触发都会跳过：

| 触发方式 | 今天这个时段已经扫描过时 |
|---|---|
| GitHub 定时（默认 07:13、07:43、16:13、16:43） | 跳过 |
| Mac 触发器（`skip_if_done=true`） | 跳过 |
| **Run workflow**，或 `tools/mac/trigger-radar.sh --force` | 总是扫描，并记录这个时段 |

中午之前的定时运行是早上的扫描，其余的是晚上的扫描。在 12:00 到 15:00 之间的 Mac 触发会跳过，因为没有需要补的扫描。
日志在 `~/Library/Logs/job-radar-trigger*.log`。用 `/bin/zsh tools/mac/uninstall-radar-trigger.sh` 卸载。

## 4. 本地开发

```bash
python -m venv .venv
source .venv/bin/activate      # Windows：.venv\Scripts\activate
pip install -e ".[dev]"
pytest
ruff check .
```

`radar scan --fixture my_jobs.json` 会用你的 `config/` 给保存在文件里的职位打分（格式同
`tests/fixtures/sample_jobs.json`，里面是护理职位），不访问招聘网站，也不访问 GitHub。它会像真实扫描一样写入
`data/`、`reports/` 和 `resumes/jobs/`，所以不要提交它的改动。真实扫描应该在 GitHub Actions 上运行；用上面的触发器启动。

测试使用 `tests/fixtures/` 里一个虚构人物的完整配置，所以无论你的 `config/` 填了什么，测试都能通过。

## 5. 从模板获取更新

修复和改进会进入模板 [estul26/job-radar](https://github.com/estul26/job-radar)。用 **Use this template**
创建的副本不会自动得到它们，而且和模板没有共同的 git 历史，所以不能直接合并。**Update from template** workflow
负责把它们带进来：

1. **Actions → Update from template → Run workflow → Run workflow。**
2. 大约一分钟后，它会创建一个 Pull Request："Update from the template"。描述里写着改了什么，**Files changed**
   里能看到每一行改动。
3. 点击 **Merge pull request**。如果描述里列出了需要你自己更新的 workflow 文件，按它的步骤逐个操作。

它只在你手动启动时运行，想运行几次都可以；再次运行会更新已经打开的 Pull Request。在模板仓库本身里它什么也不做。

它运行的是你副本自己的更新脚本，也就是你合并上一次更新时审阅过的那个，所以不会有你没看过的代码带着你仓库的 token
运行。这个脚本自身的修复会出现在 Pull Request 里，从下一次更新开始使用。如果你副本里的脚本坏了，启动运行时勾选
**script_from_template**，改用模板最新的脚本。

**会更新什么。** 模板自己的文件：`src/`、`tests/`、`docs/`、`tools/`、`.github/` 里的 workflow、action 和 Issue
表单、`pyproject.toml`、两个 README、`LICENSE`、`.gitignore`，以及 `resumes/` 里的简历填写说明（英文和中文）。
对每个文件，它比较三个版本：你的副本创建时（或上次更新时）的模板版本、你的版本、模板的最新版本。

| 如果 | 那么 |
|---|---|
| 只有你改过这个文件 | 保留你的版本。 |
| 只有模板改过 | 使用模板的版本。 |
| 你们都改过，但改的是不同的行（比如你在 `daily-jobs.yml` 里改的 `timezone:` 行） | 两边的改动都保留。 |
| 你们都改了同样的行 | 使用模板的版本，Pull Request 会列出你的改动，方便你加回去。 |
| 你删除了它 | 保持删除。 |

**永远不会改动什么。** `config/`、`resumes/master_resume.json`、`resumes/jobs/`、`resumes/index.csv`、`data/`、
`reports/`，以及模板里没有的任何文件。模板 `config/` 里的示例设置变化时，Pull Request 会附上链接，方便你把新设置抄进
自己的文件。你所在的模板版本记录在 `.github/template-version` 里（不要编辑它），这样下一次更新就知道哪些改动是你的。

**Workflow 文件。** workflow 的标准 token 不能修改 `.github/workflows/` 里的文件。所以默认情况下这些文件不在
Pull Request 里，描述中会给出每个文件的新版本供你粘贴（保留你自己的改动，比如时区），以及编辑它的链接。想让它们直接
包含在 Pull Request 里，请创建一次 token：

1. 在 GitHub 上点你的头像 → **Settings → Developer settings → Personal access tokens → Fine-grained tokens →
   Generate new token**。
2. 在 **Repository access** 下选 **Only select repositories**，选中你的副本。在 **Permissions** 下添加
   **Contents**、**Pull requests** 和 **Workflows**，都设为 **Read and write**。选一个过期日期，点
   **Generate token**。
3. 在你的副本里打开 **Settings → Secrets and variables → Actions → New repository secret**：名称填
   `TEMPLATE_UPDATE_TOKEN`，粘贴 token。

有了这个 token，Pull Request 上的 CI 也会自动运行。没有它的话，关闭再重新打开 Pull Request 即可运行 CI。

**如果运行提示它无法创建 Pull Request**，说明 GitHub Actions 不被允许在你的副本里创建 Pull Request，新仓库默认就是
这样。更新已经准备好了：运行摘要里有链接，点开即可自己创建。或者勾选 **Settings → Actions → General → Allow GitHub
Actions to create and approve pull requests**，点 **Save**，再运行一次。

**在你的电脑上**，用 `gh workflow run update-from-template.yml` 启动，然后在合并前先试一下这次更新：

```bash
gh pr checkout update-from-template
pytest && radar doctor
```
