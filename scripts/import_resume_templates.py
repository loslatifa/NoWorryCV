"""Distill local DOCX layouts into versioned, content-free flow templates.

Original files are read-only. Photos, example text and fixed text boxes are not
copied; font hierarchy, colors, spacing and section order drive both exporters.
"""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "backend/app/assets/resume_templates/catalog.json"
NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
}
SECTIONS = {
    "education": ("教育经历", "教育背景"),
    "experience": ("实习经历", "实习经验", "实践经历", "工作经历", "工作经验"),
    "projects": ("项目经历", "项目经验", "科研经历"),
    "skills": ("个人技能", "技能特长", "技能证书", "其他技能", "荣誉技能"),
}


def color(value):
    if not re.fullmatch(r"[0-9a-fA-F]{6}", value or ""):
        return False
    components = [int(value[index:index + 2], 16) for index in (0, 2, 4)]
    return max(components) - min(components) > 25 and min(components) < 210


def extract(path):
    raw = path.read_bytes()
    with ZipFile(path) as archive:
        info = archive.getinfo("word/document.xml")
        if info.file_size > 16 * 1024 * 1024:
            raise ValueError("document.xml exceeds import size limit")
        root = ET.fromstring(archive.read(info))
    parents = {child: parent for parent in root.iter() for child in parent}
    w = "{" + NS["w"] + "}"
    paragraphs = []
    for sequence, paragraph in enumerate(root.findall(".//w:p", NS)):
        if paragraph.find(".//w:p", NS) is not None:
            continue
        chain, node = [], paragraph
        while node in parents:
            node = parents[node]
            chain.append(node)
        if any(node.tag == "{" + NS["mc"] + "}Fallback" for node in chain):
            continue
        text = "".join(node.text or "" for node in paragraph.findall(".//w:t", NS)).strip()
        if not text:
            continue
        anchor = next((node for node in chain if node.tag == "{" + NS["wp"] + "}anchor"), None)
        offset = anchor.find("wp:positionV/wp:posOffset", NS) if anchor is not None else None
        position = int(offset.text) if offset is not None and offset.text else sequence * 1000
        paragraphs.append((position, sequence, text, paragraph))
    paragraphs.sort(key=lambda item: (item[0], item[1]))
    colors, fills, fonts, sizes = Counter(), Counter(), Counter(), Counter()
    for node in root.findall(".//w:color", NS):
        value = node.get(w + "val", "").upper()
        if color(value):
            colors[value] += 1
    for node in root.findall(".//a:solidFill/a:srgbClr", NS):
        value = node.get("val", "").upper()
        if color(value):
            fills[value] += 1
    for node in root.findall(".//w:rFonts", NS):
        value = node.get(w + "eastAsia")
        if value and not value.startswith("+"):
            fonts[value] += 1
    for node in root.findall(".//w:sz", NS):
        value = float(node.get(w + "val", "20")) / 2
        if 9 <= value <= 12:
            sizes[value] += 1
    accent = (fills or colors).most_common(1)[0][0] if fills or colors else "262626"
    headings, white_headings, title_sizes, alignments, order = [], 0, [], [], []
    for _, _, text, paragraph in paragraphs:
        normalized = re.sub(r"\s+", "", text)
        key = next((key for key, terms in SECTIONS.items()
                    if len(normalized) < 32 and any(term in normalized for term in terms)), None)
        paragraph_sizes = [float(node.get(w + "val", "20")) / 2
                           for node in paragraph.findall(".//w:sz", NS)]
        if key:
            if key not in order:
                order.append(key)
            headings.extend(value for value in paragraph_sizes if 10 <= value <= 16)
            if any(node.get(w + "val", "").upper() == "FFFFFF"
                   for node in paragraph.findall(".//w:color", NS)):
                white_headings += 1
        elif re.fullmatch(r"[\u4e00-\u9fffXx]{2,8}", normalized) and paragraph_sizes:
            size = max(paragraph_sizes)
            if 15 <= size <= 36:
                title_sizes.append(min(size, 24))
                alignment = paragraph.find("w:pPr/w:jc", NS)
                alignments.append(alignment.get(w + "val") if alignment is not None else "left")
    for key in ("education", "experience", "projects", "skills"):
        if key not in order:
            order.append(key)
    section = root.find(".//w:sectPr", NS)
    margins = section.find("w:pgMar", NS) if section is not None else None
    margin_x = max(28, min(65, int(margins.get(w + "left", "720")) / 20)) if margins is not None else 36
    margin_y = max(28, min(55, int(margins.get(w + "top", "720")) / 20)) if margins is not None else 36
    number = re.match(r"\d+", path.stem)
    slug = number.group() if number else sha256(path.stem.encode()).hexdigest()[:6]
    if "双页" in path.stem:
        slug += "_two"
    digest = sha256(raw).hexdigest()
    return {
        "id": "user_{0}_{1}".format(slug, digest[:8]),
        "name": path.stem.replace("-互联网大厂极简简历", " · 极简简历"),
        "source_filename": path.name,
        "source_sha256": digest,
        "active": True,
        "adaptation": "flow",
        "description": "保留源模板配色与文字层次，自动分页的流式适配版",
        "suggested_pages": 2 if "双页" in path.stem else 1,
        "accent": accent,
        "font": fonts.most_common(1)[0][0] if fonts else "微软雅黑",
        "body_size": sizes.most_common(1)[0][0] if sizes else 10,
        "title_size": max(title_sizes) if title_sizes else 20,
        "heading_size": Counter(headings).most_common(1)[0][0] if headings else 12,
        "title_align": "center" if alignments and alignments[0] == "center" else "left",
        "heading_bar": white_headings > 0 or sum(
            node.get(w + "val", "").upper() == "FFFFFF"
            for node in root.findall(".//w:color", NS)
        ) >= 20,
        "section_gap": 7 if white_headings else 6,
        "margin_x": margin_x,
        "margin_y": margin_y,
        "section_order": ["summary"] + order,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", type=Path, default=CATALOG)
    args = parser.parse_args()
    if not args.directory.is_dir():
        parser.error("Template directory does not exist")
    imported, issues = [], []
    for path in sorted(args.directory.iterdir()):
        if path.name.startswith((".", "~$")):
            continue
        if path.suffix.lower() != ".docx":
            issues.append({"filename": path.name, "reason": "仅支持导入 DOCX 模板"})
            continue
        try:
            imported.append(extract(path))
        except (OSError, ValueError, KeyError, BadZipFile, ET.ParseError):
            issues.append({"filename": path.name, "reason": "文件无法作为 DOCX 模板读取"})
    if not imported:
        parser.error("No usable DOCX templates found")
    previous = json.loads(args.output.read_text()).get("templates", []) if args.output.exists() else []
    current_ids = {item["id"] for item in imported}
    # Keep past style versions addressable by existing runs and saved snapshots.
    retired = [{**item, "active": False} for item in previous if item["id"] not in current_ids]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"templates": imported + retired, "issues": issues}, ensure_ascii=False, indent=2) + "\n")
    print("Imported {0} templates; retained {1} previous versions; skipped {2} entries.".format(len(imported), len(retired), len(issues)))
    for issue in issues:
        print("{filename}: {reason}".format(**issue))


if __name__ == "__main__":
    main()
