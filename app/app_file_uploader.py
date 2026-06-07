import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""
基于Streamlit的知识库文件上传Web服务

提供图形化界面让用户上传TXT文件到知识库系统，主要功能：
- 文件上传：支持TXT格式文件的拖拽或选择上传
- 文件预览：显示文件基本信息和内容预览
- 自动处理：调用知识库服务进行文本分割、向量化和存储
- 去重检查：通过MD5校验避免重复上传相同内容

使用Streamlit框架构建交互式Web应用，无需前端开发经验即可快速搭建
"""

import streamlit as st
from src.knowledge import KnowledgeBaseService


# ==================== 页面配置 ====================
# 设置网页标题，显示在浏览器标签页和页面顶部
st.title("知识库更新服务")

# ==================== 文件上传组件 ====================
# 创建文件上传器组件，允许用户上传文件
uploaded_file = st.file_uploader(
    "请上传TXT文件",           # 上传组件的提示文本
    type=["txt"],              # 允许的文件类型列表，仅接受TXT格式
    accept_multiple_files=False,  # 是否允许多文件上传，False表示一次只能上传一个文件
)

# ==================== 会话状态管理 ====================
# 使用Streamlit的session_state机制持久化知识库服务对象
# 避免每次用户交互时都重新初始化，提高性能并保持向量数据库连接
if "service" not in st.session_state:
    # 首次访问时创建KnowledgeBaseService实例并保存到会话状态
    # 后续请求会复用同一个实例，保持Chroma数据库连接
    st.session_state["service"] = KnowledgeBaseService()

# ==================== 文件处理逻辑 ====================
# 当用户上传了文件后（uploaded_file不为None），执行以下处理流程
if uploaded_file is not None:
    # 第一步：获取上传文件的基本信息
    file_name = uploaded_file.name      # 文件名（包含扩展名）
    file_type = uploaded_file.type      # MIME类型（如text/plain）
    file_size = uploaded_file.size      # 文件大小（字节）

    # 第二步：在页面上显示文件信息，让用户确认上传的文件
    st.write("文件名称：", file_name)
    st.write("文件类型：", file_type)
    st.write("文件大小：", file_size, "字节")

    # 第三步：读取文件内容并解码为字符串
    # getvalue()返回字节流，需要使用UTF-8编码解码成文本
    txt = uploaded_file.getvalue().decode("utf-8")
    
    # 第四步：在页面上预览文件内容（用于调试和确认）
    # 注意：大文件可能会导致页面加载缓慢，生产环境建议限制预览长度
    st.write(txt)

    # 第五步：显示加载动画，提升用户体验
    # spinner会在代码块执行期间显示旋转加载图标和提示文本
    with st.spinner("上传中..."):
        # 第六步：调用知识库服务处理上传的文件
        # 注意：这里调用的upload_file方法在knowledge_base.py中尚未实现
        # 当前knowledge_base.py中只有upload_bt_str方法，需要补充upload_file方法
        result = st.session_state["service"].upload_bt_str(txt, file_name)
    
    # 第七步：显示处理结果（成功或失败信息）
    st.write(result)