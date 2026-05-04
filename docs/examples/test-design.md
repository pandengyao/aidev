# 技术设计文档：外部设计文件验证

## 1. 目标与非目标

### 目标
- 创建 `hello.py`。
- 执行 `python hello.py` 后输出 `hello design file`。
- 退出码为 0。

### 非目标
- 不需要测试文件。
- 不需要额外依赖。

## 2. 文件清单

- `hello.py`

## 3. 实现细节

`hello.py` 内容应为：

```python
print("hello design file")
```

## 4. 验收标准

- `hello.py` 文件存在。
- 执行后 stdout 精确输出 `hello design file\n`。
