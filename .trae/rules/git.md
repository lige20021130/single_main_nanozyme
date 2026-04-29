alwaysApply: true
scene: git_commit
---

# GitHub 自动上传规则

你负责在每次项目修改后，协助完成 GitHub 提交与上传。

## 核心规则（修改后）

每次我修改代码后，**自动执行上传流程**，不需要等待我的"上传"指令。

当用户明确说“上传”“提交到 GitHub”“推送”“同步仓库”“更新 GitHub”时，同样执行上传。

## 标准流程

优先执行：

```bash
git status

确认有修改后执行：

git add .
git commit -m "<合适的提交信息>"
git push

如果当前分支第一次推送，先查看分支：

git branch --show-current

假设当前分支是 main，则执行：

git push -u origin main

不要把“当前分支名”这类占位符直接写进命令。
```

## 提交信息规范

使用 Conventional Commits：

```
<type>(<scope>): <中文描述>
```

常用 type：
- feat：新增功能
- fix：修复问题
- docs：文档更新
- refactor：代码重构
- test：测试相关
- chore：配置、依赖、规则、杂项

示例：
```
fix(extraction): 优化纳米酶数据提取逻辑
docs: 更新项目迭代日志
chore(git): 更新 GitHub 上传规则
```

## 文件提交规则（严格执行）

**绝对不要提交：**
- `__pycache__/`
- `*.pyc`
- `*.bak`
- `*.log`
- `temp_*.py`
- `new_lit_output/`
- `validation_output/`
- `venv/`（虚拟环境）
- `.env`（环境变量，可能包含 API key）
- `config.yaml`（可能包含 API key）
- `.vscode/`
- `.idea/`
- `test_output_*/`
- `e2e_results/`
- 任何包含 token、密码、密钥、账号的文件
- 大体积中间文件（> 10MB）

如果发现上述文件，应先确保它们在 `.gitignore` 中。如果已经被 Git 跟踪，使用：
```bash
git rm -r -f --cached <文件/目录>
```

## 安全要求

上传前必须检查是否包含 token、密码、密钥、账号、本地日志、大体积中间文件。发现疑似敏感文件时，不要直接提交，应先提醒用户确认。

## 输出要求

优先直接给可复制命令，少解释。命令需适配 PowerShell。不要重复执行无意义的 commit 或 push。
