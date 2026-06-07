# Git 使用指南 — RAG 智能客服系统

> 本文档为零基础 Git 操作指南，涵盖本项目的日常开发场景。

---

## 一、Git 是什么？

Git 是一个**版本管理工具**，它的核心作用是：

- **记录代码的每一次修改**（谁、什么时候、改了什么）
- **可以回退到任意历史版本**（改坏了可以撤销）
- **多人协作开发**（每个人写自己的部分，最后合并）

你可以把它理解为「代码的时光机 + 协作平台」。

---

## 二、核心概念速览

| 概念 | 通俗解释 |
|------|---------|
| **仓库（Repository）** | 存放代码的地方。远程仓库在 GitHub，本地仓库在你电脑 |
| **克隆（Clone）** | 把 GitHub 上的代码下载到本地 |
| **暂存（Stage）** | 告诉 Git「这些文件的修改我打算提交」 |
| **提交（Commit）** | 把暂存的修改正式记录到版本历史中 |
| **推送（Push）** | 把本地的新提交上传到 GitHub |
| **拉取（Pull）** | 把 GitHub 上的新提交下载到本地 |
| **分支（Branch）** | 一条独立的开发线，互不干扰 |
| **合并（Merge）** | 把两条开发线合在一起 |

```
┌─────────────┐    git push →    ┌─────────────┐
│  你的电脑     │                  │   GitHub     │
│  (本地仓库)   │    ← git pull   │  (远程仓库)   │
└─────────────┘                  └─────────────┘
```

---

## 三、本项目 Git 远程地址

```
https://github.com/six-seven67/RAG-LangChain.git
```

**分支说明：**

| 分支 | 用途 |
|------|------|
| `main` | 主分支，稳定版本，可部署 |
| `develop`（建议） | 开发分支，日常开发在这里 |

---

## 四、日常操作（必会）

### 4.1 首次克隆项目

```bash
git clone https://github.com/six-seven67/RAG-LangChain.git
cd RAG-LangChain
```

### 4.2 日常开发流程

```bash
# 1. 开始工作前，先拉取最新代码
git pull origin main

# 2. 写代码、改文件...

# 3. 查看哪些文件被修改了
git status

# 4. 查看具体改了什么内容
git diff

# 5. 把修改的文件加入暂存区
git add .                    # 添加所有修改
# 或者
git add src/api/chat.py      # 只添加某个文件

# 6. 提交（记录这次修改）
git commit -m "修复：会话列表显示第一条消息作为标题"

# 7. 推送到 GitHub
git push origin main
```

### 4.3 提交信息规范

```bash
# 好的提交信息（清楚表达了做了什么）
git commit -m "新增：用户注册登录功能"
git commit -m "修复：流式对话无响应问题"
git commit -m "优化：查询改写增加指代消解逻辑"

# 不好的提交信息
git commit -m "修改"
git commit -m "123"
```

### 4.4 查看历史

```bash
# 查看提交历史
git log --oneline -10

# 查看某个文件的修改历史
git log --oneline src/rag_async.py

# 查看某次提交改了哪些内容
git show abc1234
```

---

## 五、分支操作（推荐）

使用分支可以让新功能开发不影响主代码：

```bash
# 创建并切换到新分支
git checkout -b feature/新功能名

# 在这个分支上开发、提交...
git add .
git commit -m "新增：xxx功能"

# 切回 main 并合并
git checkout main
git merge feature/新功能名

# 推送 main
git push origin main

# 删除已合并的分支
git branch -d feature/新功能名
```

---

## 六、常见场景处理

### 6.1 改坏了想回退

```bash
# 回退单个文件到上次提交的状态
git checkout -- src/api/chat.py

# 回退所有修改（危险！未提交的修改将丢失）
git checkout -- .

# 撤销最近一次 commit（保留文件修改）
git reset --soft HEAD~1

# 撤销最近一次 commit（同时丢弃文件修改，危险！）
git reset --hard HEAD~1
```

