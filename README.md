# aidev

`aidev` 是一个 Mac 本地 AI 开发流水线工具，支持从自然语言需求或外部 Markdown 输入（设计大纲 / 技术设计 / PRD 摘要）出发，生成代码、自动验证、自动修复，并可安全落盘到 Git 项目。

## 目录结构

```text
/Users/frank/work/aidev/
├── pipeline.py          # 主入口
├── aidev.yaml           # 默认配置
├── .env.example         # 环境变量模板，可提交
├── .env                 # OneAPI Key 等敏感配置，不提交
├── config2.yaml         # 自动生成的 MetaGPT 配置，不提交
├── environment.yml      # Conda 环境导出
├── bin/aidev            # 可执行入口
├── docs/history/        # 历史计划和演进记录
├── examples/            # 使用示例
├── metagpt/tools/       # MetaGPT 运行所需 schema
├── runs/                # 每次运行的结果（忽略提交）
├── workspace/           # MetaGPT 原生工作目录（忽略提交）
├── test-runs/           # 本地验证样例（按需生成，忽略提交）
└── target-smoke/        # target-dir 验证样例（按需生成，忽略提交）
```

## 环境准备

```bash
conda create -n aidev python=3.11 -y
conda activate aidev
/Users/frank/work/aidev/install.sh
```

建议优先使用 `install.sh` 安装依赖；`requirements.txt` 仅作为依赖清单参考，MetaGPT 相关依赖对版本比较敏感。`install.sh` 通过 `conda run -n aidev python` 使用虚拟环境，不依赖 Conda 的安装根路径。

`~/.zshrc` 中已配置 PATH：

```bash
export PATH="/Users/frank/work/aidev/bin:$PATH"
```

可执行入口：

```bash
/Users/frank/work/aidev/bin/aidev
```

新终端生效：

```bash
source ~/.zshrc
```

## 配置

默认配置在 `/Users/frank/work/aidev/aidev.yaml`：

```yaml
version: "0.1.0"
model: "Claude Sonnet 4.6"
budget: 50.0
rounds: 30
max_repair_attempts: 5
engineer_count: 2
max_token: 128000
runs_root: "/Users/frank/work/aidev/runs"
workspace_root: "/Users/frank/work/aidev/workspace"
verification:
  auto_install_tools: true
  node:
    command: ["npm", "test"]
    timeout: 180
    conda_package: "nodejs"
  go:
    command: ["go", "test", "./..."]
    timeout: 180
    conda_package: "go"
  rust:
    command: ["cargo", "test"]
    timeout: 240
    conda_package: "rust"
```

敏感配置在 `/Users/frank/work/aidev/.env`。新机器上先复制模板：

```bash
cp /Users/frank/work/aidev/.env.example /Users/frank/work/aidev/.env
```

然后填写自己的 OneAPI Key：

```bash
ANTHROPIC_API_KEY=你的 OneAPI Key
ANTHROPIC_BASE_URL=https://oneapi-comate.baidu-int.com
ANTHROPIC_MODEL="Claude Sonnet 4.6"
```

如果 OneAPI 后续开放新模型，可直接修改 `.env` 中的 `ANTHROPIC_MODEL`；运行时会尝试检查该模型是否出现在 `/v1/models` 返回列表中。

### `aidev.yaml` 与 `config2.yaml` 的区别

`aidev.yaml` 是 aidev 自己的配置文件，用来管理：

- 默认模型名
- 默认预算和轮数
- 自动返修次数
- MetaGPT Engineer 数量 `engineer_count`
- `runs_root` 和 `workspace_root`
- MetaGPT 单次响应上限 `max_token`
- Node / Go / Rust 的验证命令和自动安装包名

`config2.yaml` 是 MetaGPT `0.8.x` 约定的配置文件名，不是 aidev 自定义的名字。MetaGPT 内部默认读取 `~/.metagpt/config2.yaml`，所以 aidev 保留这个文件名来兼容 MetaGPT。

