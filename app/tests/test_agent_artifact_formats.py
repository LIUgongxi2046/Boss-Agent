import hashlib
import io
import os
from pathlib import Path
from uuid import uuid4

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.comments import Comment
from docx import Document
from pptx import Presentation
from pptx.util import Inches
from pptx.enum.shapes import MSO_SHAPE
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas

from agent_artifact_formats import FORMATS, create_format, create_runtime_format, parse_format, verify_format, verify_runtime_format
from agent_artifacts import read_verified_file, store_exact_file
from boss_comprehensive_simulation import populate
from boss_simulation_api import _context
from boss_source_access import require_current_business_source
from controls import ControlStore


@pytest.fixture
def documents(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    populate(store, "2026-10-28T10:00:00+08:00")
    with store.connect() as db:
        db.execute("BEGIN")
        context = _context(db)
        document = require_current_business_source(store, db, context["namespace"], context["owner_id"], "simulation-meeting-material")
    return [document]


@pytest.mark.parametrize("format_name", ["MARKDOWN", "PDF", "DOCX", "XLSX", "PPTX"])
def test_actual_file_reopens_with_sources_and_digest(tmp_path, documents, format_name):
    content = create_format(format_name, documents)
    suffix, _ = FORMATS[format_name]
    storage_key = str(uuid4()) + suffix
    path = tmp_path / storage_key
    path.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    verified = read_verified_file(tmp_path, storage_key, len(content), digest)
    assert verified == content
    verify_format(format_name, verified, documents)
    path.write_bytes(content + b"changed")
    with pytest.raises(ValueError, match="摘要"):
        read_verified_file(tmp_path, storage_key, len(content), digest)


def test_format_and_path_reject_invalid_values(tmp_path, documents):
    with pytest.raises(ValueError, match="格式"):
        create_format("UNKNOWN", documents)
    with pytest.raises(ValueError):
        read_verified_file(tmp_path, "../outside.pdf", 1, "invalid")


def test_pdf_rejects_additional_page_with_duplicate_source_content(documents):
    original = create_format("PDF", documents)
    reader = PdfReader(io.BytesIO(original), strict=True)
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    for page in reader.pages:
        writer.add_page(page)
    output = io.BytesIO()
    writer.write(output)
    with pytest.raises(ValueError, match="成果内容与来源不一致"):
        verify_format("PDF", output.getvalue(), documents)


@pytest.mark.parametrize("extra", ["table", "header", "notes", "slide_table"])
def test_generated_office_file_rejects_additional_content(documents, extra):
    if extra in {"table", "header"}:
        format_name = "DOCX"
        document = Document(io.BytesIO(create_format(format_name, documents)))
        if extra == "table":
            document.add_table(rows=1, cols=1).cell(0, 0).text = documents[0]["content"]
        else:
            document.sections[0].header.paragraphs[0].text = documents[0]["content"]
        output = io.BytesIO()
        document.save(output)
    else:
        format_name = "PPTX"
        presentation = Presentation(io.BytesIO(create_format(format_name, documents)))
        slide = presentation.slides[0]
        if extra == "notes":
            slide.notes_slide.notes_text_frame.text = documents[0]["content"]
        else:
            slide.shapes.add_table(1, 1, Inches(1), Inches(1), Inches(2), Inches(1)).table.cell(0, 0).text = documents[0]["content"]
        output = io.BytesIO()
        presentation.save(output)
    with pytest.raises(ValueError, match="成果内容与来源不一致"):
        verify_format(format_name, output.getvalue(), documents)


@pytest.mark.parametrize("format_name", ["DOCX", "PPTX"])
def test_runtime_brief_rejects_additional_office_content(documents, format_name):
    paragraphs = [documents[0]["content"]]
    original = create_runtime_format(format_name, paragraphs)
    output = io.BytesIO()
    if format_name == "DOCX":
        document = Document(io.BytesIO(original))
        document.add_table(rows=1, cols=1).cell(0, 0).text = paragraphs[0]
        document.save(output)
    else:
        presentation = Presentation(io.BytesIO(original))
        presentation.slides[0].notes_slide.notes_text_frame.text = paragraphs[0]
        presentation.save(output)
    with pytest.raises(ValueError, match="会议简报内容与登记内容不一致"):
        verify_runtime_format(format_name, output.getvalue(), paragraphs)


@pytest.mark.parametrize("format_name", ["DOCX", "PPTX", "PDF"])
@pytest.mark.parametrize("runtime", [False, True])
def test_generated_document_rejects_added_image(documents, format_name, runtime):
    image_path = Path(__file__).resolve().parents[2] / "Boss-Agent-Desktop-Complete-v7/qa/N02-1280w.png"
    paragraphs = [documents[0]["content"]]
    original = create_runtime_format(format_name, paragraphs) if runtime else create_format(format_name, documents)
    output = io.BytesIO()
    if format_name == "DOCX":
        document = Document(io.BytesIO(original))
        document.add_picture(str(image_path), width=Inches(1))
        document.save(output)
    elif format_name == "PPTX":
        presentation = Presentation(io.BytesIO(original))
        presentation.slides[0].shapes.add_picture(str(image_path), Inches(1), Inches(1), width=Inches(1))
        presentation.save(output)
    else:
        overlay = io.BytesIO()
        layer = canvas.Canvas(overlay)
        layer.drawImage(str(image_path), 10, 10, width=20, height=20)
        layer.save()
        reader = PdfReader(io.BytesIO(original), strict=True)
        reader.pages[0].merge_page(PdfReader(io.BytesIO(overlay.getvalue())).pages[0])
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        writer.write(output)
    with pytest.raises(ValueError, match="会议简报内容与登记内容不一致" if runtime else "成果内容与来源不一致"):
        if runtime:
            verify_runtime_format(format_name, output.getvalue(), paragraphs)
        else:
            verify_format(format_name, output.getvalue(), documents)


def test_generated_docx_rejects_header_image(documents):
    image_path = Path(__file__).resolve().parents[2] / "Boss-Agent-Desktop-Complete-v7/qa/N02-1280w.png"
    document = Document(io.BytesIO(create_format("DOCX", documents)))
    document.sections[0].header.paragraphs[0].add_run().add_picture(str(image_path), width=Inches(1))
    output = io.BytesIO()
    document.save(output)
    with pytest.raises(ValueError, match="成果内容与来源不一致"):
        verify_format("DOCX", output.getvalue(), documents)


@pytest.mark.parametrize("format_name", ["PPTX", "PDF"])
def test_generated_document_rejects_added_vector_object(documents, format_name):
    original = create_format(format_name, documents)
    output = io.BytesIO()
    if format_name == "PPTX":
        presentation = Presentation(io.BytesIO(original))
        presentation.slides[0].shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(1), Inches(1), Inches(1), Inches(1))
        presentation.save(output)
    else:
        overlay = io.BytesIO()
        layer = canvas.Canvas(overlay)
        layer.rect(10, 10, 20, 20)
        layer.save()
        reader = PdfReader(io.BytesIO(original), strict=True)
        reader.pages[0].merge_page(PdfReader(io.BytesIO(overlay.getvalue())).pages[0])
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        writer.write(output)
    with pytest.raises(ValueError, match="成果内容与来源不一致"):
        verify_format(format_name, output.getvalue(), documents)


