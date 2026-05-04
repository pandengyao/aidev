"""Mac 本地 AI 开发流水线：轻量设计阶段 → MetaGPT 实现阶段。"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import shutil
import subprocess
import time
import tomllib
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
import yaml

PROJECT_ROOT = Path("/Users/frank/work/aidev")
AIDEV_CONFIG_FILE = PROJECT_ROOT / "aidev.yaml"
ENV_FILE = PROJECT_ROOT / ".env"
CONFIG_FILE = PROJECT_ROOT / "config2.yaml"
DEFAULT_CONFIG = {
    "version": "0.1.0",
    "model": "Claude Sonnet 4.6",
    "budget": 50.0,
    "rounds": 30,
    "max_repair_attempts": 5,
    "engineer_count": 2,
    "max_token": 128000,
    "runs_root": str(PROJECT_ROOT / "runs"),
    "workspace_root": str(PROJECT_ROOT / "workspace"),
    "verification": {
        "auto_install_tools": True,
        "node": {"command": ["npm", "test"], "timeout": 180, "conda_package": "nodejs"},
        "go": {"command": ["go", "test", "./..."], "timeout": 180, "conda_package": "go"},
        "rust": {"command": ["cargo", "test"], "timeout": 240, "conda_package": "rust"},
    },
}


def validate_aidev_config(config: dict) -> None:
    errors: list[str] = []
    if not isinstance(config.get("version"), str) or not config.get("version"):
        errors.append("version 必须是非空字符串")
    if not isinstance(config.get("model"), str) or not config.get("model"):
        errors.append("model 必须是非空字符串")
    for key in ["budget"]:
        if not isinstance(config.get(key), (int, float)) or float(config[key]) <= 0:
            errors.append(f"{key} 必须是大于 0 的数字")
    for key in ["rounds", "max_repair_attempts", "engineer_count", "max_token"]:
        if not isinstance(config.get(key), int) or int(config[key]) <= 0:
            errors.append(f"{key} 必须是大于 0 的整数")
    for key in ["runs_root", "workspace_root"]:
        if not isinstance(config.get(key), str) or not config.get(key):
            errors.append(f"{key} 必须是非空路径字符串")

    verification = config.get("verification")
    if not isinstance(verification, dict):
        errors.append("verification 必须是字典")
    else:
        if not isinstance(verification.get("auto_install_tools"), bool):
            errors.append("verification.auto_install_tools 必须是布尔值")
        for language in ["node", "go", "rust"]:
            settings = verification.get(language)
            if not isinstance(settings, dict):
                errors.append(f"verification.{language} 必须是字典")
                continue
            command = settings.get("command")
            if not isinstance(command, list) or not command or not all(isinstance(item, str) and item for item in command):
                errors.append(f"verification.{language}.command 必须是非空字符串列表")
            timeout = settings.get("timeout")
            if not isinstance(timeout, int) or timeout <= 0:
                errors.append(f"verification.{language}.timeout 必须是大于 0 的整数")
            package = settings.get("conda_package")
            if not isinstance(package, str) or not package:
                errors.append(f"verification.{language}.conda_package 必须是非空字符串")

    if errors:
        detail = "\n".join(f"- {error}" for error in errors)
        raise ValueError(f"aidev.yaml 配置无效：\n{detail}")


def load_aidev_config() -> dict:
    if not AIDEV_CONFIG_FILE.exists():
        config = DEFAULT_CONFIG.copy()
        validate_aidev_config(config)
        return config
    loaded = yaml.safe_load(AIDEV_CONFIG_FILE.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise ValueError("aidev.yaml 顶层必须是字典")
    config = DEFAULT_CONFIG.copy()
    config.update(loaded)
    config["verification"] = DEFAULT_CONFIG["verification"].copy()
    config["verification"].update(loaded.get("verification", {}))
    validate_aidev_config(config)
    return config


CONFIG = load_aidev_config()
RUNS_ROOT = Path(CONFIG["runs_root"]).expanduser()
WORKSPACE_ROOT = Path(CONFIG["workspace_root"]).expanduser()

load_dotenv(ENV_FILE)
os.environ.setdefault("ANTHROPIC_MODEL", str(CONFIG["model"]))
os.environ.setdefault("METAGPT_CONFIG", str(CONFIG_FILE))
os.environ.setdefault("METAGPT_PROJECT_ROOT", str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("aidev")


class Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, data: str) -> None:
        for stream in self.streams:
            stream.write(data)
            stream.flush()

    def flush(self) -> None:
        for stream in self.streams:
            stream.flush()


def add_run_log_handler(run_dir: Path) -> logging.Handler:
    handler = logging.FileHandler(run_dir / "run.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logging.getLogger().addHandler(handler)
    return handler


def slugify(text: str) -> str:
    slug = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", text.strip())[:40].strip("-")
    return slug or "task"


def create_run_dir(requirement: str, run_dir_arg: Optional[str] = None, output_root: Path = RUNS_ROOT) -> Path:
    if run_dir_arg:
        run_dir = Path(run_dir_arg).expanduser()
    else:
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        run_dir = output_root.expanduser() / f"{run_id}-{slugify(requirement)}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def read_summary(run_dir: Path) -> dict[str, str]:
    summary_path = run_dir / "summary.md"
    if not summary_path.exists():
        return {}
    summary: dict[str, str] = {}
    for line in summary_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.startswith("- ") or ":" not in line:
            continue
        key, value = line[2:].split(":", 1)
        summary[key.strip()] = value.strip().strip("`")
    return summary


def command_version(command: str, args: list[str] | None = None) -> str:
    args = args or ["--version"]
    if not command_available(command):
        return "not installed"
    result = subprocess.run([command, *args], capture_output=True, text=True)
    output = (result.stdout or result.stderr).strip().splitlines()
    return output[0] if output else "unknown"


def latest_run_dirs(limit: int = 10) -> list[Path]:
    if not RUNS_ROOT.exists():
        return []
    run_dirs = [path for path in RUNS_ROOT.iterdir() if path.is_dir()]
    return sorted(run_dirs, key=lambda path: path.stat().st_mtime, reverse=True)[:limit]


def print_status() -> None:
    print("# aidev status")
    print(f"config: {AIDEV_CONFIG_FILE}")
    print(f"version: {CONFIG['version']}")
    print(f"model: {os.environ.get('ANTHROPIC_MODEL', CONFIG['model'])}")
    print(f"runs_root: {RUNS_ROOT}")
    print(f"workspace_root: {WORKSPACE_ROOT}")
    print(f"engineer_count: {CONFIG['engineer_count']}")
    print(f"python: {sys.version.split()[0]}")
    print(f"node: {command_version('node')}")
    print(f"npm: {command_version('npm')}")
    print(f"go: {command_version('go', ['version'])}")
    print(f"cargo: {command_version('cargo', ['--version'])}")
    try:
        response = call_oneapi("ping", max_tokens=5, timeout=30, retries=1)
        print(f"oneapi: ok ({response[:40]})")
    except Exception as error:
        print(f"oneapi: failed ({error})")
    runs = latest_run_dirs(1)
    if runs:
        summary = read_summary(runs[0])
        print(f"latest_run: {runs[0]}")
        print(f"latest_status: {summary.get('Status', 'UNKNOWN')}")


def list_runs(limit: int) -> None:
    print("# aidev runs")
    for run_dir in latest_run_dirs(limit):
        summary = read_summary(run_dir)
        status = summary.get("Status", "UNKNOWN")
        phase = summary.get("Phase", "-")
        cost_time = summary.get("Cost time", "-")
        print(f"- [{status}] phase={phase} time={cost_time} path={run_dir}")


def infer_requirement(requirement: Optional[str], run_dir_arg: Optional[str], design_file: Optional[Path]) -> str:
    if requirement:
        return requirement
    if design_file:
        return f"实现技术设计文档：{design_file.expanduser().name}"
    if run_dir_arg:
        requirement_path = Path(run_dir_arg).expanduser() / "requirement.md"
        if requirement_path.exists():
            return requirement_path.read_text(encoding="utf-8", errors="ignore").strip() or f"继续运行：{Path(run_dir_arg).name}"
        return f"继续运行：{Path(run_dir_arg).name}"
    raise ValueError("缺少 requirement；请提供需求文本，或使用 --design-file / --run-dir")


def clean_paths(days: int, dry_run: bool, include_test: bool) -> None:
    cutoff = datetime.now() - timedelta(days=days)
    roots = [WORKSPACE_ROOT]
    if include_test:
        roots.extend([PROJECT_ROOT / "test-runs", PROJECT_ROOT / "target-smoke"])
    roots.append(RUNS_ROOT)
    print("# aidev clean")
    for root in roots:
        if not root.exists():
            continue
        for path in root.iterdir():
            if not path.is_dir():
                continue
            modified = datetime.fromtimestamp(path.stat().st_mtime)
            if modified >= cutoff:
                continue
            print(f"{'would remove' if dry_run else 'remove'}: {path}")
            if not dry_run:
                shutil.rmtree(path)


def get_required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"缺少环境变量：{name}，请检查 {ENV_FILE}")
    return value


def call_oneapi(prompt: str, max_tokens: int = 4096, timeout: int = 180, retries: int = 4) -> str:
    api_key = get_required_env("ANTHROPIC_API_KEY")
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "https://oneapi-comate.baidu-int.com").rstrip("/")
    model = os.environ.get("ANTHROPIC_MODEL", "Claude Sonnet 4.6")
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    data = None
    for attempt in range(retries + 1):
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
            break
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", "replace")[:1000]
            if error.code == 429 and attempt < retries:
                sleep_seconds = min(60, 5 * (2 ** attempt))
                logger.warning("OneAPI 429 限流，%.0fs 后重试：%s", sleep_seconds, body)
                time.sleep(sleep_seconds)
                continue
            raise RuntimeError(f"OneAPI HTTP {error.code}: {body}") from error
        except urllib.error.URLError as error:
            if attempt < retries:
                sleep_seconds = min(30, 3 * (2 ** attempt))
                logger.warning("OneAPI 请求失败，%.0fs 后重试：%s", sleep_seconds, error)
                time.sleep(sleep_seconds)
                continue
            raise RuntimeError(f"OneAPI 请求失败：{error}") from error

    if data is None:
        raise RuntimeError("OneAPI 请求失败：未获得响应")
    content = data.get("content", [])
    text_blocks = [block.get("text", "") for block in content if isinstance(block, dict)]
    result = "\n".join(block for block in text_blocks if block).strip()
    if not result:
        raise RuntimeError(f"OneAPI 响应中没有文本内容：{json.dumps(data, ensure_ascii=False)[:1000]}")
    return result


def sync_metagpt_config() -> None:
    api_key = get_required_env("ANTHROPIC_API_KEY")
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "https://oneapi-comate.baidu-int.com")
    model = os.environ.get("ANTHROPIC_MODEL", "Claude Sonnet 4.6")
    content = (
        "llm:\n"
        "  api_type: \"anthropic\"\n"
        f"  base_url: \"{base_url}\"\n"
        f"  api_key: \"{api_key}\"\n"
        f"  model: \"{model}\"\n"
        f"  max_token: {int(CONFIG['max_token'])}\n"
    )
    CONFIG_FILE.write_text(content, encoding="utf-8")
    home_config_dir = Path.home() / ".metagpt"
    home_config_dir.mkdir(parents=True, exist_ok=True)
    (home_config_dir / "config2.yaml").write_text(content, encoding="utf-8")


def collect_target_context(target_dir: Optional[Path]) -> str:
    if not target_dir:
        return ""
    target_dir = target_dir.expanduser()
    if not target_dir.exists():
        raise FileNotFoundError(f"目标项目目录不存在：{target_dir}")

    ignore_dirs = {".git", "node_modules", "__pycache__", ".pytest_cache", "target", "dist", "build"}
    tree_lines: list[str] = []
    for path in sorted(target_dir.rglob("*")):
        relative = path.relative_to(target_dir)
        if any(part in ignore_dirs for part in relative.parts):
            continue
        if len(relative.parts) > 3:
            continue
        suffix = "/" if path.is_dir() else ""
        tree_lines.append(f"- {relative}{suffix}")
        if len(tree_lines) >= 160:
            tree_lines.append("- ...")
            break

    key_files = [
        "README.md", "package.json", "pyproject.toml", "setup.cfg", "requirements.txt",
        "go.mod", "Cargo.toml", "Makefile",
    ]
    file_sections: list[str] = []
    for name in key_files:
        path = target_dir / name
        if path.exists() and path.is_file():
            content = path.read_text(encoding="utf-8", errors="ignore")[:4000]
            file_sections.append(f"## {name}\n```text\n{content}\n```")

    git_status = ""
    if (target_dir / ".git").exists():
        git_status = git_output(["status", "--short"], target_dir)

    return (
        f"\n\n## 目标项目上下文\n"
        f"目标目录：{target_dir}\n\n"
        f"### 文件树（截断）\n" + "\n".join(tree_lines) + "\n\n"
        f"### Git 状态\n```text\n{git_status or '(clean or not a git repo)'}\n```\n\n"
        f"### 关键文件\n" + "\n\n".join(file_sections)
    )


def build_effective_requirement(requirement: str, mode: str, target_dir: Optional[Path]) -> str:
    if mode == "new":
        return requirement
    context = collect_target_context(target_dir)
    return f"""
