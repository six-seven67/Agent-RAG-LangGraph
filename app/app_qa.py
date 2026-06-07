
import sys, os, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.rag import AsyncRagService
import streamlit as st
import src.config as config
from src.storage import load_history_for_ui

st.title("智能客服")
st.divider()

# -------- 初始化 session_id（每个标签页唯一）--------
if "session_id" not in st.session_state:
    st.session_state["session_id"] = str(uuid.uuid4())
    st.session_state["session_config"] = config.build_session_config(
        st.session_state["session_id"]
    )

# -------- 初始化消息：先从文件历史恢复，再补默认欢迎语 --------
if "message" not in st.session_state:
    history = load_history_for_ui(st.session_state["session_id"])
    if history:
        st.session_state["message"] = history
    else:
        st.session_state["message"] = [
            {"role": "assistant", "content": "你好，有什么可以帮助你？"}
        ]

# -------- 初始化 RAG 服务 --------
if "rag" not in st.session_state:
    st.session_state["rag"] = AsyncRagService()

# -------- 渲染历史消息 --------
for message in st.session_state["message"]:
    st.chat_message(message["role"]).write(message["content"])

# -------- 用户输入 --------
prompt = st.chat_input()

if prompt:
    st.chat_message("user").write(prompt)
    st.session_state["message"].append({"role": "user", "content": prompt})

    ai_res_list = []
    with st.spinner("AI思考中..."):
        # 使用异步服务的同步兼容接口（异步管道 → 同步生成器）
        res_stream = st.session_state["rag"].sync_stream(
            {"input": prompt}, st.session_state["session_config"]
        )

        def capture(generator, cache_list):
            for chunk in generator:
                cache_list.append(chunk)
                yield chunk

        st.chat_message("assistant").write_stream(capture(res_stream, ai_res_list))
        st.session_state["message"].append(
            {"role": "assistant", "content": "".join(ai_res_list)}
        )
