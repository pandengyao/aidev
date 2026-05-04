# Mac 本地 AI 开发流水线部署计划

## 架构概览

```text
Mac 本地输入（终端 / shell alias / Raycast / Alfred）
    ↓
本地 pipeline.py（参数解析、阶段控制、日志与产物目录）
    ↓ Anthropic 格式直连
OneAPI 网关（Claude Sonnet 4.6）
    ↓
轻量设计阶段（生成 design.md）
    ↓
MetaGPT Team（ProjectManager → Architect → Engineer×2 → QA）
    ↓
/Users/frank/work/aidev/workspace/（MetaGPT 原生工作目录）
    ↓
/Users/frank/work/aidev/runs/{timestamp}-{slug}/（代码、日志、summary.md）
```

**结论**：当前目标是“Mac 本地控制自动开发”，不再默认引入 OpenClaw 和 AutoGen。OpenClaw 更适合通讯 App 入口，AutoGen 更适合复杂多 Agent 讨论；在本地开发流水线里，两者会增加配置、费用、延迟和故障点。

**已实测**：OneAPI 网关支持 Anthropic `/v1/messages` 格式，全部 11 个模型均 HTTP 200。模型名必须用网关注册名（带空格大写）：`"Claude Sonnet 4.6"`。

当前支持模型列表：

- `Kimi-K2.5`
- `MiniMax-M2-Stable`
- `MiniMax-M2.1`
- `GLM-5`
- `GLM-5.1`
- `GLM-5-Turbo`
- `Claude Sonnet 4.6`
- `Kimi-K2.6`
- `MiniMax-M2.7`
- `Claude Sonnet 4.5`
- `Claude Haiku 4.5`

---

## 设计取舍

### 保留：MetaGPT

MetaGPT 是主执行引擎，负责把需求转成工程任务并生成代码。

| 角色 | 职责 |
|------|------|
| `ProjectManager` | 设计文档 → 任务清单 |
| `Architect` | 技术设计 → 模块与接口方案 |
| `Engineer(n_borg=2)` | 任务 → 代码实现（2 并发） |
| `QaEngineer` | 代码 → 测试与质量反馈 |

### 移除：OpenClaw（默认不装）

| 原用途 | 为什么不再默认需要 |
|--------|--------------------|
| 手机 / 通讯 App 入口 | 已改为 Mac 本地控制 |
| Skills 触发 | 本地 CLI、shell alias、Raycast、Alfred 更轻 |
| 结果推送 | 统一放在 `/Users/frank/work/aidev` 下，直接查看更可控 |

后续如果确实要从 WhatsApp、Telegram、Slack 触发，再把 OpenClaw 作为“入口适配层”加回来，但不要让它参与核心工程流水线。

### 移除：AutoGen（默认不装）

| 原用途 | 为什么不再默认需要 |
|--------|--------------------|
| 产品经理 ↔ 架构师讨论 | MetaGPT 内部已有 PM / Architect 角色 |
| 生成技术设计文档 | 一个轻量 OneAPI 调用即可完成 |
| 多 Agent GroupChat | 当前只有两类角色，收益不足以覆盖复杂度 |

后续如果要做需求澄清、多方案辩论、评审委员会等复杂协作，再单独引入 AutoGen。

---

## 原三层方案的主要问题

| 优先级 | 组件 | 问题 |
|--------|------|------|
| 🔴 高 | OpenClaw + AutoGen + MetaGPT | 三层都在做 Agent 编排，职责重叠 |
| 🔴 高 | `pipeline.py` / 文档示例 | API Key 不应出现在 Markdown、代码或 git 中 |
| 🟡 中 | AutoGen → MetaGPT | 设计文档二次转述，增加上下文损耗 |
| 🟡 中 | 多配置体系 | OpenClaw、AutoGen、MetaGPT 都要维护模型配置 |
| 🟡 中 | 全链路重跑 | 缺少 `design` / `implement` / `all` 阶段控制 |
| 🟡 中 | 输出不可追踪 | 缺少固定输出目录、日志、summary 和复盘文件 |
| 🟡 中 | 失败恢复弱 | 任一环节失败后不方便从中间产物继续执行 |

---

## 实施步骤

### Step 1：配置环境变量

先创建统一目录：