运行时 `pipeline.py` 会根据 `.env` 和 `aidev.yaml` 自动生成：

```text
/Users/frank/work/aidev/config2.yaml
~/.metagpt/config2.yaml
```

`config2.yaml` 里会包含 OneAPI / Anthropic 的连接配置。当前实现会写入运行时展开后的 API Key，因为 MetaGPT 对 `${ANTHROPIC_API_KEY}` 这种占位符展开不稳定；这样做能保证 MetaGPT 阶段可用。

注意：`config2.yaml` 可能包含明文 API Key，已经加入 `.gitignore`，不要提交、不要上传、不要跨电脑共享。如果真实 Key 曾经被贴出或误传，建议去 OneAPI 后台重置/更换。

## 跨电脑迁移

推荐用 GitHub 或其他 Git 仓库共享项目代码，但只共享可复现源码和文档，不共享本机运行产物和密钥。

在当前电脑推送：

```bash
cd /Users/frank/work/aidev
git remote add origin <你的 GitHub 仓库地址>
git push -u origin main
```

在另一台电脑恢复：

```bash
git clone <你的 GitHub 仓库地址> /Users/frank/work/aidev
cd /Users/frank/work/aidev
conda create -n aidev python=3.11 -y
conda activate aidev
./install.sh
cp .env.example .env
```

然后编辑 `.env`，填入自己的 `ANTHROPIC_API_KEY`。`ANTHROPIC_MODEL` 可以填写当前可用模型，例如 Sonnet 或未来的 Opus 系列；运行 aidev 时会先尝试读取 OneAPI 模型列表并校验当前模型是否可用。`config2.yaml` 不需要手动复制，运行 aidev 时会自动生成。`install.sh` 不要求新电脑的 Conda 安装在固定目录，只要求存在名为 `aidev` 的 Conda 环境。

忽略文件的处理方式：

- `.env`：每台电脑单独创建，不能提交。
- `config2.yaml`：自动生成，不能提交，也不需要共享；如果其中的真实 Key 泄露，建议重置/更换 Key。
- `runs/`：运行记录和中间产物，默认不提交；确需共享时单独打包某个 run 目录。
- `workspace/`、`logs/`、`test-runs/`：本地运行产物，不需要共享。

## 示例

示例目录：

```text
/Users/frank/work/aidev/examples/
```

当前包含：

- `design-file/hello-design.md`：验证 `--design-file`
- `patch-node/`：验证 `--mode patch` 和 `--preview-patch`
- `requirements/calculator-requirement.md`：验证需求文本入口

详细命令见：

```text
/Users/frank/work/aidev/examples/README.md
```

## 历史文档

早期部署计划和演进记录已归档到：

```text
/Users/frank/work/aidev/docs/history/ai-pipeline-plan.md
```

当前使用和维护请以本 README 为准。

## 常用命令

查看状态：

```bash
aidev --status
```

列出最近运行：

```bash
aidev --list-runs 10
```

清理旧目录（预览）：

```bash
aidev --clean --dry-run --days 7
```

清理旧目录并包含测试目录（预览）：

```bash
aidev --clean --dry-run --include-test --days 7
```

## 参数说明

### 基础参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `requirement` | 无 | 用户需求文本。使用 `--status`、`--list-runs`、`--clean`、`--design-file` 或 `--run-dir` 时可省略。 |
| `--model` | `aidev.yaml` 中的 `model` | 单次运行覆盖模型名，例如 `"Claude Sonnet 4.6"`。 |
| `--budget` | `aidev.yaml` 中的 `budget`，当前 `50.0` | MetaGPT 预算上限。不是无限预算，防止异常循环消耗过多 token。 |
| `--rounds` | `aidev.yaml` 中的 `rounds`，当前 `30` | MetaGPT 多 Agent 最大运行轮数。 |
| `engineer_count` | 配置项，当前 `2` | 仅在 `aidev.yaml` 中配置；表示 MetaGPT Engineer 分身数量。小任务可设 `1`，多模块任务可设 `2`。 |
| `--output-root` | `aidev.yaml` 中的 `runs_root` | 运行目录根路径。默认 `/Users/frank/work/aidev/runs`。 |