请在 patch 模式下修改已有项目，而不是生成无关的新项目。

用户需求：
{requirement}

要求：
1. 优先遵循目标项目现有技术栈、目录结构、命名风格和测试方式。
2. 只实现用户需求相关变更，避免重写整个项目。
3. 生成结果应能通过目标项目验证命令。
4. 如需新增文件，请说明放置路径。
{context}
""".strip()


def run_design_phase(requirement: str, run_dir: Path, mode: str = "new", target_dir: Optional[Path] = None) -> str:
    effective_requirement = build_effective_requirement(requirement, mode, target_dir)
    prompt = f"""
你是资深技术负责人。请根据需求生成可执行的技术设计文档，要求包含：
1. 目标与非目标
2. 用户故事和验收标准
3. 模块拆分与数据流
4. 接口/数据结构设计
5. 实施任务清单
6. 测试策略
7. 风险与回滚方案

需求：{effective_requirement}
""".strip()
    design = call_oneapi(prompt)
    (run_dir / "design.md").write_text(design, encoding="utf-8")
    return design


def strip_markdown_fence(content: str) -> str:
    lines = content.splitlines()
    if lines and lines[0].startswith("## Code:"):
        lines = lines[1:]
    while lines and not lines[0].strip():
        lines = lines[1:]
    if lines and re.fullmatch(r"```[a-zA-Z0-9_+-]*", lines[0].strip()):
        lines = lines[1:]
        if lines and lines[0].startswith("## "):
            lines = lines[1:]
        while lines and not lines[0].strip():
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
    return "\n".join(lines).rstrip() + "\n"


def sanitize_generated_files(output_dir: Path) -> list[Path]:
    sanitized: list[Path] = []
    for path in output_dir.rglob("*"):
        if not path.is_file() or path.suffix not in {".py", ".toml", ".cfg", ".txt", ".md"}:
            continue
        if path.name in {"requirement.md", "summary.md", "verification.md", "repair.md", "target_diff.md", "run.log"}:
            continue
        if any(part in {"docs", "resources"} for part in path.parts):
            continue
        content = path.read_text(encoding="utf-8", errors="ignore")
        cleaned = strip_markdown_fence(content)
        if cleaned != content:
            path.write_text(cleaned, encoding="utf-8")
            sanitized.append(path)
    return sanitized


def find_python_project_dirs(root: Path) -> list[Path]:
    candidates: set[Path] = set()
    for marker in ["pyproject.toml", "setup.cfg", "setup.py", "requirements.txt", "main.py", "package.json", "go.mod", "Cargo.toml"]:
        for path in root.rglob(marker):
            if any(part in {"docs", "resources", "test_outputs"} for part in path.parts):
                continue
            candidates.add(path.parent)
    for tests_dir in root.rglob("tests"):
        if tests_dir.is_dir() and any(tests_dir.glob("test_*.py")):
            candidates.add(tests_dir.parent)
    if not candidates:
        candidates.add(root)
    return sorted(candidates, key=lambda path: (len(path.parts), str(path)))


def verification_status(report_path: Path) -> str:
    if not report_path.exists():
        return "UNKNOWN"
    for line in report_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = re.fullmatch(r"- Status:\s*(PASSED|FAILED|SKIPPED|UNKNOWN|PENDING)", line.strip())
        if match:
            return match.group(1)
    return "UNKNOWN"


def smoke_commands_for_project(project_dir: Path) -> list[list[str]]:
    commands: list[list[str]] = []
    main_py = project_dir / "main.py"
    if main_py.exists():
        commands.append([sys.executable, str(main_py), "--help"])

    pyproject = project_dir / "pyproject.toml"
    if pyproject.exists():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            scripts = data.get("project", {}).get("scripts", {})
            for name, target in list(scripts.items())[:3]:
                if ":" not in target:
                    continue
                module, function = target.split(":", 1)
                code = (
                    "import sys; "
                    f"from {module} import {function}; "
                    f"sys.argv = ['{name}', '--help']; "
                    f"{function}()"
                )
                commands.append([sys.executable, "-c", code])
        except Exception as error:
            logger.warning("读取 pyproject.toml 失败：%s", error)
    return commands


def command_available(command: str) -> bool:
    return shutil.which(command) is not None


def run_check_command(command: list[str], cwd: Path, timeout: int = 120) -> tuple[str, str]:
    if not command_available(command[0]):
        if install_missing_tool(command[0]) and command_available(command[0]):
            logger.info("命令 `%s` 自动安装成功", command[0])
        else:
            return "SKIPPED", f"command not found: {command[0]}"
    try:
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        return "FAIL", f"timeout after {timeout}s: {' '.join(command)}\n{error}"
    output = "\n".join(part for part in [result.stdout, result.stderr] if part.strip()).strip()
    return ("PASS" if result.returncode == 0 else "FAIL"), output


def configured_check(language: str) -> tuple[list[str], int]:
    settings = CONFIG.get("verification", {}).get(language, {})
    command = settings.get("command", DEFAULT_CONFIG["verification"][language]["command"])
    timeout = int(settings.get("timeout", DEFAULT_CONFIG["verification"][language]["timeout"]))
    return list(command), timeout


def install_missing_tool(command: str) -> bool:
    verification_config = CONFIG.get("verification", {})
    if not verification_config.get("auto_install_tools", True):
        return False
    package_map = {
        "npm": verification_config.get("node", {}).get("conda_package", "nodejs"),
        "node": verification_config.get("node", {}).get("conda_package", "nodejs"),
        "go": verification_config.get("go", {}).get("conda_package", "go"),
        "cargo": verification_config.get("rust", {}).get("conda_package", "rust"),
    }
    package = package_map.get(command)
    if not package:
        return False
    logger.info("检测到缺失命令 `%s`，尝试安装 conda 包 `%s`", command, package)
    result = subprocess.run(["conda", "install", "-n", "aidev", package, "-y"], capture_output=True, text=True)
    if result.returncode != 0:
        logger.warning("自动安装 `%s` 失败：%s", package, result.stderr.strip()[:1000])
        return False
    return True


def language_checks_for_project(project_dir: Path) -> list[tuple[str, list[str], int]]:
    checks: list[tuple[str, list[str], int]] = []
    package_json = project_dir / "package.json"
    if package_json.exists():
        try:
            json.loads(package_json.read_text(encoding="utf-8"))
            command, timeout = configured_check("node")
            checks.append(("Node test", command, timeout))
        except json.JSONDecodeError as error:
            checks.append(("Node package.json", ["__invalid_json__", str(error)], 0))
    if (project_dir / "go.mod").exists():
        command, timeout = configured_check("go")
        checks.append(("Go test", command, timeout))
    if (project_dir / "Cargo.toml").exists():
        command, timeout = configured_check("rust")
        checks.append(("Rust test", command, timeout))
    return checks


def verify_python_file(path: Path, cwd: Path) -> tuple[bool, str]:
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", str(path)],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    output = "\n".join(part for part in [result.stdout, result.stderr] if part.strip()).strip()
    return result.returncode == 0, output


def repair_truncated_python(path: Path, error: str) -> bool:
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    line_match = re.search(r"line (\d+)", error)
    if line_match:
        line_no = int(line_match.group(1))
        if line_no >= max(1, len(lines) - 5):
            bad_index = max(0, line_no - 1)
            if bad_index < len(lines):
                candidate = lines[bad_index].strip()
                if candidate.startswith(("def ", "class ")) and ":" not in candidate:
                    path.write_text("\n".join(lines[:bad_index]).rstrip() + "\n", encoding="utf-8")
                    logger.info("已本地截断返修文件：%s", path)
                    return True
    stripped_indexes = [index for index, line in enumerate(lines) if line.strip()]
    if stripped_indexes:
        last_index = stripped_indexes[-1]
        if lines[last_index].rstrip().endswith(":"):
            indent = re.match(r"\s*", lines[last_index]).group(0) + "    "
            lines.append(f"{indent}pass")
            path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
            logger.info("已补全空代码块：%s", path)
            return True
    return False


def repair_file_with_oneapi(path: Path, error: str, project_root: Path) -> None:
    if path.suffix == ".py" and repair_truncated_python(path, error):
        return
    file_content = path.read_text(encoding="utf-8", errors="ignore")
    nearby_files = []
    for candidate in sorted(project_root.rglob("*.py")):
        if candidate == path or any(part in {"docs", "resources"} for part in candidate.parts):
            continue
        try:
            nearby_files.append(f"# {candidate.relative_to(project_root)}\n{candidate.read_text(encoding='utf-8', errors='ignore')[:3000]}")
        except OSError:
            continue
        if len(nearby_files) >= 4:
            break

    prompt = f"""