```bash
mkdir -p /Users/frank/work/aidev/runs
```

**新建 `/Users/frank/work/aidev/.env`**（此文件不提交 git）：

```bash
ANTHROPIC_API_KEY=你的 OneAPI Key
ANTHROPIC_BASE_URL=https://oneapi-comate.baidu-int.com
ANTHROPIC_MODEL="Claude Sonnet 4.6"
METAGPT_CONFIG=/Users/frank/work/aidev/config2.yaml
```

**新建或更新 `/Users/frank/work/aidev/.gitignore`**：

```gitignore
.env
runs/
__pycache__/
*.pyc
```

可选：如果希望每个终端自动加载环境变量，在你的 shell 启动脚本中加入：

```bash
set -a
[ -f /Users/frank/work/aidev/.env ] && source /Users/frank/work/aidev/.env
set +a
```

### Step 2：安装 Python 依赖

创建并进入独立的 `aidev` 环境（Python 3.11）：

```bash
conda create -n aidev python=3.11 -y
conda activate aidev
```

**新建 `/Users/frank/work/aidev/requirements.txt`**：

```text
metagpt>=0.7.0
python-dotenv>=1.0.0
```

安装：

```bash
conda activate aidev
/Users/frank/work/aidev/install.sh
```

注意：不要使用 `base` 的 Python 3.13。MetaGPT `0.8.1` 更适配 Python 3.11，`faiss-cpu==1.7.4` 在 macOS arm64 + Python 3.11 下有可用 wheel。

### Step 3：配置 MetaGPT

**新建 `/Users/frank/work/aidev/config2.yaml`**：

```yaml
llm:
  api_type: "anthropic"
  base_url: "https://oneapi-comate.baidu-int.com"
  api_key: "${ANTHROPIC_API_KEY}"
  model: "Claude Sonnet 4.6"
  max_token: 4096
```

### Step 4：pipeline.py（轻量版）

当前实际实现已增加：`METAGPT_CONFIG` 自动设置、OneAPI 错误详情、MetaGPT 懒加载、`--budget` 和 `--rounds` 参数。

**新建 `/Users/frank/work/aidev/pipeline.py`**：

