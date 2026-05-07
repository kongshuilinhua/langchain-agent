import uuid

import streamlit as st

import config_data as config
from env_utils import load_dotenv
from rag import RagService

load_dotenv(str(config.PROJECT_ROOT / ".env"))

st.title("智能客服")
st.divider()

if "rag" not in st.session_state:
    st.session_state["rag"] = RagService()

if "session_id" not in st.session_state:
    st.session_state["session_id"] = f"user_{uuid.uuid4().hex}"

if "message" not in st.session_state:
    st.session_state["message"] = [
        {"role": "assistant", "content": "你好，有什么可以帮助你？"}
    ]

if "last_sources" not in st.session_state:
    st.session_state["last_sources"] = []

for message in st.session_state["message"]:
    st.chat_message(message["role"]).write(message["content"])

prompt = st.chat_input()
if prompt:
    st.chat_message("user").write(prompt)
    st.session_state["message"].append({"role": "user", "content": prompt})

    with st.spinner("AI 正在思考中..."):
        session_config = config.build_session_config(st.session_state["session_id"])
        res_stream, source_docs, fallback = st.session_state["rag"].answer_question(
            prompt,
            session_config,
        )
        st.session_state["last_sources"] = source_docs

        if fallback:
            st.chat_message("assistant").write(fallback)
            st.session_state["message"].append(
                {"role": "assistant", "content": fallback}
            )
        else:
            ai_res_list = []

            def capture(generator, cache_list):
                for item in generator:
                    cache_list.append(item)
                    yield item

            st.chat_message("assistant").write_stream(capture(res_stream, ai_res_list))
            st.session_state["message"].append(
                {"role": "assistant", "content": "".join(ai_res_list)}
            )

if st.session_state["last_sources"]:
    with st.expander("查看本轮命中的参考资料"):
        for index, doc in enumerate(st.session_state["last_sources"], start=1):
            source = doc.metadata.get("source", "未知来源")
            create_time = doc.metadata.get("create_time", "未知时间")
            score = doc.metadata.get("relevance_score", "未知分数")
            st.markdown(f"**{index}. {source}**")
            st.caption(f"入库时间: {create_time} | 相关度: {score}")
            st.write(doc.page_content)