@pytest.mark.parametrize("runtime", [False, True])
@pytest.mark.parametrize("extra", ["chart", "comment", "header", "hidden"])
def test_generated_workbook_rejects_additional_objects(documents, runtime, extra):
    paragraphs = [documents[0]["content"]]
    original = create_runtime_format("XLSX", paragraphs) if runtime else create_format("XLSX", documents)
    book = load_workbook(io.BytesIO(original))
    sheet = book.active
    if extra == "chart":
        chart = BarChart()
        chart.add_data(Reference(sheet, min_col=1, min_row=1, max_row=1))
        sheet.add_chart(chart, "G2")
    elif extra == "comment":
        sheet["A1"].comment = Comment(documents[0]["content"], "模拟资料")
    elif extra == "header":
        sheet.oddHeader.center.text = documents[0]["title"]
    else:
        sheet.row_dimensions[1].hidden = True
    output = io.BytesIO()
    book.save(output)
    book.close()
    with pytest.raises(ValueError, match="会议简报内容与登记内容不一致" if runtime else "成果内容与来源不一致"):
        if runtime:
            verify_runtime_format("XLSX", output.getvalue(), paragraphs)
        else:
            verify_format("XLSX", output.getvalue(), documents)


@pytest.mark.parametrize("runtime", [False, True])
@pytest.mark.parametrize("extra", [b"\n\n---\n", b"\n\n<div>additional</div>\n", b"\n\n```\nadditional\n```\n"])
def test_generated_markdown_rejects_extra_blocks(documents, runtime, extra):
    paragraphs = [documents[0]["content"]]
    original = create_runtime_format("MARKDOWN", paragraphs) if runtime else create_format("MARKDOWN", documents)
    with pytest.raises(ValueError, match="会议简报内容与登记内容不一致" if runtime else "成果内容与来源不一致"):
        if runtime:
            verify_runtime_format("MARKDOWN", original + extra, paragraphs)
        else:
            verify_format("MARKDOWN", original + extra, documents)


