# 复杂设计文件示例：TaskFlow 本地任务管理 CLI

## 1. 目标

实现一个名为 `taskflow` 的 Python CLI 项目，用于本地任务管理。项目必须只依赖 Python 标准库和 pytest，不依赖 FastAPI、Typer、Click、Pydantic 等第三方运行时库。

核心能力：

- 任务增删改查
- JSON 文件持久化
- 标签、优先级、状态、截止日期管理
- 按状态/标签/优先级/关键词筛选
- 统计汇总
- CSV 导入导出
- 清晰错误处理
- 完整 pytest 测试

## 2. 非目标

- 不需要 Web 服务
- 不需要数据库
- 不需要并发同步
- 不需要联网
- 不需要彩色终端 UI

## 3. 技术约束

- Python 版本：3.11+
- 只使用标准库实现 CLI 和业务逻辑
- 测试使用 pytest
- CLI 使用 `argparse`
- 持久化使用 JSON 文件
- 日期使用 ISO 格式：`YYYY-MM-DD`
- 所有命令必须支持 `--db PATH` 指定数据文件，便于测试隔离

## 4. 项目结构

必须生成以下结构：

```text
taskflow/
├── pyproject.toml
├── README.md
├── taskflow/
│   ├── __init__.py
│   ├── cli.py
│   ├── models.py
│   ├── storage.py
│   ├── service.py
│   ├── reporting.py
│   └── errors.py
└── tests/
    ├── conftest.py
    ├── test_cli.py
    ├── test_service.py
    ├── test_storage.py
    └── test_reporting.py
```

## 5. 数据模型

### Task 字段

- `id`: int，自增主键，从 1 开始
- `title`: str，非空
- `description`: str，默认空字符串
- `status`: str，只允许 `todo` / `doing` / `done`
- `priority`: str，只允许 `low` / `medium` / `high`
- `tags`: list[str]，去重后排序
- `due`: optional str，必须是 `YYYY-MM-DD` 或空
- `created_at`: str，ISO datetime
- `updated_at`: str，ISO datetime

### JSON 存储格式

```json
{
  "next_id": 3,
  "tasks": [
    {
      "id": 1,
      "title": "Write tests",
      "description": "Add coverage",
      "status": "todo",
      "priority": "high",
      "tags": ["dev", "qa"],
      "due": "2026-06-01",
      "created_at": "2026-05-04T10:00:00",
      "updated_at": "2026-05-04T10:00:00"
    }
  ]
}
```

## 6. CLI 命令

入口脚本在 `pyproject.toml` 中定义：

```toml
[project.scripts]
taskflow = "taskflow.cli:main"
```

### 6.1 新增任务

```bash
taskflow --db tasks.json add "Write tests" --description "Add pytest" --priority high --tag dev --tag qa --due 2026-06-01
```

输出：

```text
Created task #1: Write tests
```

### 6.2 列出任务

```bash
taskflow --db tasks.json list
```

输出表格必须包含：`ID`、`Status`、`Priority`、`Due`、`Tags`、`Title`。

支持筛选：

```bash
taskflow --db tasks.json list --status todo --tag dev --priority high --query test
```

### 6.3 查看任务详情

```bash
taskflow --db tasks.json show 1
```

输出必须包含全部字段。

### 6.4 更新任务

```bash
taskflow --db tasks.json update 1 --title "Write more tests" --status doing --priority medium --tag backend --due 2026-06-02
```

输出：

```text
Updated task #1
```

### 6.5 完成任务

```bash
taskflow --db tasks.json done 1
```

输出：

```text
Completed task #1
```

### 6.6 删除任务

```bash
taskflow --db tasks.json delete 1
```

输出：

```text
Deleted task #1
```

### 6.7 统计

```bash
taskflow --db tasks.json stats
```

输出必须包含：

- `Total: N`
- `Todo: N`
- `Doing: N`
- `Done: N`
- `High priority: N`
- `Overdue: N`

### 6.8 CSV 导出

```bash
taskflow --db tasks.json export tasks.csv
```

输出：

```text
Exported N tasks to tasks.csv
```

### 6.9 CSV 导入

```bash
taskflow --db tasks.json import tasks.csv
```

输出：

```text
Imported N tasks from tasks.csv
```

CSV 字段：`title,description,status,priority,tags,due`，其中 `tags` 使用英文逗号分隔。

## 7. 错误处理

必须定义自定义异常：

- `TaskFlowError`
- `TaskNotFoundError`
- `ValidationError`
- `StorageError`

CLI 捕获 `TaskFlowError`，输出到 stderr，退出码为 1。

必须处理：

- 空标题
- 非法状态
- 非法优先级
- 非法日期格式
- 不存在的任务 ID
- JSON 文件损坏
- CSV 缺少必要列

## 8. 服务层要求

`service.py` 至少包含：

- `TaskService.add_task(...)`
- `TaskService.list_tasks(...)`
- `TaskService.get_task(task_id)`
- `TaskService.update_task(task_id, ...)`
- `TaskService.complete_task(task_id)`
- `TaskService.delete_task(task_id)`
- `TaskService.import_csv(path)`
- `TaskService.export_csv(path)`

## 9. 报表要求

`reporting.py` 至少包含：

- `format_task_table(tasks)`
- `format_task_detail(task)`
- `build_stats(tasks, today=None)`
- `format_stats(stats)`

## 10. 测试要求

必须包含 pytest 测试，覆盖：

- 新增任务并持久化
- 自增 ID
- 标签去重排序
- 非法状态/优先级/日期校验
- list 按 status/tag/priority/query 筛选
- show 不存在 ID 报错
- update 修改字段
- done 改为 done
- delete 删除任务
- stats 统计 total/status/high/overdue
- CSV export/import
- CLI add/list/done/stats 基本流程
- 损坏 JSON 报 StorageError

测试必须使用临时目录和 `--db`，不能读写用户真实目录。

## 11. README 要求

README 必须包含：

- 安装说明
- CLI 命令示例
- 数据文件说明
- 测试命令：`pytest`

## 12. 验收标准

- `python -m py_compile` 通过
- `pytest -q` 通过
- CLI help 可用
- `taskflow --db /tmp/tasks.json add "Demo"` 可创建任务
- 不生成 Markdown 代码围栏到源码文件
