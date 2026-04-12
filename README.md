# RAG 知识库示例（LangChain + Chroma + 通义）

## 本地运行

1. 创建虚拟环境并安装依赖：

   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. 配置环境变量：复制 `.env.example` 为 `.env`，填入 `DASHSCOPE_API_KEY`。

3. 按需运行 Streamlit 应用（以你目录中的入口为准），例如：

   ```bash
   streamlit run app_qa.py
   streamlit run app_file_uploader.py
   ```

首次运行会在本地生成 `chroma.db` 向量库目录（已加入 `.gitignore`，不会上传到 GitHub）。

## 上传到 GitHub

在**本目录**下执行（将 `你的用户名` 与 `仓库名` 换成自己的）：

```bash
git init
git add .
git commit -m "Initial commit: RAG demo"
```

在 GitHub 网页新建空仓库（不要勾选添加 README），然后：

```bash
git branch -M main
git remote add origin https://github.com/你的用户名/仓库名.git
git push -u origin main
```

若使用 SSH：

```bash
git remote add origin git@github.com:你的用户名/仓库名.git
git push -u origin main
```

**注意：** 永远不要提交 `.env` 或真实 API Key；仅提交 `.env.example`。
