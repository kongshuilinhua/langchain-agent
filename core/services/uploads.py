from __future__ import annotations

import base64
import binascii
import re
import uuid
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from sqlalchemy.orm import Session

from core.config import get_settings
from core.db.models import Upload

IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
TEXT_TYPES = {"text/plain", "text/markdown", "application/markdown", "text/csv"}
DOC_TYPES = TEXT_TYPES | {"application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}


def create_upload(db: Session, *, workspace_id: int, user_id: int, filename: str, content_type: str, content_base64: str) -> Upload:
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
    suffix = Path(filename).suffix.lower()
    if content_type in TEXT_TYPES or suffix in {".txt", ".md", ".markdown", ".csv"}:
        return raw.decode("utf-8", errors="replace")
    if content_type == "application/pdf" or suffix == ".pdf":
        return _extract_pdf_text(raw)
    if content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document" or suffix == ".docx":
        return _extract_docx_text(raw)
    raise ValueError("Unsupported document type")


def sanitize_extracted_text(text: str) -> str:
    return str(text or "").replace("\x00", "")


def _decode_base64(content_base64: str) -> bytes:
    payload = content_base64.split(",", 1)[1] if content_base64.startswith("data:") and "," in content_base64 else content_base64
    try:
        return base64.b64decode(payload, validate=True)
    except binascii.Error as exc:
        raise ValueError("Invalid base64 upload payload") from exc


def _kind(content_type: str, filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if content_type in IMAGE_TYPES or suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        return "image"
    if content_type in DOC_TYPES or suffix in {".txt", ".md", ".markdown", ".csv", ".pdf", ".docx"}:
        return "document"
    return "unknown"


def _extract_pdf_text(raw: bytes) -> str:
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
    return (
        value.replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
        .replace("&quot;", '"')
        .replace("&apos;", "'")
    )