### 6.2 提交到错误的 commit 想改

```bash
# 修改最近一次 commit 的信息
git commit --amend -m "新的提交信息"

# 给最近一次 commit 追加忘记添加的文件
git add 忘记的文件.py
git commit --amend --no-edit
```

### 6.3 解决冲突

当 `git pull` 或 `git merge` 时出现冲突：

```bash
# 冲突文件会显示类似：
# <<<<<<< HEAD
# 你的修改
# =======
# 别人的修改
# >>>>>>> origin/main

# 1. 手动编辑冲突文件，保留正确的代码
# 2. 删除 <<<<<<<、=======、>>>>>>> 标记
# 3. 标记冲突已解决
git add 冲突文件.py
git commit -m "合并：解决冲突"
```

### 6.4 不小心提交了不该提交的文件

```bash
# 1. 先把文件从 Git 跟踪中移除（但保留本地文件）
git rm --cached .env
git rm --cached -r chat_history/

# 2. 更新 .gitignore 确保不再跟踪
# 在 .gitignore 中添加：
#   .env
#   chat_history/

# 3. 提交
git add .gitignore
git commit -m "修复：移除敏感文件"

# 4. 推送（注意：历史记录中仍然存在旧版本的文件！）
git push origin main
```

> ⚠️ 如果敏感信息（如密码、API Key）已经被推送到 GitHub，仅删除文件不够，必须立即去网站上更换密钥！

### 6.5 如何打 Tag（版本标记）

```bash
# 打一个轻量 tag
git tag v2.0.0

# 打一个带注释的 tag
git tag -a v2.0.0 -m "v2.0.0: 企业级架构升级，新增 JWT + MySQL + Redis + 用户隔离"

# 推送 tag 到 GitHub
git push origin v2.0.0

# 查看所有 tag
git tag -l
```

---

## 七、.gitignore — 什么不该上传

本项目 `.gitignore` 已配置以下文件**不上传**：

| 文件/目录 | 原因 |
|-----------|------|
| `.env` | 包含 API Key、数据库密码 |
| `chroma.db/` | 向量库，体积大，可重建 |
| `chat_history/` | 对话历史，包含用户隐私 |
| `__pycache__/` | Python 缓存，无意义 |
| `.idea/` `.vscode/` | IDE 个人配置 |

---

## 八、本项目推荐的 Git 工作流

```
main 分支（稳定）
  │
  ├── v1.0.0  初始版本（Streamlit MVP）
  ├── v2.0.0  企业级升级（FastAPI + JWT + MySQL + Redis + 用户隔离）
  └── v3.0.0  未来版本...

开发流程：
  1. git checkout -b feature/xxx     # 创建功能分支
  2. 在这个分支上写代码、提交
  3. 完成后合并到 main
  4. git tag vX.X.X                 # 打版本号
  5. git push origin main --tags    # 推送代码和标签
```

---

## 九、常用命令速查

```bash
git status                    # 查看状态（最常用）
git diff                      # 查看未暂存的修改
git add <file>                # 暂存文件
git commit -m "message"       # 提交
git push origin main          # 推送到 GitHub
git pull origin main          # 拉取最新代码
git log --oneline -10         # 查看最近 10 条提交
git checkout -b <branch>      # 创建并切换分支
git merge <branch>            # 合并分支
git reset --soft HEAD~1       # 撤销 commit（保留修改）
git checkout -- <file>        # 丢弃文件修改
git stash                     # 暂存当前修改（去干别的事）
git stash pop                 # 恢复暂存的修改
git tag -a v1.0.0 -m "..."    # 打标签
```

---

## 十、更多学习资源

- [Git 官方文档](https://git-scm.com/doc)
- [GitHub Skills](https://skills.github.com/) — 交互式 Git 教程
- [可视化 Git 学习](https://learngitbranching.js.org/) — 游戏化学习分支操作
- [Conventional Commits](https://www.conventionalcommits.org/) — 提交信息规范参考
