from __future__ import annotations

import base64
import binascii
import os
import re
import tempfile
import uuid
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from sqlalchemy.orm import Session

from core.config import get_settings
from core.db.models import Upload

# 🧠 魔鬼数字与前沿技术参数：支持的多模态文件 mime-type 集合划分。
# 区分 image 与 document 可以让系统对于不同资产实施差异化的编排链路（如多模态 Vision vs RAG 检索分流）。
IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
TEXT_TYPES = {"text/plain", "text/markdown", "application/markdown", "text/csv"}
DOC_TYPES = TEXT_TYPES | {"application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
LANGCHAIN_EXTRA_SUFFIXES = {".html", ".htm"}
LANGCHAIN_EXTRA_TYPES = {"text/html", "application/xhtml+xml"}


def create_upload(db: Session, *, workspace_id: int, user_id: int, filename: str, content_type: str, content_base64: str) -> Upload:
    """
    创建上传文件并自动解析提取其多模态内容或纯文本。

    🎯 意图与工程大局观：
        本函数为平台多模态资产接入与 RAG 文本入库的“安检口”和“分流器”。
        - 对于图片资产，将其包装为规范的 data_url 直接传递给多模态大模型进行视觉推理。
        - 对于文档资产，触发提取管道拉取其核心文本，持久化为 RAG 或 Context 提示词的一部分。
    
    🛡️ 防御性编程与大模型兜底：
        - 限制文件尺寸（settings.upload_max_bytes），防止大体积文件攻击引起服务端 OOM。
        - 限制只有 image 和 document 两类资源准入，其余归于 unknown 抛出，从源头封堵未知漏洞。
        - 对文档提取出的纯文本进行严格的 `\x00` 空字符过滤，规避数据库在保存时的 Null-byte 物理截断报错。
        - 对提取结果进行硬性长度限制 `[:20000]`，防止由于单个超长 PDF 塞爆大模型上下文窗口或在 Embedding 阶段产生超长 Token 费用。
    """
    settings = get_settings()
    raw = _decode_base64(content_base64)
    if len(raw) > settings.upload_max_bytes:
        raise ValueError(f"Upload file cannot exceed {settings.upload_max_bytes // (1024 * 1024)}MB")
    kind = _kind(content_type, filename)
    if kind not in {"image", "document"}:
        raise ValueError("Only image and document uploads are supported")
    data_url = ""
    text = ""
    if kind == "image":
        data_url = f"data:{content_type};base64,{base64.b64encode(raw).decode('ascii')}"
    else:
        text = sanitize_extracted_text(extract_document_text(filename, content_type, raw))
        if not text.strip():
            raise ValueError("Document text could not be extracted")
    upload = Upload(
        id=f"upload_{uuid.uuid4().hex}",
        workspace_id=workspace_id,
        user_id=user_id,
        filename=Path(filename).name,
        content_type=content_type,
        kind=kind,
        data_url=data_url,
        text=text[:20000],
        size=len(raw),
    )
    db.add(upload)
    db.commit()
    db.refresh(upload)
    return upload


def upload_payload(upload: Upload) -> dict:
    """
    序列化上传实体，返回前端交互所需的最小信息载荷。

    🧠 魔鬼数字：`text_preview` 截断长度限制在 240 字符。
        作为列表预览时既能为用户提供足够的上下文认知，又能避免返回完整文本拖慢前端渲染与网络 I/O 吞吐。
    """
    return {
        "id": upload.id,
        "filename": upload.filename,
        "content_type": upload.content_type,
        "type": upload.kind,
        "size": upload.size,
        "preview_url": upload.data_url if upload.kind == "image" else "",
        "text_preview": (upload.text or "")[:240],
    }


def get_workspace_uploads(db: Session, *, workspace_id: int, upload_ids: list[str]) -> list[Upload]:
    """
    批量获取指定工作区下的上传资源并校验所有权。

    🛡️ 防御性编程（多租户越权防范）：
        即使传入合法的 UUID，在查询时也必须携带当前 Workspace_id 联合过滤。
        最后采用两集合比对，一旦发现请求的 IDs 和实际检索出的 IDs 不等，立刻抛出
        "Upload not found or not accessible" 异常，从底层物理掐断“水平越权”获取他人资产的行为。
    """
    if not upload_ids:
        return []
    uploads = (
        db.query(Upload)
        .filter(Upload.workspace_id == workspace_id, Upload.id.in_(upload_ids))
        .order_by(Upload.created_at.asc())
        .all()
    )
    found_ids = {upload.id for upload in uploads}
    requested_ids = set(upload_ids)
    if found_ids != requested_ids:
        raise ValueError("Upload not found or not accessible")
    return uploads


def extract_document_text(filename: str, content_type: str, raw: bytes) -> str:
    """
    自适应文档提取总枢纽。

    🎯 意图与工程大局观：
        依据文件后缀与 mime-type 自动调度正确的解码器。
        支持纯文本、Markdown、CSV、PDF 和 DOCX。
    """
    suffix = Path(filename).suffix.lower()
    if content_type in TEXT_TYPES or suffix in {".txt", ".md", ".markdown", ".csv"}:
        return decode_bytes(raw)
    if content_type == "application/pdf" or suffix == ".pdf":
        return _extract_pdf_text(raw)
    if content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document" or suffix == ".docx":
        return _extract_docx_text(raw)
    if get_settings().ingest_langchain_loaders and (
        suffix in LANGCHAIN_EXTRA_SUFFIXES or content_type in LANGCHAIN_EXTRA_TYPES
    ):
        return _extract_via_langchain(filename, raw)
    raise ValueError("Unsupported document type")


def _extract_via_langchain(filename: str, raw: bytes) -> str:
    """通过 LangChain loader 提取额外文档类型，并确保 Windows 临时文件可被重新打开。"""
    suffix = Path(filename).suffix.lower()
    temp_path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temp_file:
            temp_file.write(raw)
            temp_path = temp_file.name
        try:
            if suffix in {".html", ".htm"}:
                from langchain_community.document_loaders import BSHTMLLoader

                loader = BSHTMLLoader(
                    temp_path,
                    open_encoding="utf-8",
                    bs_kwargs={"features": "lxml"},
                    get_text_separator="\n",
                )
            else:
                raise ValueError(f"Unsupported LangChain loader suffix: {suffix}")
            documents = loader.load()
            return "\n".join(document.page_content for document in documents)
        finally:
            if temp_path:
                os.unlink(temp_path)
    except Exception as exc:
        raise ValueError(f"LangChain document extraction failed for {suffix or 'unknown'}") from exc


def sanitize_extracted_text(text: str) -> str:
    """
    清洗过滤提取后的文本，剔除 Null 字节 `\x00`，保证数据库及下游大模型在序列化/传输时安全稳定。
    """
    return str(text or "").replace("\x00", "")


def decode_bytes(raw: bytes) -> str:
    """字节解码：utf-8 严格 → gbk 严格(中文 Windows 常见) → charset_normalizer 探测 → utf-8 replace 兜底。

    🧠 为什么显式试 gbk：charset_normalizer 对短中文文本(几个字)探测不稳，而本项目大量面对
    中文 Windows 的 GBK/GB2312 文本，故在概率探测前先尝试严格 gbk（非法字节会抛错，不会误吞）。
    """
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:
        return raw.decode("gbk")
    except UnicodeDecodeError:
        pass
    try:
        from charset_normalizer import from_bytes

        best = from_bytes(raw).best()
        if best is not None:
            return str(best)
    except Exception:
        pass
    return raw.decode("utf-8", errors="replace")


def _decode_base64(content_base64: str) -> bytes:
    """
    防爆防注入式 Base64 解码器。
    
    🛡️ 防御性设计：
        支持解析带有 `data:...;base64,` 前缀的 Data URL 格式，也能处理纯 base64 裸码。
        强制开启 `validate=True` 校验，一旦有格式损坏的脏数据直接抛出 ValueError，杜绝非法二进制溢出攻击风险。
    """
    payload = content_base64.split(",", 1)[1] if content_base64.startswith("data:") and "," in content_base64 else content_base64
    try:
        return base64.b64decode(payload, validate=True)
    except binascii.Error as exc:
        raise ValueError("Invalid base64 upload payload") from exc


def _kind(content_type: str, filename: str) -> str:
    """多级 fallback 的资源归类判定器。"""
    suffix = Path(filename).suffix.lower()
    if content_type in IMAGE_TYPES or suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        return "image"
    if content_type in DOC_TYPES or suffix in {".txt", ".md", ".markdown", ".csv", ".pdf", ".docx"}:
        return "document"
    if get_settings().ingest_langchain_loaders and (
        content_type in LANGCHAIN_EXTRA_TYPES or suffix in LANGCHAIN_EXTRA_SUFFIXES
    ):
        return "document"
    return "unknown"


def _extract_pdf_text(raw: bytes) -> str:
    """
    高度健壮的 PDF 文本解析器。

    🛡️ 防御性编程与大模型兜底：
        - 优先导入第三方 `pypdf` 进行页层级（Page-by-page）的物理文本提取。
        - 设计了高强度 Fallback（平滑降级）：
          如果 pypdf 模块由于环境原因未安装，或者解析加密/损坏的 PDF 失败抛出异常，
          系统会自动切入备用路径：以 `latin-1` 强制解码，使用正则抓取 PDF 未压缩特有的 `(text) Tj` 标记，
          或用最后一层防御：正则合并所有空白字符并强行切取前 4000 字符，保证系统能够最低限度地读到文件内容，绝不在提取阶段发生物理 Crash。
    """
    try:
        from io import BytesIO
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(raw))
        pages = []
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                pages.append(page_text)
        return "\n".join(pages) if pages else ""
    except Exception:
        # Fallback: basic extraction for simple uncompressed PDFs
        text = raw.decode("latin-1", errors="ignore")
        chunks = re.findall(r"\(([^()]*)\)\s*Tj", text)
        if chunks:
            return "\n".join(chunks)
        return re.sub(r"\s+", " ", text)[:4000]