你是 Python 修复助手。请修复下面这个文件，使其成为完整、可解析、可运行的 Python 文件。

要求：
1. 只输出修复后的完整文件内容。
2. 不要输出 Markdown 标题、解释文字或代码围栏。
3. 保留原需求语义和测试意图。
4. 如果文件明显截断，请补全缺失的函数/类/文件结尾。

项目根目录：{project_root}
目标文件：{path.relative_to(project_root)}
错误信息：
{error}

当前文件内容：
{file_content}

相邻文件上下文：
{chr(10).join(nearby_files)}
""".strip()
    repaired = strip_markdown_fence(call_oneapi(prompt, max_tokens=4096, timeout=240))
    path.write_text(repaired, encoding="utf-8")
    logger.info("已自动返修文件：%s", path)


def copy_tree_excluding(source_dir: Path, destination_dir: Path) -> None:
    ignore_names = {".git", "node_modules", "__pycache__", ".pytest_cache", "target", "dist", "build", "htmlcov"}
    if destination_dir.exists():
        shutil.rmtree(destination_dir)
    destination_dir.mkdir(parents=True, exist_ok=True)
    for source_path in source_dir.rglob("*"):
        relative_path = source_path.relative_to(source_dir)
        if any(part in ignore_names for part in relative_path.parts):
            continue
        destination = destination_dir / relative_path
        if source_path.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        elif source_path.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, destination)


def parse_file_blocks(content: str) -> dict[str, str]:
    pattern = re.compile(r"^---FILE:\s*(.+?)\s*---\n(.*?)^---END FILE---\s*$", re.MULTILINE | re.DOTALL)
    files: dict[str, str] = {}
    for match in pattern.finditer(content):
        relative_path = match.group(1).strip()
        file_content = strip_markdown_fence(match.group(2))
        if relative_path and not relative_path.startswith("/") and ".." not in Path(relative_path).parts:
            files[relative_path] = file_content
    return files


def run_patch_apply_phase(design_doc: str, run_dir: Path, target_dir: Path) -> Path:
    target_dir = target_dir.expanduser()
    if not target_dir.exists():
        raise FileNotFoundError(f"目标项目目录不存在：{target_dir}")
    output_dir = run_dir / "metagpt_output" / "patch_apply"
    copy_tree_excluding(target_dir, output_dir)
    context = collect_target_context(target_dir)
    prompt = f"""
