from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
from typing import Any, Iterable

from docx import Document
from docx.document import Document as DocxDocument
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph


def _normalize_text(value: str) -> str:
    return " ".join(value.split()).strip()


def _iter_block_items(doc: DocxDocument) -> Iterable[Paragraph | Table]:
    body = doc.element.body
    for child in body.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, doc)
        elif isinstance(child, CT_Tbl):
            yield Table(child, doc)


def _paragraph_payload(paragraph: Paragraph) -> dict[str, Any] | None:
    text = _normalize_text(paragraph.text)
    if not text:
        return None
    style = paragraph.style.name if paragraph.style is not None else "Normal"
    kind = "heading" if style.lower().startswith("heading") else "paragraph"
    return {"kind": kind, "style": style, "text": text}


def _table_payload(table: Table) -> dict[str, Any] | None:
    rows = []
    for row in table.rows:
        cells = [_normalize_text(cell.text) for cell in row.cells]
        if any(cells):
            rows.append(cells)
    if not rows:
        return None
    return {"kind": "table", "rows": rows}


def extract_docx_structure(docx_path: str | Path, doc_id: str) -> dict[str, Any]:
    path = Path(docx_path)
    document = Document(path)
    elements: list[dict[str, Any]] = []
    rendered_lines: list[str] = []
    for block in _iter_block_items(document):
        if isinstance(block, Paragraph):
            payload = _paragraph_payload(block)
            if payload is None:
                continue
            elements.append(payload)
            label = payload["kind"].upper()
            if payload["kind"] == "heading":
                label = f"HEADING {payload['style'].split()[-1]}" if payload["style"] else "HEADING"
            rendered_lines.append(f"[{label}] {payload['text']}")
        else:
            payload = _table_payload(block)
            if payload is None:
                continue
            elements.append(payload)
            for row in payload["rows"]:
                if len(row) == 2:
                    rendered_lines.append(f"[TABLE ROW] {row[0]}: {row[1]}")
                else:
                    rendered_lines.append("[TABLE ROW] " + " | ".join(row))
    return {
        "doc_id": doc_id,
        "filename": path.name,
        "elements": elements,
        "text": "\n".join(rendered_lines).strip(),
    }


def extract_text_structure(text_path: str | Path, doc_id: str) -> dict[str, Any]:
    path = Path(text_path)
    text = path.read_text(encoding="utf-8")
    lines = [line.strip() for line in text.splitlines()]
    elements: list[dict[str, Any]] = []
    rendered_lines: list[str] = []
    for line in lines:
        if not line:
            continue
        elements.append({"kind": "paragraph", "style": "Normal", "text": line})
        rendered_lines.append(f"[PARAGRAPH] {line}")
    return {
        "doc_id": doc_id,
        "filename": path.name,
        "elements": elements,
        "text": "\n".join(rendered_lines).strip(),
    }


def extract_document_structure(path: str | Path, doc_id: str) -> dict[str, Any]:
    file_path = Path(path)
    if file_path.suffix.lower() == ".txt":
        return extract_text_structure(file_path, doc_id)
    return extract_docx_structure(file_path, doc_id)


def build_context(package_dir: str | Path, manifest: dict[str, Any]) -> dict[str, Any]:
    package_path = Path(package_dir)
    documents = []
    text_parts = []
    for entry in sorted(manifest["documents"], key=lambda item: (item["order"], item["doc_id"])):
        if package_path.name not in entry.get("included_in_variants", []):
            continue
        filename = entry.get("neutral_file_name") or entry.get("filename")
        doc_path = package_path / "documents" / filename
        structure = extract_document_structure(doc_path, entry["doc_id"])
        documents.append(
            {
                "doc_id": entry["doc_id"],
                "filename": filename,
                "source_file_name": entry.get("source_file_name"),
                "source_sha256": entry.get("source_sha256"),
                "order": entry["order"],
                "text": structure["text"],
                "elements": structure["elements"],
            }
        )
        text_parts.append(f"[DOCUMENT doc_id={entry['doc_id']}]")
        text_parts.append(f"=== DOCUMENT {entry['order']} | {filename} ===")
        if structure["text"]:
            text_parts.append(structure["text"])
        text_parts.append("[/DOCUMENT]")
        text_parts.append("")
    return {
        "case_id": manifest["case_id"],
        "package": package_path.name,
        "documents": documents,
        "text": "\n".join(text_parts).strip(),
    }


def write_context_files(package_dir: str | Path, manifest: dict[str, Any]) -> dict[str, Any]:
    package_path = Path(package_dir)
    context = build_context(package_path, manifest)
    (package_path / "context.json").write_text(json.dumps(context, ensure_ascii=False, indent=2), encoding="utf-8")
    (package_path / "context.txt").write_text(context["text"] + "\n", encoding="utf-8")
    return context
