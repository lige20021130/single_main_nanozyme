# GUI可靠性审查与关键Bug修复

## 更新时间
2026-04-28 02:30

## 更新类型
- Bug 修复

## 背景
GUI界面存在两个关键可靠性问题：
1. 服务器启动按钮点击后长时间停留在"启动中"状态，无法完成启动
2. 大模型连接测试报错 "RuntimeError: main thread is not in main loop"
3. 提取过程的日志未完整显示在GUI中
4. 大模型信息显示不完整

## 改动内容

### 1. 服务器启动停滞修复（pdf_basic_gui.py）

**根本原因**：旧代码使用 `stdout` 逐行读取来检测 "Uvicorn running on" 字符串判断服务器就绪。但如果服务器输出不包含该字符串（如输出被缓冲、编码问题、或服务器启动失败），就会永远停在"启动中"状态。

**修复方案**：改用 HTTP 健康检查（`urllib.request.urlopen("http://localhost:5002/health")`）判断服务器就绪，每秒轮询一次，最多60次（60秒超时）。

**新逻辑**：
- `start_server()` → 启动后台线程 `_server_worker()`
- `_server_worker()` → 启动进程 + 独立线程读取stdout + HTTP健康检查轮询
- 健康检查成功 → `_on_server_ready()` 更新状态
- 进程退出 → `_on_server_stopped()` 更新状态
- 超时 → `_on_server_timeout()` 更新状态
- 异常 → `_on_server_error()` 更新状态

**关键改进**：
- 不再依赖 stdout 字符串匹配，改用 HTTP 接口检查
- 超时检测：60秒后自动报告超时
- 进程异常退出检测：每秒检查 `poll()` 返回值
- 所有UI更新通过 `self.root.after(0, ...)` 调度到主线程

### 2. 大模型连接测试 main thread 错误修复（pdf_basic_gui.py）

**根本原因**：旧代码在 `test_worker` 函数内部定义 `update_ui` 闭包，然后通过 `self.root.after(0, update_ui)` 调度到主线程。但 `asyncio.run()` 创建的新事件循环可能干扰 tkinter 的事件循环，导致 `self.root.after()` 抛出 "main thread is not in main loop"。

**修复方案**：
- 将 `test_worker` 从嵌套函数改为类方法 `_test_model_worker`
- 不再使用闭包 `update_ui`，而是每个UI更新单独通过 `self.root.after(0, lambda: ...)` 调度
- 使用 lambda 捕获变量值（而非闭包引用），避免变量在异步执行期间被修改
- 测试条件从 `or` 改为 `and`（任一配置存在即可测试）

### 3. 全流程提取日志显示增强（pdf_basic_gui.py）

**问题**：提取管线的日志（`single_main_nanozyme_extractor` 等）未显示在GUI中。

**修复**：
- 确保所有子模块logger级别设为INFO
- 新增logger名称列表：`single_main_nanozyme_extractor`, `nanozyme_preprocessor_midjson`, `extraction_pipeline`, `llm_extractor`, `vlm_extractor`, `api_client`, `RuleExtractor`, `TableProcessor`
- 统一设置root logger级别为INFO（不再依赖 `LOGGING_SETUP_AVAILABLE` 条件）

### 4. ttk Label兼容性修复（pdf_basic_gui.py）

**问题**：ttk Label 使用 `fg=` 参数会报错，应使用 `foreground=`。

**修复**：全局替换所有 `fg=` 为 `foreground=`（在 `.config()` 调用中）。

## 未改动内容
- `single_main_nanozyme_extractor.py`：未修改
- `nanozyme_preprocessor_midjson.py`：未修改
- `vlm_extractor.py`：未修改
- `extraction_pipeline.py`：未修改
- `config.yaml`：未修改
- `test_single_main_nanozyme.py`：未修改

## 验证方式
- 32个单元测试全部通过
- GUI模块导入成功
- 服务器启动逻辑：HTTP健康检查替代stdout字符串匹配
- 大模型测试：lambda调度替代闭包调度

## 风险与后续
- **服务器端口硬编码**：当前硬编码为5002端口，如需更改需修改多处
- **_ensure_server 在主线程阻塞**：转换流程中 `_ensure_server` 的HTTP轮询在主线程执行，可能冻结GUI。需后续改为异步
- **GUILogHandler 线程安全**：`log_queue.append()` 是线程安全的，但 `update_log()` 的100ms刷新间隔可能导致日志延迟