### 阶段控制

| 参数 | 可选值 | 说明 |
|------|--------|------|
| `--phase` | `design` / `implement` / `verify` / `repair` / `all` | 控制执行阶段。`all` 表示设计、实现、验证完整链路。 |
| `--run-dir` | 路径 | 复用已有运行目录，常用于基于已有 `design.md` 继续实现、验证或修复。 |
| `--design-file` | Markdown 文件路径 | 使用外部 Markdown 输入（设计大纲 / 技术设计 / PRD 摘要），复制到当前 run 的 `design.md` 后交给 MetaGPT 实现。 |

### 项目模式

| 参数 | 可选值 | 说明 |
|------|--------|------|
| `--mode` | `new` / `patch` | `new` 生成新项目；`patch` 读取 `--target-dir` 上下文并面向已有项目生成补丁。 |
| `--target-dir` | 路径 | 验证通过后将最终项目文件复制到指定目录。patch 模式必须提供。 |
| `--preview-patch` | 开关 | 只生成 patch 预览和 `target_diff.md`，不写入目标目录。正式项目建议先使用。 |
| `--allow-dirty-target` | 开关 | 允许覆盖有未提交改动的 Git 目标目录。默认不允许。 |
| `--archive-workspace` | 开关 | 复制 MetaGPT 产物后清理 `/Users/frank/work/aidev/workspace` 中的原始工作目录。 |

### 验证与修复

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--auto-continue` | 关闭 | 验证失败时自动执行 `repair`，直到通过或达到返修上限。 |
| `--max-repair-attempts` | `aidev.yaml` 中的 `max_repair_attempts`，当前 `5` | 自动返修最大次数。 |
| `--no-verify` | 关闭 | 实现阶段后不自动运行验证。通常不建议使用。 |

### 运维命令

| 参数 | 说明 |
|------|------|
| `--status` | 查看版本、配置、模型、工具链版本、OneAPI 连通性和最近一次 run 状态。 |
| `--list-runs N` | 列出最近 N 次运行。 |
| `--clean` | 清理旧运行目录和临时目录。 |
| `--days` | 配合 `--clean` 使用，清理多少天以前的目录，默认 `7`。 |
| `--dry-run` | 配合 `--clean` 使用，只预览不删除。 |
| `--include-test` | 配合 `--clean` 使用，同时清理 `test-runs` 和 `target-smoke`。 |

## 版本与维护

查看版本和工具链状态：

```bash
aidev --status
```

导出当前环境：

```bash
conda env export -n aidev > /Users/frank/work/aidev/environment.yml
```

更新依赖或切换模型后建议执行：

```bash
conda run -n aidev python -m py_compile /Users/frank/work/aidev/pipeline.py
aidev --status
aidev --list-runs 5
```

`aidev --status` 会尝试读取 OneAPI `/v1/models`，展示可用模型数量、当前模型是否可识别，以及部分模型示例。

## 从需求生成代码

```bash
aidev "创建一个 Python CLI 计算器，支持 add/sub/mul/div，并包含 pytest 测试" \
  --phase all \
  --auto-continue \
  --max-repair-attempts 5