```python
"""Mac 本地 AI 开发流水线：轻量设计阶段 → MetaGPT 实现阶段。"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

PROJECT_ROOT = Path("/Users/frank/work/aidev")
RUNS_ROOT = PROJECT_ROOT / "runs"
ENV_FILE = PROJECT_ROOT / ".env"
CONFIG_FILE = PROJECT_ROOT / "config2.yaml"

load_dotenv(ENV_FILE)
os.environ.setdefault("METAGPT_CONFIG", str(CONFIG_FILE))
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("aidev")


def slugify(text: str) -> str:
    slug = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", text.strip())[:40].strip("-")
    return slug or "task"


def create_run_dir(requirement: str, run_dir_arg: Optional[str] = None) -> Path:
    if run_dir_arg:
        run_dir = Path(run_dir_arg).expanduser()
    else:
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        run_dir = RUNS_ROOT / f"{run_id}-{slugify(requirement)}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def get_required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"缺少环境变量：{name}，请检查 {ENV_FILE}")
    return value


def call_oneapi(prompt: str, max_tokens: int = 4096, timeout: int = 180) -> str:
    api_key = get_required_env("ANTHROPIC_API_KEY")
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "https://oneapi-comate.baidu-int.com").rstrip("/")
    model = os.environ.get("ANTHROPIC_MODEL", "Claude Sonnet 4.6")
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    request = urllib.request.Request(
        f"{base_url}/v1/messages",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", "replace")[:1000]
        raise RuntimeError(f"OneAPI HTTP {error.code}: {body}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"OneAPI 请求失败：{error}") from error

    content = data.get("content", [])
    text_blocks = [block.get("text", "") for block in content if isinstance(block, dict)]
    result = "\n".join(block for block in text_blocks if block).strip()
    if not result:
        raise RuntimeError(f"OneAPI 响应中没有文本内容：{json.dumps(data, ensure_ascii=False)[:1000]}")
    return result


def run_design_phase(requirement: str, run_dir: Path) -> str:
    prompt = f"""
你是资深技术负责人。请根据需求生成可执行的技术设计文档，要求包含：
1. 目标与非目标
2. 用户故事和验收标准
3. 模块拆分与数据流
4. 接口/数据结构设计
5. 实施任务清单
6. 测试策略
7. 风险与回滚方案

需求：{requirement}
""".strip()
    design = call_oneapi(prompt)
    (run_dir / "design.md").write_text(design, encoding="utf-8")
    return design


async def run_implementation_phase(design_doc: str, run_dir: Path, budget: float, rounds: int) -> None:
    try:
        from metagpt.roles import Architect, Engineer, ProjectManager, QaEngineer
        from metagpt.team import Team
    except ImportError as error:
        raise RuntimeError("MetaGPT 未安装或版本不兼容，请先运行：python -m pip install -r /Users/frank/work/aidev/requirements.txt") from error

    os.chdir(run_dir)
    team = Team()
    team.hire([ProjectManager(), Architect(), Engineer(n_borg=2), QaEngineer()])
    team.invest(budget)
    team.run_project(f"根据以下技术设计文档实现代码，所有产物写入当前目录：\n\n{design_doc}")
    await team.run(n_round=rounds)


async def run_pipeline(requirement: str, phase: str, run_dir_arg: Optional[str], budget: float, rounds: int) -> Path:
    t0 = time.monotonic()
    run_dir = create_run_dir(requirement, run_dir_arg)
    logger.info("运行目录：%s", run_dir)
    (run_dir / "requirement.md").write_text(requirement, encoding="utf-8")

    design_path = run_dir / "design.md"
    design = ""
    if phase in {"design", "all"}:
        design = await asyncio.wait_for(
            asyncio.to_thread(run_design_phase, requirement, run_dir), timeout=300)
        logger.info("设计阶段完成：%s", design_path)

    if phase in {"implement", "all"}:
        if not design:
            if not design_path.exists():
                raise FileNotFoundError(f"缺少设计文档：{design_path}")
            design = design_path.read_text(encoding="utf-8")
        await asyncio.wait_for(run_implementation_phase(design, run_dir, budget, rounds), timeout=900)
        logger.info("实现阶段完成：%s", run_dir)

    summary = f"# Run Summary\n\n- Requirement: {requirement}\n- Phase: {phase}\n- Output: `{run_dir}`\n- Cost time: {time.monotonic() - t0:.1f}s\n"
    (run_dir / "summary.md").write_text(summary, encoding="utf-8")
    logger.info("Pipeline 完成，总耗时 %.1fs", time.monotonic() - t0)


def main() -> None:
    parser = argparse.ArgumentParser(description="Mac 本地 AI 开发流水线")
    parser.add_argument("requirement", help="要实现的需求")
    parser.add_argument("--phase", choices=["design", "implement", "all"], default="all")
    parser.add_argument("--run-dir", help="复用已有运行目录，常用于从 design.md 继续实现")
    parser.add_argument("--budget", type=float, default=50.0, help="MetaGPT 预算，默认 50.0")
    parser.add_argument("--rounds", type=int, default=30, help="MetaGPT 运行轮数，默认 30")
    args = parser.parse_args()
    asyncio.run(run_pipeline(args.requirement, args.phase, args.run_dir, args.budget, args.rounds))


if __name__ == "__main__":
    main()
```

### Step 5：本地快捷入口

可选：在你的 shell 启动脚本中加入一个 alias，替代 OpenClaw 触发：

```bash
alias aidev='conda run -n aidev python /Users/frank/work/aidev/pipeline.py'
```

使用方式：

```bash
aidev "开发用户登录功能，含注册、JWT 鉴权"
aidev "开发购物车功能" --phase design
aidev "开发购物车功能" --phase implement --run-dir /Users/frank/work/aidev/runs/20260503-120000-开发购物车功能
```

---

## 文件清单

