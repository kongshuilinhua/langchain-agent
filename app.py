import streamlit as st
from agent.react_agent import ReactAgent
from agent.tools.agent_tools import rag as rag_service
from utils.bootstrap import validate_runtime
from utils.chat_session_store import (
    create_session,
    delete_session,
    load_sessions,
    save_sessions,
    sort_sessions,
    update_session_messages,
    upsert_session,
)
from utils.file_handler import clean_text, pdf_loader
from utils.logger_handler import logger
from utils.path_tool import get_abs_path
import re


st.set_page_config(
    page_title="扫地机器人智能客服",
    page_icon="🤖",
    layout="wide",
)

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;500;700;800&display=swap');

    :root {
        --brand-ink: #19324a;
        --brand-cyan: #3da9a3;
        --brand-gold: #f2c26b;
        --bg-soft: #f5f8fa;
        --surface: #ffffff;
        --surface-2: #ecf3f7;
        --line: #d9e3ea;
        --text-main: #13293d;
        --text-muted: #2f4d63;
    }

    html, body, [class*="css"] {
        font-family: 'Noto Sans SC', sans-serif;
        color: var(--text-main);
        -webkit-font-smoothing: antialiased;
        text-rendering: optimizeLegibility;
    }

    .stApp {
        background:
            radial-gradient(1200px 420px at 100% -10%, rgba(61,169,163,0.22), transparent 70%),
            radial-gradient(900px 400px at -10% 5%, rgba(242,194,107,0.24), transparent 65%),
            linear-gradient(180deg, #f8fbfd 0%, #f2f6f9 100%);
    }

    .main .block-container {
        max-width: 980px;
        padding-top: 2rem;
        padding-bottom: 6.5rem;
    }

    .hero-wrap {
        border: 1px solid var(--line);
        border-radius: 22px;
        padding: 1rem 1.25rem;
        background: linear-gradient(150deg, rgba(255,255,255,0.94), rgba(236,243,247,0.92));
        box-shadow: 0 12px 30px rgba(25,50,74,0.08);
        animation: riseIn 0.45s ease-out;
    }

    .hero-title {
        margin: 0;
        color: var(--brand-ink);
        font-size: 1.95rem;
        font-weight: 800;
        letter-spacing: 0.2px;
    }

    .hero-sub {
        margin: 0.35rem 0 0;
        color: var(--text-muted);
        font-size: 1.06rem;
        font-weight: 600;
    }

    .stat {
        margin-top: 0.9rem;
        display: inline-block;
        padding: 0.38rem 0.72rem;
        border-radius: 999px;
        border: 1px solid #c5d7e3;
        background: #f8fcff;
        color: #1f3d54;
        font-size: 0.9rem;
        font-weight: 700;
        margin-right: 0.45rem;
    }

    div[data-testid="stChatMessage"] {
        border-radius: 16px;
        border: 1px solid var(--line);
        background: rgba(255, 255, 255, 0.96);
        box-shadow: 0 7px 18px rgba(15,43,66,0.07);
        animation: riseIn 0.35s ease-out;
    }

    div[data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] p,
    div[data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] li {
        font-size: 1.08rem;
        line-height: 1.86;
        color: var(--text-main);
        font-weight: 500;
    }

    div[data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] h1,
    div[data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] h2,
    div[data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] h3 {
        color: #143248;
        letter-spacing: 0.2px;
        font-weight: 800;
    }

    [data-testid="stChatMessageAvatarUser"],
    [data-testid="stChatMessageAvatarAssistant"] {
        transform: scale(1.08);
    }

    [data-testid="stChatInput"] {
        position: fixed;
        left: 50%;
        transform: translateX(-50%);
        bottom: 1rem;
        width: min(940px, calc(100% - 1.6rem));
        background: rgba(255,255,255,0.93);
        border: 1px solid var(--line);
        border-radius: 18px;
        box-shadow: 0 16px 34px rgba(15,43,66,0.13);
        padding: 0.22rem 0.72rem;
        backdrop-filter: blur(8px);
    }

    [data-testid="stChatInput"] textarea {
        font-size: 1.08rem;
        font-weight: 500;
        color: var(--text-main);
    }

    div[data-testid="stHorizontalBlock"] div[data-testid="column"] .stButton button {
        width: 100%;
        border-radius: 999px;
        border: 1px solid #c0d4e2;
        background: #f7fbfe;
        color: #1e3f57;
        font-weight: 700;
        font-size: 0.98rem;
        transition: all 0.18s ease;
    }

    div[data-testid="stHorizontalBlock"] div[data-testid="column"] .stButton button:hover {
        background: #e7f4f3;
        border-color: #7fbcb7;
        color: #1f4541;
    }

    div[data-testid="stAlert"] p {
        color: #163349;
        font-size: 1rem;
        font-weight: 600;
    }

    .ref-wrap {
        margin-top: 0.85rem;
        padding-top: 0.8rem;
        border-top: 1px dashed #c9d8e3;
    }

    .ref-title {
        margin-bottom: 0.45rem;
        color: #38586f;
        font-size: 0.88rem;
        font-weight: 800;
        letter-spacing: 0.04em;
    }

    .ref-chip {
        display: inline-block;
        margin: 0 0.45rem 0.45rem 0;
        padding: 0.32rem 0.62rem;
        border-radius: 999px;
        border: 1px solid #c6d9e6;
        background: #f4fafc;
        color: #214158;
        font-size: 0.86rem;
        font-weight: 700;
        line-height: 1.3;
    }

    .ref-preview {
        margin-top: 0.2rem;
        color: #28465b;
        font-size: 0.96rem;
        line-height: 1.75;
    }

    @keyframes riseIn {
        from {
            transform: translateY(8px);
            opacity: 0;
        }
        to {
            transform: translateY(0);
            opacity: 1;
        }
    }

    @media (max-width: 768px) {
        .main .block-container {
            padding-top: 1.2rem;
            padding-bottom: 7.2rem;
        }

        .hero-title {
            font-size: 1.58rem;
        }

        div[data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] p,
        div[data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] li {
            font-size: 1rem;
            line-height: 1.78;
        }

        [data-testid="stChatInput"] {
            width: calc(100% - 0.9rem);
            bottom: 0.4rem;
            border-radius: 14px;
            padding: 0.2rem 0.5rem;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

runtime_issues = validate_runtime()
if runtime_issues:
    for issue in runtime_issues:
        st.error(issue)
    st.stop()

# Agent 实例只初始化一次，避免每次重跑页面都重新构建模型和工具。
if "agent" not in st.session_state:
    st.session_state["agent"] = ReactAgent()

# sessions 存的是全部历史会话；current_session_id 指向当前打开的那一个。
if "sessions" not in st.session_state:
    sessions = sort_sessions(load_sessions())
    if not sessions:
        sessions = [create_session()]
        save_sessions(sessions)
    st.session_state["sessions"] = sessions

if "current_session_id" not in st.session_state:
    st.session_state["current_session_id"] = st.session_state["sessions"][0]["id"]

if "pending_prompt" not in st.session_state:
    st.session_state["pending_prompt"] = ""


def get_current_session() -> dict:
    """根据 current_session_id 取当前会话；如果丢失则兜底创建一个新会话。"""
    current_session_id = st.session_state["current_session_id"]
    for session in st.session_state["sessions"]:
        if session["id"] == current_session_id:
            return session
    fallback = create_session()
    st.session_state["sessions"] = [fallback] + st.session_state["sessions"]
    st.session_state["current_session_id"] = fallback["id"]
    save_sessions(sort_sessions(st.session_state["sessions"]))
    return fallback


def persist_current_messages(messages: list[dict]) -> None:
    """把当前会话消息写回内存和本地文件。"""
    current = get_current_session()
    updated = update_session_messages(current, messages)
    st.session_state["sessions"] = sort_sessions(upsert_session(st.session_state["sessions"], updated))
    st.session_state["current_session_id"] = updated["id"]
    save_sessions(st.session_state["sessions"])


def switch_session(session_id: str) -> None:
    """切换当前会话，同时清空待发送的快捷问题。"""
    st.session_state["current_session_id"] = session_id
    st.session_state["pending_prompt"] = ""


def create_new_chat() -> None:
    """创建新会话并立即切过去。"""
    new_session = create_session()
    st.session_state["sessions"] = sort_sessions(upsert_session(st.session_state["sessions"], new_session))
    st.session_state["current_session_id"] = new_session["id"]
    st.session_state["pending_prompt"] = ""
    save_sessions(st.session_state["sessions"])


def delete_current_chat() -> None:
    """删除当前会话；如果删完为空，则自动补一个空会话。"""
    current_id = st.session_state["current_session_id"]
    sessions = delete_session(st.session_state["sessions"], current_id)
    if not sessions:
        sessions = [create_session()]
    sessions = sort_sessions(sessions)
    st.session_state["sessions"] = sessions
    st.session_state["current_session_id"] = sessions[0]["id"]
    st.session_state["pending_prompt"] = ""
    save_sessions(sessions)


def split_response_and_references(content: str) -> tuple[str, list[str]]:
    """
    把回答正文和“参考来源”拆开。

    RAG 最终返回的是一段完整文本，这里按约定格式拆分，
    方便前端把正文和引用来源分开展示。
    """
    if not content:
        return "", []

    match = re.search(r"\n参考来源：\s*\n(?P<refs>(?:- .+\n?)*)$", content.strip())
    if not match:
        return content.strip(), []

    body = content[: match.start()].strip()
    refs_block = match.group("refs")
    references = [line[2:].strip() for line in refs_block.splitlines() if line.startswith("- ")]
    return body, references


def render_references(references: list[str]):
    """把引用来源渲染成标签，并支持展开查看预览片段。"""
    if not references:
        return

    chips = "".join(f'<span class="ref-chip">{reference}</span>' for reference in references)
    st.markdown(
        f"""
        <div class="ref-wrap">
            <div class="ref-title">参考来源</div>
            <div>{chips}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    for index, reference in enumerate(references, start=1):
        with st.expander(f"查看片段 {index}: {reference}", expanded=False):
            st.caption("命中的本地知识片段预览")
            st.write(load_reference_preview(reference))


def parse_reference_label(reference: str) -> tuple[str, int | None]:
    """从“文件名 / 文件名 + 页码”格式中解析出来源和页码。"""
    match = re.match(r"^(?P<source>.+?)(?: 第(?P<page>\d+)页)?$", reference.strip())
    if not match:
        return reference.strip(), None
    source = match.group("source").strip()
    page = match.group("page")
    return source, int(page) - 1 if page else None


@st.cache_data(show_spinner=False)
def load_reference_preview(reference: str) -> str:
    """
    读取引用来源的本地预览片段。

    txt 直接读取文件开头片段；
    pdf 优先按页码读取对应页内容。
    """
    source, page = parse_reference_label(reference)
    abs_path = get_abs_path(f"data/{source}")
    if not abs_path or not source:
        return "未能解析参考来源。"

    try:
        if source.lower().endswith(".txt"):
            with open(abs_path, "r", encoding="utf-8") as f:
                preview = clean_text(f.read())[:420]
                return preview or "该文本来源没有可展示的预览内容。"
        if source.lower().endswith(".pdf"):
            docs = pdf_loader(abs_path)
            if page is not None and 0 <= page < len(docs):
                return clean_text(docs[page].page_content)[:420] or "该页没有可展示内容。"
            if docs:
                return clean_text(docs[0].page_content)[:420] or "PDF 没有可展示内容。"
            return "PDF 没有可展示内容。"
    except FileNotFoundError:
        return f"本地未找到来源文件：{source}"
    except Exception as e:
        logger.warning(f"加载参考片段失败: {reference}, error={str(e)}")
        return f"无法读取该来源的片段预览：{source}"

    return f"当前仅支持预览 txt/pdf 来源，文件：{source}"


def render_message(message: dict):
    """统一渲染一条消息，自动处理正文和引用来源。"""
    body, references = split_response_and_references(message["content"])
    st.write(body or message["content"])
    render_references(references)


with st.sidebar:
    # 侧边栏负责会话管理，体验上接近常见大模型产品的历史会话区。
    st.markdown("## 会话管理")
    sidebar_action_cols = st.columns(2)
    if sidebar_action_cols[0].button("新建会话", use_container_width=True):
        create_new_chat()
        st.rerun()
    if sidebar_action_cols[1].button("删除当前", use_container_width=True):
        delete_current_chat()
        st.rerun()

    st.caption("历史会话")
    current_session = get_current_session()
    for session in st.session_state["sessions"]:
        label = session["title"] or "新对话"
        if st.button(
            label,
            key=f"session_{session['id']}",
            use_container_width=True,
            type="primary" if session["id"] == current_session["id"] else "secondary",
        ):
            switch_session(session["id"])
            st.rerun()

st.markdown(
    """
    <div class="hero-wrap">
        <h1 class="hero-title">扫地机器人智能客服</h1>
        <p class="hero-sub">快速解答选购、故障排查、维护保养与使用技巧，支持多轮对话。</p>
        <span class="stat">知识库问答</span>
        <span class="stat">故障诊断建议</span>
        <span class="stat">维护提醒</span>
    </div>
    """,
    unsafe_allow_html=True,
)

st.write("")
action_cols = st.columns([1, 1, 4])
if action_cols[0].button("清空会话"):
    # 清空的是“当前会话”的消息，不影响其他历史会话。
    persist_current_messages([])
    st.session_state["pending_prompt"] = ""
    st.rerun()

if action_cols[1].button("重建知识库"):
    try:
        with st.spinner("正在重建知识库，请稍候..."):
            # 这里直接调用当前运行中的 RAG 服务实例，避免页面重启后才生效。
            rag_service.vector_store.reset_store(clear_md5=True)
            rag_service.vector_store.load_document(force_reload=True)
            rag_service._collection_ready_checked = True
        st.success("知识库重建完成。")
    except Exception as e:
        logger.error(f"知识库重建失败: {str(e)}", exc_info=True)
        st.error("知识库重建失败，请查看日志。")

shortcut_cols = st.columns(3)
shortcuts = [
    "我家适合买扫拖一体还是纯扫地？",
    "机器人不回充了怎么排查？",
    "怎么做日常维护延长寿命？",
]
for col, text in zip(shortcut_cols, shortcuts):
    if col.button(text):
        st.session_state["pending_prompt"] = text

current_session = get_current_session()
current_messages = current_session.get("messages", [])

# 页面展示的始终是“当前会话”的消息。
if not current_messages:
    st.info("可以先试试上面的快捷问题，也可以直接在下方输入你的需求。")

for message in current_messages:
    avatar = "🧑" if message["role"] == "user" else "🤖"
    with st.chat_message(message["role"], avatar=avatar):
        render_message(message)

input_prompt = st.chat_input("请输入你的问题，例如：拖地有水痕怎么处理？")
prompt = input_prompt or st.session_state.get("pending_prompt", "")
if prompt:
    st.session_state["pending_prompt"] = ""
    with st.chat_message("user", avatar="🧑"):
        st.write(prompt)
    # 先写入用户消息，再调用 Agent，这样异常时也能保留用户输入。
    current_messages = current_messages + [{"role": "user", "content": prompt}]
    persist_current_messages(current_messages)

    response_chunks = []

    def capture(generator, cache_list, placeholder):
        """一边接收流式输出，一边实时刷新前端占位区域。"""
        for chunk in generator:
            cache_list.append(chunk)
            body, _ = split_response_and_references("".join(cache_list))
            placeholder.markdown(body or "".join(cache_list))
            yield chunk

    try:
        with st.spinner("正在分析问题并检索答案..."):
            res_stream = st.session_state["agent"].execute_stream(current_messages)
            with st.chat_message("assistant", avatar="🤖"):
                response_placeholder = st.empty()
                for _ in capture(res_stream, response_chunks, response_placeholder):
                    pass

        response_text = "".join(response_chunks).strip()
        if not response_text:
            response_text = "暂时没有生成有效回答，请重试。"
        else:
            # 流式阶段只先展示正文，结束后再补渲染来源区，避免中途闪烁。
            body, references = split_response_and_references(response_text)
            response_placeholder.markdown(body or response_text)
            render_references(references)
    except Exception as e:
        logger.error(f"对话处理失败: {str(e)}", exc_info=True)
        response_text = "服务暂时不可用，请稍后重试。"
        with st.chat_message("assistant", avatar="🤖"):
            st.write(response_text)

    # 最终回答也要落盘，这样刷新页面后仍能恢复完整会话。
    current_messages = current_messages + [{"role": "assistant", "content": response_text}]
    persist_current_messages(current_messages)
    st.rerun()
