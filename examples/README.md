# aidev examples

这里放置 `aidev` 的最小使用示例，方便验证不同入口和工作流。

## 当前保留的验证 run

`runs/` 当前保留了一些历史示例产物；新 run 会使用 `编号-项目名-时间戳` 命名，并按阶段拆分到 `00_input/`、`01_design/`、`02_metagpt/`、`03_code/`、`04_verification/`、`05_repair/`、`06_reports/`、`07_target/`。当前历史示例包括：

```text
/Users/frank/work/aidev/runs/20260504-190639-实现技术设计文档-hello-design-md
/Users/frank/work/aidev/runs/20260504-190639-给-README-增加-Usage-小节-包含-npm-install-和-np
/Users/frank/work/aidev/runs/20260504-101758-创建一个-Python-CLI-计算器-支持-add-sub-mul-div-并
```

## 示例 1：从外部 Markdown 输入实现

文件：

```text
examples/design-file/hello-design.md
```

命令：

```bash
aidev \
  --design-file /Users/frank/work/aidev/examples/design-file/hello-design.md \
  --phase implement \
  --auto-continue
```

用途：验证 `--design-file` 可以在没有自然语言 requirement 的情况下工作。

运行后建议查看：

```bash
cat /Users/frank/work/aidev/runs/<run-dir>/06_reports/summary.md
cat /Users/frank/work/aidev/runs/<run-dir>/06_reports/meta_summary.md
cat /Users/frank/work/aidev/runs/<run-dir>/04_verification/verification.md
```

其中 `meta_summary.md` 用来确认 MetaGPT 的 PRD、系统设计、任务拆分和最终项目目录是否已被索引。

说明：如果外部 Markdown 示例只让 MetaGPT 生成中间设计/资源文档、没有生成可执行代码或测试，`verification.md` 可能显示 `UNKNOWN`；这时重点查看 `meta_summary.md` 和 `metagpt_output/`。

## 示例 2：复杂 Markdown 设计输入

文件：

```text
examples/design-file/taskflow-complex-design.md
```

用途：验证复杂设计文档输入，包括多模块 Python CLI、JSON 持久化、CSV 导入导出、统计和 pytest 测试。

本地已验证的复杂 run：

```text
/Users/frank/work/aidev/runs/20260504-212907-实现技术设计文档-taskflow-complex-design-md
```

注意：复杂项目可能超过单次 MetaGPT 实现超时时间；如果 workspace 已生成部分产物，可以将其复制到 run 的 `metagpt_output/` 后继续执行 `--phase verify`。

## 示例 3：patch 模式预览已有 Node 项目

目标项目：

```text
examples/patch-node/
```

先预览，不写入目标目录：

```bash
aidev "给 README 增加 Usage 小节，包含 npm install 和 npm test" \
  --mode patch \
  --phase all \
  --target-dir /Users/frank/work/aidev/examples/patch-node \
  --preview-patch \
  --auto-continue
```

确认 `target_diff.md` 后再落盘：

```bash
aidev "给 README 增加 Usage 小节，包含 npm install 和 npm test" \
  --mode patch \
  --phase all \
  --target-dir /Users/frank/work/aidev/examples/patch-node \
  --auto-continue
```

用途：验证 `--mode patch`、`--preview-patch`、`--target-dir`。

运行后建议查看：

```bash
cat /Users/frank/work/aidev/runs/<run-dir>/06_reports/summary.md
cat /Users/frank/work/aidev/runs/<run-dir>/07_target/target_diff.md
cat /Users/frank/work/aidev/runs/<run-dir>/04_verification/verification.md
```

patch 模式直接生成文件块并应用到临时产物目录，通常不会产生完整 MetaGPT 中间文档；重点检查 `target_diff.md` 和验证报告。

## 示例 4：从需求文本创建新项目

需求文件：

```text
examples/requirements/calculator-requirement.md
```

命令：

```bash
aidev "$(cat /Users/frank/work/aidev/examples/requirements/calculator-requirement.md)" \
  --phase all \
  --auto-continue
```

用途：验证自然语言/Markdown 需求文本入口。

运行后建议查看：

```bash
cat /Users/frank/work/aidev/runs/<run-dir>/06_reports/summary.md
cat /Users/frank/work/aidev/runs/<run-dir>/06_reports/meta_summary.md
cat /Users/frank/work/aidev/runs/<run-dir>/04_verification/verification.md
```

## 快速验证已有 run 的 MetaGPT 透明度产物

如果只是验证 `meta_summary.md` 生成逻辑，不需要重新调用模型，可以复用已有 run：

```bash
aidev "验证已有产物" \
  --phase verify \
  --run-dir /Users/frank/work/aidev/runs/<run-dir>
```

验证点：

- `summary.md` 包含 `MetaGPT Artifacts`
- `meta_summary.md` 存在
- `meta_summary.md` 能列出 PRD、System Design、Tasks 或 Generated Project
- `verification.md` 状态为 `PASSED`