| 文件 | 操作 |
|------|------|
| `/Users/frank/work/aidev/.env` | 新建：存放 OneAPI Key，不提交 git |
| `/Users/frank/work/aidev/aidev.yaml` | 新建：集中配置模型、预算、轮数、运行目录、workspace 目录和多语言验证命令 |
| `/Users/frank/work/aidev/.gitignore` | 新建/更新：忽略 `.env`、`runs/`、`workspace/` 和 Python 缓存 |
| `/Users/frank/work/aidev/requirements.txt` | 新建：Python 运行依赖 |
| `/Users/frank/work/aidev/install.sh` | 新建：适配 Python 3.11 的安装脚本 |
| `/Users/frank/work/aidev/pipeline.py` | 新建：Mac 本地轻量流水线 |
| `/Users/frank/work/aidev/config2.yaml` | 自动生成：MetaGPT 模型配置，包含本地密钥，已加入 `.gitignore` |
| `/Users/frank/work/aidev/runs/{timestamp}-{slug}/` | 自动生成：每次运行的设计、代码、日志和总结 |

不再默认创建：

- OpenClaw 配置文件和技能文件
- AutoGen 相关代码和 `pyautogen` 依赖

---

## 验证步骤

```bash
# 1. 激活 aidev 环境并验证环境变量
conda activate aidev
source /Users/frank/work/aidev/.env
python - <<'PY'
import os
assert os.environ.get("ANTHROPIC_API_KEY"), "ANTHROPIC_API_KEY 未设置"
print(os.environ.get("ANTHROPIC_MODEL", "Claude Sonnet 4.6"))
PY

# 2. 验证 OneAPI 连通性
curl -X POST "https://oneapi-comate.baidu-int.com/v1/messages" \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  -d '{"model":"Claude Sonnet 4.6","max_tokens":10,"messages":[{"role":"user","content":"hi"}]}'

# 3. 只跑设计阶段
python /Users/frank/work/aidev/pipeline.py "开发用户登录功能，含注册、JWT 鉴权" --phase design

# 4. 从已有 design.md 继续实现
python /Users/frank/work/aidev/pipeline.py "开发用户登录功能，含注册、JWT 鉴权" \
  --phase implement \
  --run-dir /Users/frank/work/aidev/runs/20260503-120000-开发用户登录功能

# 5. 跑完整链路
python /Users/frank/work/aidev/pipeline.py "开发用户登录功能，含注册、JWT 鉴权"

# 6. 查看产物
ls -R /Users/frank/work/aidev/runs/20260503-120000-开发用户登录功能 | tail -50
```

预期结果：

- `/Users/frank/work/aidev/runs/{timestamp}-{slug}/requirement.md` 保存原始需求
- `/Users/frank/work/aidev/runs/{timestamp}-{slug}/design.md` 保存轻量设计阶段输出
- `/Users/frank/work/aidev/runs/{timestamp}-{slug}/summary.md` 保存运行摘要
- MetaGPT 在同一运行目录生成代码和测试相关产物

---

## 当前验证状态

| 项目 | 状态 | 说明 |
|------|------|------|
| 目录和文件 | ✅ 已创建 | `/Users/frank/work/aidev/` 已生成核心文件 |
| Python 语法 | ✅ 通过 | `pipeline.py` 已通过 `py_compile` |
| OneAPI 连通性 | ✅ 通过 | `/v1/messages` 返回正常文本 |
| 设计阶段 | ✅ 通过 | `--phase design` 已生成 `design.md` 和 `summary.md` |
| MetaGPT 安装 | ✅ 已验证 | 已创建 `aidev` 环境，Python `3.11.15`，MetaGPT 角色导入通过 |
| 实现阶段 | ✅ 通过 | 最小需求已跑通，MetaGPT 生成代码并复制到 `runs/.../metagpt_output/` |
| 运行日志 | ✅ 已增强 | 每次运行生成 `run.log`，`summary.md` 会记录日志路径 |
| 环境固化 | ✅ 已完成 | 已导出 `/Users/frank/work/aidev/environment.yml` |
| 第二个小任务 | ✅ 通过 | 计算器任务可生成并支持 `add/sub/mul/div`；`repair` 后 `py_compile`、`pytest`、CLI smoke 均通过 |
| 运行参数 | ✅ 已增强 | 已支持 `--mode new/patch`、`--preview-patch`、`--model`、`--output-root`、`--archive-workspace`、`--target-dir`、`--auto-continue` |
| Shell 入口 | ✅ 已固化 | 已创建 `/Users/frank/work/aidev/bin/aidev`，并在 `~/.zshrc` 添加 PATH |
| Workspace 合并 | ✅ 已完成 | MetaGPT 原生工作目录已切到 `/Users/frank/work/aidev/workspace` |
| 目标目录落盘 | ✅ 已验证 | `--target-dir` 可将验证通过的最终项目复制到指定目录，并生成 `target_diff.md` |
| Git diff 摘要 | ✅ 已验证 | 当目标目录是 Git 仓库时，`target_diff.md` 会记录 git status、`git diff --check`、diff stat、diff preview 和建议命令 |
| 脏 Git 保护 | ✅ 已验证 | 默认拒绝覆盖有未提交改动的 Git 目标目录；`--allow-dirty-target` 可显式覆盖 |
| 自动推进 | ✅ 已验证 | `--auto-continue` 可在验证失败时自动进入 `repair`，直到通过或达到上限 |
| 外部设计文档 | ✅ 已验证 | `--design-file` 可传入 Markdown 技术设计文档并直接进入实现阶段 |
| 配置文件化 | ✅ 已验证 | 已新增 `/Users/frank/work/aidev/aidev.yaml`，CLI 默认值和验证命令可从配置读取，并支持启动时字段校验 |
| 多语言验证 | ✅ 已验证 | `verify` 可识别 Python、Node、Go、Rust；缺失工具可按配置自动安装，Node/Go/Rust 示例均已通过 |
| 运维命令 | ✅ 已验证 | 已支持并验证 `--status`、`--list-runs N`、`--clean --dry-run` |
| 版本化 | ✅ 已完成 | `aidev.yaml` 已加入 `version: "0.1.0"`，`aidev --status` 会显示版本号 |
| Patch 模式 | ✅ 已验证 | `--mode patch` 可读取 `--target-dir` 上下文，并支持 FILE 块补丁应用与 `--preview-patch` 预览 |