你是补丁生成助手。请根据技术设计文档修改已有项目。

必须严格按以下格式输出一个或多个完整文件块，不要输出解释文字：
---FILE: relative/path/from/project/root---
完整文件内容
---END FILE---

要求：
1. 只输出需要新增或修改的文件。
2. 每个文件块必须包含完整文件内容，不要只输出 diff。
3. 不要使用 Markdown 代码围栏。
4. 保留目标项目中与需求无关的现有内容。
5. 文件路径必须是相对目标项目根目录的路径。

技术设计文档：
{design_doc}

{context}
""".strip()
    response = call_oneapi(prompt, max_tokens=int(CONFIG["max_token"]), timeout=300)
    file_blocks = parse_file_blocks(response)
    if not file_blocks:
        (run_dir / "patch_response.txt").write_text(response, encoding="utf-8")
        raise RuntimeError(f"模型未返回可解析的 FILE 块，原始响应已保存：{run_dir / 'patch_response.txt'}")
    for relative_path, file_content in file_blocks.items():
        destination = output_dir / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(file_content, encoding="utf-8")
        logger.info("已应用 patch 文件：%s", destination)
    return output_dir


def run_repair(run_dir: Path) -> Path:
    output_roots = [path for path in (run_dir / "metagpt_output").glob("*") if path.is_dir()]
    if not output_roots:
        output_roots = [run_dir]

    repaired_files: list[Path] = []
    for output_root in output_roots:
        sanitize_generated_files(output_root)
        py_files = [path for path in output_root.rglob("*.py") if not any(part in {"docs", "resources"} for part in path.parts)]
        for path in py_files:
            ok, error = verify_python_file(path, output_root)
            if ok:
                continue
            repair_file_with_oneapi(path, error, output_root)
            repaired_files.append(path)

    report = run_verification(run_dir)
    repair_report = run_dir / "repair.md"
    lines = ["# Repair", "", f"- Repaired files: {len(repaired_files)}"]
    for path in repaired_files:
        lines.append(f"  - `{path}`")
    lines.append(f"- Verification: `{report}`")
    repair_report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("返修报告已生成：%s", repair_report)
    return repair_report


def write_meta_summary(run_dir: Path) -> Optional[Path]:
    output_roots = [path for path in (run_dir / "metagpt_output").glob("*") if path.is_dir()]
    if not output_roots:
        return None
    lines = ["# MetaGPT Artifacts", ""]
    for output_root in output_roots:
        lines.append(f"## `{output_root.name}`")
        for title, glob_pattern in [
            ("PRD", "docs/prd/*"),
            ("System Design", "docs/system_design/*"),
            ("Tasks", "docs/task/*"),
            ("Resource PRD", "resources/prd/*"),
            ("Resource System Design", "resources/system_design/*"),
            ("Sequence Flow", "resources/seq_flow/*"),
            ("Data/API Design", "resources/data_api_design/*"),
        ]:
            files = sorted(path for path in output_root.glob(glob_pattern) if path.is_file())
            if not files:
                continue
            lines.append(f"### {title}")
            for path in files[:20]:
                lines.append(f"- `{path.relative_to(output_root)}`")
            lines.append("")
        project_root = final_project_root_from_output(output_root)
        if project_root:
            lines.append("### Generated Project")
            lines.append(f"- `{project_root.relative_to(output_root)}`")
            lines.append("")
    report_path = run_dir / "meta_summary.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("MetaGPT 产物索引已生成：%s", report_path)
    return report_path


def final_project_root_from_output(output_root: Path) -> Optional[Path]:
    project_dirs = find_python_project_dirs(output_root)
    if project_dirs:
        for project_dir in project_dirs:
            if any((project_dir / marker).exists() for marker in ["pyproject.toml", "setup.cfg", "setup.py", "main.py", "package.json", "go.mod", "Cargo.toml"]):
                return project_dir
        return project_dirs[0]
    return None


def final_project_root(run_dir: Path) -> Optional[Path]:
    output_roots = [path for path in (run_dir / "metagpt_output").glob("*") if path.is_dir()]
    search_roots = output_roots or [run_dir]
    for search_root in search_roots:
        project_root = final_project_root_from_output(search_root)
        if project_root:
            return project_root
    return None


def git_output(args: list[str], cwd: Path) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        return result.stderr.strip()
    return result.stdout.strip()


def git_check(args: list[str], cwd: Path) -> tuple[bool, str]:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    output = "\n".join(part for part in [result.stdout, result.stderr] if part.strip()).strip()
    return result.returncode == 0, output


def write_preview_target_report(run_dir: Path, target_dir: Path) -> Path:
    source_dir = final_project_root(run_dir)
    if not source_dir:
        raise RuntimeError(f"未找到可预览的项目根目录：{run_dir}")
    target_dir = target_dir.expanduser()
    is_git_repo = (target_dir / ".git").exists()
    git_status = git_output(["status", "--short"], target_dir) if is_git_repo else ""
    candidate_files = [
        path.relative_to(source_dir)
        for path in source_dir.rglob("*")
        if path.is_file() and not any(part in {".git", "node_modules", "__pycache__", ".pytest_cache", "target", "dist", "build", "htmlcov"} for part in path.relative_to(source_dir).parts)
    ]
    report_path = run_dir / "target_diff.md"
    lines = [
        "# Target Diff",
        "",
        f"- Source: `{source_dir}`",
        f"- Target: `{target_dir}`",
        "- Status: PREVIEW_ONLY",
        f"- Candidate files: {len(candidate_files)}",
        f"- Git repo: {'yes' if is_git_repo else 'no'}",
        "",
        "## Candidate Files",
    ]
    lines += [f"- `{path}`" for path in sorted(candidate_files)[:200]]
    if is_git_repo:
        lines += ["", "## Git Status", "```text", git_status or "(clean)", "```"]
    lines += [
        "",
        "未写入目标目录。确认无误后，去掉 `--preview-patch` 再执行一次以落盘。",
    ]
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("预览报告已生成：%s", report_path)
    return report_path


def copy_project_to_target(run_dir: Path, target_dir: Path, allow_dirty_target: bool) -> Path:
    source_dir = final_project_root(run_dir)
    if not source_dir:
        raise RuntimeError(f"未找到可落盘的项目根目录：{run_dir}")

    target_dir = target_dir.expanduser()
    target_dir.mkdir(parents=True, exist_ok=True)
    is_git_repo = (target_dir / ".git").exists()
    git_status_before = git_output(["status", "--short"], target_dir) if is_git_repo else ""
    if is_git_repo and git_status_before and not allow_dirty_target:
        report_path = run_dir / "target_diff.md"
        report_path.write_text(
            "# Target Diff\n\n"
            f"- Source: `{source_dir}`\n"
            f"- Target: `{target_dir}`\n"
            "- Status: BLOCKED_DIRTY_TARGET\n\n"
            "## Git Status Before\n"
            "```text\n"
            f"{git_status_before}\n"
            "```\n\n"
            "目标目录存在未提交改动。为避免覆盖，请先提交/暂存/清理，或显式添加 `--allow-dirty-target`。\n",
            encoding="utf-8",
        )
        raise RuntimeError(f"目标 Git 目录存在未提交改动，已拒绝覆盖：{target_dir}。详情见 {report_path}")
    before_files = {path.relative_to(target_dir) for path in target_dir.rglob("*") if path.is_file()}

    ignore_names = {"__pycache__", ".pytest_cache", "htmlcov"}
    copied_files: list[Path] = []
    for source_path in source_dir.rglob("*"):
        if not source_path.is_file() or any(part in ignore_names for part in source_path.parts):
            continue
        relative_path = source_path.relative_to(source_dir)
        destination = target_dir / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination)
        copied_files.append(relative_path)

    after_files = {path.relative_to(target_dir) for path in target_dir.rglob("*") if path.is_file()}
    new_files = sorted(after_files - before_files)
    touched_files = sorted(set(copied_files))
    report_path = run_dir / "target_diff.md"
    lines = [
        "# Target Diff",
        "",
        f"- Source: `{source_dir}`",
        f"- Target: `{target_dir}`",
        f"- Copied files: {len(copied_files)}",
        f"- New files: {len(new_files)}",
        f"- Git repo: {'yes' if is_git_repo else 'no'}",
        "",
        "## Copied Files",
    ]
    lines += [f"- `{path}`" for path in touched_files[:200]]
    if new_files:
        lines += ["", "## New Files"]
        lines += [f"- `{path}`" for path in new_files[:200]]
    if is_git_repo:
        git_status_after = git_output(["status", "--short"], target_dir)
        git_diff_stat = git_output(["diff", "--stat"], target_dir)
        git_diff = git_output(["diff", "--", *[str(path) for path in touched_files[:100]]], target_dir)
        diff_check_ok, diff_check_output = git_check(["diff", "--check"], target_dir)
        lines += ["", "## Git Status Before", "```text", git_status_before or "(clean)", "```"]
        lines += ["", "## Git Status After", "```text", git_status_after or "(clean)", "```"]
        lines += ["", "## Git Diff Check", f"- Status: {'PASS' if diff_check_ok else 'FAIL'}"]
        if diff_check_output:
            lines += ["```text", diff_check_output[:4000], "```"]
        lines += ["", "## Git Diff Stat", "```text", git_diff_stat or "(no tracked-file diff)", "```"]
        if git_diff:
            lines += ["", "## Git Diff Preview", "```diff", git_diff[:12000], "```"]
        lines += [
            "",
            "## Suggested Commands",
            "```bash",
            "git diff --check",
            "git status --short",
            "git diff --stat",
            "git diff",
            "git add .",
            "```",
        ]
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("目标目录已更新：%s", target_dir)
    logger.info("目标目录变更报告：%s", report_path)
    return report_path


def run_verification(run_dir: Path) -> Path:
    report_path = run_dir / "verification.md"
    output_roots = [path for path in (run_dir / "metagpt_output").glob("*") if path.is_dir()]
    if not output_roots:
        output_roots = [run_dir]

    checks: list[bool] = []
    skipped_checks = 0
    sections = ["# Verification", "", "- Status: PENDING", ""]
    for output_root in output_roots:
        sections.append(f"## `{output_root}`")
        sanitized = sanitize_generated_files(output_root)
        sections.append(f"- Sanitized files: {len(sanitized)}")
        for path in sanitized[:20]:
            sections.append(f"  - `{path.relative_to(output_root)}`")

        project_dirs = find_python_project_dirs(output_root)
        if project_dirs:
            sections.append("- Project roots:")
            for project_dir in project_dirs[:5]:
                sections.append(f"  - `{project_dir.relative_to(output_root)}`")

        py_files = [path for path in output_root.rglob("*.py") if not any(part in {"docs", "resources"} for part in path.parts)]
        if py_files:
            compile_cmd = [sys.executable, "-m", "py_compile", *[str(path) for path in py_files]]
            compile_result = subprocess.run(compile_cmd, cwd=output_root, capture_output=True, text=True)
            compile_ok = compile_result.returncode == 0
            checks.append(compile_ok)
            sections.append(f"- `py_compile`: {'PASS' if compile_ok else 'FAIL'}")
            if compile_result.stdout.strip():
                sections.append("```text\n" + compile_result.stdout.strip()[:4000] + "\n```")
            if compile_result.stderr.strip():
                sections.append("```text\n" + compile_result.stderr.strip()[:4000] + "\n```")

        for project_dir in project_dirs[:3]:
            test_dir = project_dir / "tests"
            if test_dir.is_dir() and any(test_dir.glob("test_*.py")):
                pytest_result = subprocess.run(
                    [sys.executable, "-m", "pytest", "tests", "-q", "-o", "addopts="],
                    cwd=project_dir,
                    capture_output=True,
                    text=True,
                )
                pytest_ok = pytest_result.returncode == 0
                checks.append(pytest_ok)
                sections.append(f"- `pytest` in `{project_dir.relative_to(output_root)}`: {'PASS' if pytest_ok else 'FAIL'}")
                output = "\n".join(part for part in [pytest_result.stdout, pytest_result.stderr] if part.strip()).strip()
                if output:
                    sections.append("```text\n" + output[:8000] + "\n```")

            smoke_commands = smoke_commands_for_project(project_dir)
            for smoke_command in smoke_commands[:2]:
                smoke_result = subprocess.run(
                    smoke_command,
                    cwd=project_dir,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                smoke_ok = smoke_result.returncode in {0, 2}
                checks.append(smoke_ok)
                smoke_display = " ".join(smoke_command[1:])
                sections.append(f"- CLI smoke in `{project_dir.relative_to(output_root)}`: {'PASS' if smoke_ok else 'FAIL'}")
                sections.append(f"  - `{smoke_display}`")
                smoke_output = "\n".join(part for part in [smoke_result.stdout, smoke_result.stderr] if part.strip()).strip()
                if smoke_output:
                    sections.append("```text\n" + smoke_output[:3000] + "\n```")

            for check_name, command, timeout in language_checks_for_project(project_dir):
                if command[0] == "__invalid_json__":
                    checks.append(False)
                    sections.append(f"- `{check_name}` in `{project_dir.relative_to(output_root)}`: FAIL")
                    sections.append("```text\n" + command[1][:3000] + "\n```")
                    continue
                status, output = run_check_command(command, project_dir, timeout=timeout)
                if status == "SKIPPED":
                    skipped_checks += 1
                else:
                    checks.append(status == "PASS")
                sections.append(f"- `{check_name}` in `{project_dir.relative_to(output_root)}`: {status}")
                sections.append(f"  - `{' '.join(command)}`")
                if output:
                    sections.append("```text\n" + output[:8000] + "\n```")
        sections.append("")

    status = "PASSED" if checks and all(checks) else "FAILED" if checks else "SKIPPED" if skipped_checks else "UNKNOWN"
    sections[2] = f"- Status: {status}"
    report_path.write_text("\n".join(sections), encoding="utf-8")
    logger.info("验证报告已生成：%s", report_path)
    return report_path


async def run_implementation_phase(
    design_doc: str,
    run_dir: Path,
    budget: float,
    rounds: int,
    archive_workspace: bool,
    mode: str,
    target_dir: Optional[Path],
) -> Optional[Path]:
    sync_metagpt_config()
    try:
        from metagpt.roles import Architect, Engineer, ProductManager, ProjectManager, QaEngineer
        from metagpt.team import Team
    except ImportError as error:
        raise RuntimeError("MetaGPT 未安装或版本不兼容，请先运行：/Users/frank/work/aidev/install.sh") from error

    workspace_root = WORKSPACE_ROOT
    before_dirs = {path.resolve() for path in workspace_root.iterdir()} if workspace_root.exists() else set()

    original_cwd = Path.cwd()
    os.chdir(run_dir)
    try:
        team = Team()
        engineer_count = int(CONFIG["engineer_count"])
        team.hire([ProductManager(), Architect(), ProjectManager(), Engineer(n_borg=engineer_count), QaEngineer()])
        team.invest(budget)
        implementation_prompt = f"""