def test_file_read_rejects_nonregular_and_unexpected_size(tmp_path):
    key = str(uuid4()) + ".md"
    path = tmp_path / key
    os.mkfifo(path)
    with pytest.raises(ValueError, match="大小"):
        read_verified_file(tmp_path, key, 1, "invalid")
    path.unlink()
    path.write_bytes(b"content")
    with pytest.raises(ValueError, match="大小"):
        read_verified_file(tmp_path, key, 1, "invalid")


@pytest.mark.parametrize("format_name", ["MARKDOWN", "PDF", "DOCX", "XLSX", "PPTX"])
def test_exact_file_recovery_preserves_existing_bytes(tmp_path, documents, format_name):
    content = create_format(format_name, documents)
    storage_key = str(uuid4()) + FORMATS[format_name][0]
    assert store_exact_file(tmp_path, storage_key, content) == content
    assert store_exact_file(tmp_path, storage_key, content) == content
    path = tmp_path / storage_key
    damaged = content[:len(content) // 2]
    path.write_bytes(damaged)
    with pytest.raises(ValueError, match="摘要"):
        store_exact_file(tmp_path, storage_key, content)
    assert path.read_bytes() == damaged


def test_existing_xlsx_with_formula_is_readable(tmp_path, documents):
    workbook = Workbook()
    workbook.active["A1"] = documents[0]["content"]
    workbook.active["B1"] = "=LEN(A1)"
    workbook.create_sheet("来源")["A1"] = documents[0]["source_id"]
    storage_key = str(uuid4()) + ".xlsx"
    path = tmp_path / storage_key
    workbook.save(path)
    workbook.close()
    content = path.read_bytes()
    assert read_verified_file(tmp_path, storage_key, len(content), hashlib.sha256(content).hexdigest()) == content
    parsed = parse_format("XLSX", content)
    assert len(parsed["sheets"]) == 2 and parsed["sheets"][0]["rows"][0][1] == {"value": "=LEN(A1)", "type": "f"}
    assert parsed["sheets"][1]["rows"][0][0]["value"] == documents[0]["source_id"]


@pytest.mark.parametrize("format_name", ["MARKDOWN", "PDF", "DOCX", "XLSX", "PPTX"])
def test_general_parser_extracts_actual_source(documents, format_name):
    parsed = parse_format(format_name, create_format(format_name, documents))
    if format_name in {"MARKDOWN", "DOCX"}:
        text = "".join(item.get("text", "") for item in parsed["elements"])
    elif format_name == "PDF":
        text = "".join(page["text"] for page in parsed["pages"])
    elif format_name == "XLSX":
        text = "".join(str(cell["value"]) for sheet in parsed["sheets"] for row in sheet["rows"] for cell in row)
    else:
        text = "".join(item.get("text", "") for slide in parsed["slides"] for item in slide["elements"])
    normalized = "".join(text.split())
    for value in (documents[0]["title"], documents[0]["source_id"], documents[0]["version"], documents[0]["content"]):
        assert "".join(value.split()) in normalized


def test_general_parser_reads_docx_and_pptx_tables(documents):
    source = documents[0]
    doc = Document()
    doc.add_paragraph(source["title"])
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = source["source_id"]
    table.cell(0, 1).text = source["content"]
    output = io.BytesIO()
    doc.save(output)
    parsed = parse_format("DOCX", output.getvalue())
    assert parsed["elements"][1]["rows"] == [[source["source_id"], source["content"]]]
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    table = slide.shapes.add_table(1, 2, Inches(1), Inches(1), Inches(6), Inches(2)).table
    table.cell(0, 0).text = source["source_id"]
    table.cell(0, 1).text = source["title"]
    group = slide.shapes.add_group_shape()
    group.shapes.add_textbox(Inches(1), Inches(3), Inches(6), Inches(1)).text_frame.text = source["content"]
    output = io.BytesIO()
    presentation.save(output)
    parsed = parse_format("PPTX", output.getvalue())
    assert parsed["slides"][0]["elements"][0]["rows"] == [[source["source_id"], source["title"]]]
    assert parsed["slides"][0]["elements"][1]["text"] == source["content"]


def test_general_parser_reads_document_headers_footers_and_presentation_notes(documents):
    source = documents[0]
    document = Document()
    document.add_paragraph(source["content"])
    document.sections[0].header.paragraphs[0].text = source["title"]
    document.sections[0].footer.paragraphs[0].text = source["source_id"]
    output = io.BytesIO()
    document.save(output)
    parsed = parse_format("DOCX", output.getvalue())
    assert parsed["sections"][0]["header"][0]["text"] == source["title"]
    assert parsed["sections"][0]["footer"][0]["text"] == source["source_id"]
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    slide.notes_slide.notes_text_frame.text = source["content"]
    output = io.BytesIO()
    presentation.save(output)
    parsed = parse_format("PPTX", output.getvalue())
    assert parsed["slides"][0]["notes"] == source["content"]