---

## 后续可选增强

| 增强项 | 说明 |
|--------|------|
| 质量门禁 | `verify` 会自动识别项目根、运行 `py_compile`、`pytest`、CLI smoke test，并识别 Node/Go/Rust 测试命令 |
| `aidev.yaml` | 集中管理默认 `model`、`budget`、`rounds`、`max_repair_attempts`、`runs_root`、`workspace_root`、Node/Go/Rust 验证命令和缺失工具安装包，并做字段类型校验 |
| `--mode new/patch` | `new` 生成新项目；`patch` 读取目标项目上下文并面向已有项目修改 |
| `--preview-patch` | 只生成 patch 预览和 `target_diff.md`，不写入目标目录 |
| `--design-file` | 传入已有 Markdown 技术设计文档，跳过自动设计并写入 `run/design.md` |
| `--phase verify` / `--no-verify` | 实现阶段后自动验证，或按需跳过验证 |
| `--phase repair` | 自动修复语法截断问题并重新生成 `verification.md` |
| 产物清洗 | 已在 `pipeline.py` 中清理 Markdown fence，并支持本地截断返修 |
| `--model` | 单次运行覆盖 `ANTHROPIC_MODEL` |
| `--output-root` | 覆盖运行目录根路径，默认 `/Users/frank/work/aidev/runs` |
| `--archive-workspace` | 复制 MetaGPT 产物后清理 `/Users/frank/work/aidev/workspace` 原始目录 |
| `--target-dir` | 验证通过后将最终项目文件复制到指定目录，并生成 `target_diff.md`；Git 目录会附带 status/diff 摘要 |
| `--allow-dirty-target` | 允许覆盖有未提交改动的 Git 目标目录，默认不允许 |
| `--auto-continue` | 验证失败时自动执行 `repair`，直到通过或达到上限 |
| `--max-repair-attempts` | 控制自动返修最大次数，默认 5 |
| `--budget` | 控制 `team.invest()` 成本预算 |
| `--rounds` | 控制 MetaGPT `team.run(n_round=...)` 轮数 |
| 自动测试 | 已支持 `pytest` / `npm test` / `go test ./...` / `cargo test` 的识别、自动安装和报告 |
| 运维命令 | 已支持并验证 `--status`、`--list-runs N`、`--clean --dry-run`、`--clean --include-test` |
| diff 摘要 | 已支持 Git status、`git diff --check`、diff stat、diff preview 和建议命令 |
| OpenClaw 入口 | 需要手机或聊天软件触发时再作为入口适配层接入 |
| AutoGen 评审 | 需要多方案辩论或设计评审时再作为可选设计阶段接入 |