请严格根据以下技术设计文档实现代码。

当前模式：{mode}
目标目录：{target_dir if target_dir else '无'}

硬性要求：
1. 不要擅自改写验收标准、命令名称、参数名称、输出格式或文件清单。
2. 如果设计文档中要求 `add/sub/mul/div`，实现和测试必须使用这些字面命令，而不是替换成 `+/-/*//`。
3. 所有代码产物写入当前项目目录。
4. 生成可直接运行的代码和必要测试。
5. 输出代码时不要包含 Markdown 标题、文件名行或代码围栏，例如 `## Code:`、```python、```。
6. 测试文件要保持简洁，避免生成超长或被截断的测试文件。

技术设计文档：

{design_doc}
""".strip()
        team.run_project(implementation_prompt)
        await team.run(n_round=rounds)
    finally:
        os.chdir(original_cwd)

    if workspace_root.exists():
        candidate_dirs = [path for path in workspace_root.iterdir() if path.is_dir() and path.resolve() not in before_dirs]
        if not candidate_dirs:
            candidate_dirs = [path for path in workspace_root.iterdir() if path.is_dir()]
        if candidate_dirs:
            latest_dir = max(candidate_dirs, key=lambda path: path.stat().st_mtime)
            output_dir = run_dir / "metagpt_output" / latest_dir.name
            if output_dir.exists():
                shutil.rmtree(output_dir)
            shutil.copytree(latest_dir, output_dir)
            logger.info("MetaGPT 产物已复制到：%s", output_dir)
            if archive_workspace:
                shutil.rmtree(latest_dir)
                logger.info("已清理 MetaGPT 原始 workspace：%s", latest_dir)
            return output_dir
    return None


async def run_pipeline(
    requirement: str,
    phase: str,
    run_dir_arg: Optional[str],
    budget: float,
    rounds: int,
    verify: bool,
    output_root: Path,
    archive_workspace: bool,
    target_dir: Optional[Path],
    allow_dirty_target: bool,
    preview_patch: bool,
    mode: str,
    auto_continue: bool,
    max_repair_attempts: int,
    design_file: Optional[Path],
) -> Path:
    started_at = time.monotonic()
    run_dir = create_run_dir(requirement, run_dir_arg, output_root)
    log_handler = add_run_log_handler(run_dir)
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    with (run_dir / "run.log").open("a", encoding="utf-8") as log_file:
        sys.stdout = Tee(original_stdout, log_file)
        sys.stderr = Tee(original_stderr, log_file)
        try:
            logger.info("运行目录：%s", run_dir)
            (run_dir / "requirement.md").write_text(requirement, encoding="utf-8")

            design_path = run_dir / "design.md"
            design = ""
            if mode == "patch" and not target_dir:
                raise ValueError("patch 模式必须提供 --target-dir")

            if design_file:
                source_design = design_file.expanduser()
                if not source_design.exists():
                    raise FileNotFoundError(f"技术设计文档不存在：{source_design}")
                design = source_design.read_text(encoding="utf-8")
                design_path.write_text(design, encoding="utf-8")
                logger.info("已使用外部技术设计文档：%s", source_design)
            elif phase in {"design", "all"}:
                design = await asyncio.wait_for(
                    asyncio.to_thread(run_design_phase, requirement, run_dir, mode, target_dir), timeout=300
                )
                logger.info("设计阶段完成：%s", design_path)

            verification_report = None
            if phase in {"implement", "all"}:
                if not design:
                    if not design_path.exists():
                        raise FileNotFoundError(f"缺少设计文档：{design_path}")
                    design = design_path.read_text(encoding="utf-8")
                if mode == "patch":
                    if not target_dir:
                        raise ValueError("patch 模式必须提供 --target-dir")
                    run_patch_apply_phase(design, run_dir, target_dir)
                else:
                    await asyncio.wait_for(
                        run_implementation_phase(design, run_dir, budget, rounds, archive_workspace, mode, target_dir),
                        timeout=900,
                    )
                logger.info("实现阶段完成：%s", run_dir)
                if verify:
                    verification_report = run_verification(run_dir)

            if phase == "verify":
                verification_report = run_verification(run_dir)

            repair_report = None
            if phase == "repair":
                repair_report = run_repair(run_dir)
                verification_report = run_dir / "verification.md"

            repair_attempts = 0
            last_verification_content = ""
            while (
                auto_continue
                and verification_report
                and verification_status(verification_report) == "FAILED"
                and repair_attempts < max_repair_attempts
            ):
                current_content = verification_report.read_text(encoding="utf-8", errors="ignore")
                if current_content == last_verification_content and repair_attempts > 0:
                    logger.warning("验证结果没有改善，停止自动返修")
                    break
                last_verification_content = current_content
                repair_attempts += 1
                logger.info("自动返修第 %d/%d 次", repair_attempts, max_repair_attempts)
                repair_report = run_repair(run_dir)
                verification_report = run_dir / "verification.md"
                if verification_status(verification_report) == "PASSED":
                    logger.info("自动返修后验证通过")
                    break

            meta_summary = write_meta_summary(run_dir)

            target_report = None
            if target_dir and verification_report and verification_status(verification_report) == "PASSED":
                if preview_patch:
                    target_report = write_preview_target_report(run_dir, target_dir)
                else:
                    target_report = copy_project_to_target(run_dir, target_dir, allow_dirty_target)
            elif target_dir:
                logger.warning("验证未通过或未运行，跳过 target-dir 落盘：%s", target_dir)

            summary_lines = [
                "# Run Summary",
                "",
                f"- Requirement: {requirement}",
                f"- Phase: {phase}",
                f"- Output: `{run_dir}`",
                f"- Log: `{run_dir / 'run.log'}`",
            ]
            if verification_report:
                summary_lines.insert(2, f"- Status: {verification_status(verification_report)}")
                summary_lines.append(f"- Verification: `{verification_report}`")
            if meta_summary:
                summary_lines.append(f"- MetaGPT Artifacts: `{meta_summary}`")
            if repair_report:
                summary_lines.append(f"- Repair: `{repair_report}`")
                summary_lines.append(f"- Repair attempts: {repair_attempts}")
            if target_report:
                summary_lines.append(f"- Target Diff: `{target_report}`")
            summary_lines.append(f"- Cost time: {time.monotonic() - started_at:.1f}s")
            summary = "\n".join(summary_lines) + "\n"
            (run_dir / "summary.md").write_text(summary, encoding="utf-8")
            logger.info("Pipeline 完成，总耗时 %.1fs", time.monotonic() - started_at)
            return run_dir
        finally:
            sys.stdout = original_stdout
            sys.stderr = original_stderr
            logging.getLogger().removeHandler(log_handler)
            log_handler.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Mac 本地 AI 开发流水线")
    parser.add_argument("requirement", nargs="?", help="要实现的需求")
    parser.add_argument("--status", action="store_true", help="查看配置、环境、工具链和最近运行状态")
    parser.add_argument("--list-runs", type=int, metavar="N", help="列出最近 N 次运行")
    parser.add_argument("--clean", action="store_true", help="清理旧运行目录和临时目录")
    parser.add_argument("--days", type=int, default=7, help="clean 清理多少天以前的目录，默认 7")
    parser.add_argument("--dry-run", action="store_true", help="clean 只预览不删除")
    parser.add_argument("--include-test", action="store_true", help="clean 同时处理 test-runs 和 target-smoke")
    parser.add_argument("--phase", choices=["design", "implement", "verify", "repair", "all"], default="all")
    parser.add_argument("--mode", choices=["new", "patch"], default="new", help="new 生成新项目；patch 修改已有项目")
    parser.add_argument("--run-dir", help="复用已有运行目录，常用于从 design.md 继续实现")
    parser.add_argument("--design-file", help="使用已有 Markdown 技术设计文档，直接写入 run/design.md")
    parser.add_argument("--budget", type=float, default=float(CONFIG["budget"]), help=f"MetaGPT 预算，默认 {CONFIG['budget']}")
    parser.add_argument("--rounds", type=int, default=int(CONFIG["rounds"]), help=f"MetaGPT 运行轮数，默认 {CONFIG['rounds']}")
    parser.add_argument("--model", help=f"本次运行覆盖 ANTHROPIC_MODEL，默认 {CONFIG['model']}")
    parser.add_argument("--output-root", default=str(RUNS_ROOT), help=f"运行目录根路径，默认 {RUNS_ROOT}")
    parser.add_argument("--archive-workspace", action="store_true", help="复制 MetaGPT 产物后清理 /Users/frank/work/aidev/workspace 原始目录")
    parser.add_argument("--target-dir", help="验证通过后将最终项目文件复制到指定目录")
    parser.add_argument("--preview-patch", action="store_true", help="只生成 target_diff 预览，不写入 target-dir")
    parser.add_argument("--allow-dirty-target", action="store_true", help="允许覆盖有未提交改动的 Git 目标目录")
    parser.add_argument("--auto-continue", action="store_true", help="验证失败时自动执行 repair，直到通过或达到上限")
    parser.add_argument("--max-repair-attempts", type=int, default=int(CONFIG["max_repair_attempts"]), help=f"自动返修最大次数，默认 {CONFIG['max_repair_attempts']}")
    parser.add_argument("--no-verify", action="store_true", help="实现阶段后不自动运行验证")
    args = parser.parse_args()
    if args.status:
        print_status()
        return
    if args.list_runs is not None:
        list_runs(args.list_runs)
        return
    if args.clean:
        clean_paths(args.days, args.dry_run, args.include_test)
        return
    design_file = Path(args.design_file) if args.design_file else None
    try:
        requirement = infer_requirement(args.requirement, args.run_dir, design_file)
    except ValueError as error:
        parser.error(str(error))
    if args.model:
        os.environ["ANTHROPIC_MODEL"] = args.model
    asyncio.run(
        run_pipeline(
            requirement,
            args.phase,
            args.run_dir,
            args.budget,
            args.rounds,
            not args.no_verify,
            Path(args.output_root),
            args.archive_workspace,
            Path(args.target_dir) if args.target_dir else None,
            args.allow_dirty_target,
            args.preview_patch,
            args.mode,
            args.auto_continue,
            args.max_repair_attempts,
            design_file,
        )
    )


if __name__ == "__main__":
    main()
