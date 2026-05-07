import time

import streamlit as st

import config_data as config
from env_utils import load_dotenv
from knowledge_base import KnowledgeBaseService

load_dotenv(str(config.PROJECT_ROOT / ".env"))

st.title("知识库管理")

if "service" not in st.session_state:
    st.session_state["service"] = KnowledgeBaseService()

service = st.session_state["service"]

uploaded_file = st.file_uploader(
    "请上传 txt 或 md 文件",
    type=["txt", "md"],
    accept_multiple_files=False,
)

if uploaded_file is not None:
    file_name = uploaded_file.name
    file_type = uploaded_file.type or "text/plain"
    file_size = uploaded_file.size / 1024
    st.subheader(f"文件名: {file_name}")
    st.write(f"格式: {file_type} | 大小: {file_size:.2f} KB")
    text = uploaded_file.getvalue().decode("utf-8")
    with st.spinner("正在导入知识库..."):
        time.sleep(0.5)
        st.success(service.upload_by_str(text, file_name))

st.divider()
st.subheader("已入库文件")

sources = service.list_sources()
if not sources:
    st.info("当前知识库还没有文件。")
else:
    for source_item in sources:
        col1, col2 = st.columns([4, 1])
        with col1:
            st.markdown(f"**{source_item['source']}**")
            st.caption(
                f"入库时间: {source_item['create_time']} | 分块数: {source_item['chunk_count']}"
            )
        with col2:
            if st.button("删除", key=f"delete_{source_item['source']}"):
                with st.spinner("正在删除来源文件..."):
                    st.warning(service.delete_by_source(source_item["source"]))
                st.rerun()