```

输出会进入：

```text
/Users/frank/work/aidev/runs/{编号}-{项目名}-{timestamp}/
```

新 run 采用编号 + 项目名 + 时间戳命名，例如：

```text
0001-创建一个-Python-CLI-计算器-20260504-101758/
```

阶段产物按目录拆分：

```text
00_input/          # requirement.md
01_design/         # design.md
02_metagpt/        # MetaGPT PRD、系统设计、任务拆分、资源文档等原始中间产物
03_code/           # 最终代码产物，用于验证和落盘
04_verification/   # verification.md
05_repair/         # repair.md
06_reports/        # run.log、summary.md、meta_summary.md、patch_response.txt
07_target/         # target_diff.md
```

`meta_summary.md` 会索引 MetaGPT 生成的 PRD、系统设计、任务拆分、资源文档和代码目录，方便快速查看中间过程；完整原始文件保存在 `02_metagpt/`，最终代码保存在 `03_code/`。

## 从外部 Markdown 输入生成代码

```bash
aidev \
  --design-file /path/to/design.md \
  --phase implement \
  --auto-continue
```

传入 `--design-file` 后，工具会把该 Markdown 文件复制到当前 run 的 `design.md`，并交给 MetaGPT 继续处理。这个 Markdown 可以是完整技术设计，也可以只是设计大纲或 PRD 摘要；MetaGPT 会继续进行 PRD、系统设计和任务拆分。此时可以不写自然语言需求，aidev 会自动用文件名生成 `requirement.md`。

如果你有强约束，建议在 Markdown 中明确写出文件名、接口、输出格式、验收标准和测试要求，避免 MetaGPT 自由发挥。

## 修改已有项目

使用 `--mode patch` 可以让 aidev 读取目标项目上下文，生成面向已有项目的技术设计或实现方案。实现阶段会要求模型输出 `---FILE: path---` 文件块，aidev 会解析后直接应用到临时产物目录，再通过验证后落盘到目标项目：

```bash
aidev "给现有项目增加 README Usage 小节" \
  --mode patch \
  --target-dir /path/to/project \
  --phase design
```

`patch` 模式会读取目标目录的：

- 文件树（截断）
- Git 状态
- `README.md`
- `package.json`
- `pyproject.toml`
- `go.mod`
- `Cargo.toml`
- `requirements.txt`

如果要把实现结果落盘到已有 Git 项目，建议配合：

```bash
aidev "实现目标变更" \
  --mode patch \
  --target-dir /path/to/project \
  --phase all \
  --auto-continue
```

正式项目建议先预览 patch，不写入目标目录：

```bash
aidev "实现目标变更" \
  --mode patch \
  --target-dir /path/to/project \
  --phase all \
  --preview-patch \
  --auto-continue
```

预览通过后，去掉 `--preview-patch` 再执行一次以落盘。

默认会拒绝覆盖有未提交改动的 Git 目录；确需覆盖时再加 `--allow-dirty-target`。

patch 模式已验证的典型流程：

```bash
aidev "给现有 Node 示例 README 增加 Usage 小节，包含 npm install 和 npm test" \
  --mode patch \
  --phase all \
  --target-dir /path/to/project \
  --allow-dirty-target \
  --auto-continue
```

成功后会生成：

- `verification.md`：验证 `npm test` 等命令是否通过
- `target_diff.md`：记录复制文件、Git 状态、`git diff --check`、diff stat 和建议命令

## 验证与修复

只验证已有 run：

```bash
aidev "验证已有产物" \
  --phase verify \
  --run-dir /Users/frank/work/aidev/runs/<run-dir>
```

自动修复已有 run：

```bash
aidev "修复已有产物" \
  --phase repair \
  --run-dir /Users/frank/work/aidev/runs/<run-dir>
```

自动验证失败后进入修复：

```bash
aidev "实现并自动修复" \
  --phase all \
  --auto-continue \
  --max-repair-attempts 5
```

## 落盘到目标项目

验证通过后复制到目标目录：

```bash
aidev "实现功能" \
  --phase all \
  --target-dir /path/to/project \
  --auto-continue
