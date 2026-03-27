from io import BytesIO
from zipfile import ZipFile
import xml.etree.ElementTree as ET
from typing import Optional


def extract_text_from_file(filename: str, content: bytes) -> str:
    lower_name = filename.lower()
    if lower_name.endswith(".md") or lower_name.endswith(".txt"):
        return content.decode("utf-8", errors="ignore")
    if lower_name.endswith(".pdf"):
        return _extract_pdf_text(content)
    if lower_name.endswith(".docx"):
        return _extract_docx_text(content)
    raise ValueError("Unsupported file type. Expected pdf, docx, md, or txt.")


def _extract_pdf_text(content: bytes) -> str:
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError as exc:
        raise RuntimeError("PDF parsing requires the 'pypdf' extra dependency.") from exc

    reader = PdfReader(BytesIO(content))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    return text.strip()


def _extract_docx_text(content: bytes) -> str:
    try:
        with ZipFile(BytesIO(content)) as archive:
            xml_bytes = archive.read("word/document.xml")
    except Exception as exc:
        raise RuntimeError("Unable to parse DOCX file.") from exc

    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    root = ET.fromstring(xml_bytes)
    paragraphs = []
    for paragraph in root.findall(".//w:p", namespace):
        fragments = [node.text for node in paragraph.findall(".//w:t", namespace) if node.text]
        if fragments:
            paragraphs.append("".join(fragments))
    return "\n".join(paragraphs).strip()


def detect_language(text: str, fallback: str = "en") -> str:
    if any("\u4e00" <= char <= "\u9fff" for char in text):
        return "zh"
    return fallback


def first_non_empty_line(text: str) -> Optional[str]:
    for line in text.splitlines():
        value = line.strip()
        if value:
            return value
    return None
