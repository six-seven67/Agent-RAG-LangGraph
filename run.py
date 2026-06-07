"""
Agent 智能客服系统 — 便捷启动入口

用法:
    python run.py              # 开发模式（热重载）
    python run.py --prod       # 生产模式（4 workers）

等价于:
    uvicorn app.fastapi_server:app --reload --host 0.0.0.0 --port 8000
"""

import sys
import os

# 确保项目根目录在 sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    import uvicorn

    prod = "--prod" in sys.argv
    uvicorn.run(
        "app.fastapi_server:app",
        host="0.0.0.0",
        port=8000,
        reload=not prod,
        workers=4 if prod else 1,
    )