```

如果目标目录是 Git 仓库：

- 默认会拒绝覆盖有未提交改动的目录。
- 如需显式允许覆盖，添加：

```bash
--allow-dirty-target
```

落盘后会生成 `target_diff.md`，包含：

- copied/new files
- git status before/after
- `git diff --check`
- diff stat
- diff preview
- 建议提交前命令

## 多语言验证

`verify` 会自动识别并运行：

- Python：`py_compile`、`pytest`
- Node：`npm test`
- Go：`go test ./...`
- Rust：`cargo test`

如果工具缺失且 `aidev.yaml` 中 `verification.auto_install_tools: true`，会自动尝试安装对应 conda 包。

## 常见问题

### OneAPI 429 限流

工具会自动重试。若仍频繁出现，降低并发使用频率，或稍后再运行。

### 目标 Git 目录有未提交改动

默认拒绝覆盖。先处理目标目录：

```bash
git status --short
git diff
git add .
```

或显式添加：

```bash
--allow-dirty-target
```

### 生成代码有 Markdown 代码围栏

`verify` 会自动清理常见的 `## Code:`、```python、``` 代码围栏。

### 测试文件截断

`repair` 会优先做本地截断修复；无法修复时会调用 OneAPI 重写失败文件。

## 推荐工作流

### 工作流 1：创建新项目

1. 先跑完整链路：

   ```bash
   aidev "创建 hello.py，输出 hello aidev" --phase all --auto-continue
   ```

2. 查看运行结果：

   ```bash
   aidev --list-runs 3
   cat /Users/frank/work/aidev/runs/<run-dir>/06_reports/summary.md
   cat /Users/frank/work/aidev/runs/<run-dir>/04_verification/verification.md
   ```

3. 如果要复制到目标目录：

   ```bash
   aidev "验证并落盘" \
     --phase verify \
     --run-dir /Users/frank/work/aidev/runs/<run-dir> \
     --target-dir /path/to/new-project
   ```

### 工作流 2：从外部 Markdown 输入实现

1. 准备 Markdown 输入。它可以是设计大纲、完整技术设计或 PRD 摘要；此场景下自然语言需求可以省略。

2. 直接进入实现：

   ```bash
   aidev \
     --design-file /path/to/design.md \
     --phase implement \
     --auto-continue
   ```

3. 查看验证报告：

   ```bash
   cat /Users/frank/work/aidev/runs/<run-dir>/04_verification/verification.md
   ```

### 工作流 3：修改已有项目（推荐先预览）

1. 先预览补丁，不写入目标目录：

   ```bash
   aidev "实现目标变更" \
     --mode patch \
     --phase all \
     --target-dir /path/to/project \
     --preview-patch \
     --auto-continue
   ```

2. 查看预览结果：

   ```bash
   cat /Users/frank/work/aidev/runs/<run-dir>/06_reports/summary.md
   cat /Users/frank/work/aidev/runs/<run-dir>/06_reports/meta_summary.md
   cat /Users/frank/work/aidev/runs/<run-dir>/04_verification/verification.md
   ```

3. 确认无误后落盘：

   ```bash
   aidev "实现目标变更" \
     --mode patch \
     --phase all \
     --target-dir /path/to/project \
     --auto-continue
   ```

4. 如果目标 Git 目录已有未提交改动，默认会拒绝覆盖；确需覆盖时加：

   ```bash
   --allow-dirty-target
   ```

### 工作流 4：失败后修复

1. 只验证已有运行：

   ```bash
   aidev "验证已有产物" --phase verify --run-dir /Users/frank/work/aidev/runs/<run-dir>
   ```

2. 自动修复：

   ```bash
   aidev "修复已有产物" --phase repair --run-dir /Users/frank/work/aidev/runs/<run-dir>
   ```

3. 或在完整链路中自动修复：

   ```bash
   aidev "实现目标功能" --phase all --auto-continue --max-repair-attempts 5
   ```

### 工作流 5：日常维护

```bash
aidev --status
aidev --list-runs 10
aidev --clean --dry-run --days 7
conda env export -n aidev > /Users/frank/work/aidev/environment.yml
```