def _extract_docx_text(raw: bytes) -> str:
    """
    极速、无依赖的 Word (docx) 纯文本提取器。

    ⚡ 边界与性能思考：
        - 放弃引入复杂的 python-docx 等大型外部库，利用 DOCX 本质上是 zip 压缩包的特性，
          直接用内置 `ZipFile` 内存解压，高速读取其中承载正文的 `word/document.xml`。
        - 空间复杂度极佳：流式解压读取，避免了大段二进制文件的内存冗余复制。
        - 设计了二级 Fallback：优先采用 `<w:p>` 标签对段落进行物理分割；
          如果文档结构遭到破坏没有匹配到 paragraph，则降级为直接匹配全局 `<w:t>` 文本。
    """
    try:
        from io import BytesIO

        with ZipFile(BytesIO(raw)) as archive:
            xml = archive.read("word/document.xml").decode("utf-8", errors="replace")
    except (KeyError, BadZipFile) as exc:
        raise ValueError("Invalid DOCX document") from exc
    # Group text runs by paragraph.
    paragraphs = re.findall(r"<w:p[ >].*?</w:p>", xml, re.DOTALL)
    if paragraphs:
        lines = []
        for p in paragraphs:
            runs = re.findall(r"<w:t[^>]*>(.*?)</w:t>", p)
            line = "".join(_strip_xml(item) for item in runs).strip()
            if line:
                lines.append(line)
        return "\n".join(lines)
    # Fallback: flat extraction for malformed documents.
    runs = re.findall(r"<w:t[^>]*>(.*?)</w:t>", xml)
    return "\n".join(_strip_xml(item) for item in runs)


def _strip_xml(value: str) -> str:
    """清除并还原 XML 内部的基础转义标签（如 `&lt;` 转换为 `<` 等），防止乱码或特殊实体遗漏。"""
    return (
        value.replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
        .replace("&quot;", '"')
        .replace("&apos;", "'")
    )
