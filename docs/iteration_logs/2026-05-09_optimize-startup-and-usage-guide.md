# 优化系统启动使用与编写使用指南

## 更新时间
2026-05-09 22:00

## 更新类型
- 功能开发 / 文档

## 背景
用户反馈系统启动体验差：start.bat闪退、Python路径检测不全、缺少依赖检查、config.yaml缺失时提示不友好。需要优化启动流程并编写使用指南。

## 改动内容

### start.bat 优化
- 添加 `chcp 65001` 确保中文编码正确显示
- 增加 TraeAI-5 conda 环境路径检测
- 增加 `C:\ProgramData\anaconda3` 路径检测
- 添加 `where python` PATH 搜索兜底
- Python 未找到时给出明确安装提示
- 显示 Python 版本号
- 错误退出码检测和故障排除提示

### start.py 优化
- 新增 `check_python_version()`：Python 3.10+ 版本检查
- 新增 `check_dependencies()`：必需/可选依赖包检查
- 新增 `check_project_files()`：核心文件完整性检查
- 新增 `check_config()`：配置文件检查（缺失时给出友好提示）
- 启动前自动执行预检查（Pre-flight checks）
- 检查失败时阻止启动并给出修复建议
- 直接启动 GUI（不再通过 subprocess 调用）

### nanozyme_gui.py 优化
- config.yaml 缺失时提供三选一对话框：生成模板/规则模式/取消
- 新增 `_generate_config_template()` 方法：自动生成含推荐配置的 config.yaml 模板
- 模板包含 DeepSeek LLM 和硅基流动 VLM 的推荐配置

### 使用指南
- 新建 `usage_guide.md`：完整使用指南文档
- 涵盖：环境要求、安装依赖、启动方式、API配置、使用流程、结果说明、常见问题

## 未改动内容
- 提取引擎核心逻辑未改动
- config_manager.py 未改动
- api_client.py 未改动
- 测试用例未改动

## 验证方式
- `python -m py_compile start.py` 编译通过
- `python -m py_compile nanozyme_gui.py` 编译通过
- `python -c "from start import check_python_version, check_dependencies, check_project_files, check_config"` 全部检查通过
- `python -m pytest tests/ -v` 139 个测试全部通过

## 风险与后续
- start.bat 中硬编码了 D:\conda 路径，其他用户需根据实际环境修改
- 后续可考虑自动检测 conda 环境并激活
- 使用指南可根据用户反馈持续完善
