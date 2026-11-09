import io
from datetime import date, datetime, time
from xml.sax.saxutils import escape

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph as DocxParagraph
from markdown_it import MarkdownIt
from openpyxl import Workbook, load_workbook
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.enum.dml import MSO_FILL_TYPE
from pptx.util import Inches
from pypdf import PdfReader
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer


FORMATS = {
    "DOCX": (".docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    "MARKDOWN": (".md", "text/markdown"),
    "PDF": (".pdf", "application/pdf"),
    "XLSX": (".xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    "PPTX": (".pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
}


def _slide_elements(shapes):
    result = []
    for shape in shapes:
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            result.extend(_slide_elements(shape.shapes))
        elif shape.has_table:
            result.append({"type": "table", "rows": [[cell.text for cell in row.cells] for row in shape.table.rows]})
        elif shape.has_text_frame:
            result.append({"type": "text", "text": shape.text_frame.text})
    return result


def _docx_elements(container):
    elements = []
    for item in container.iter_inner_content():
        if isinstance(item, DocxParagraph):
            elements.append({"type": "paragraph", "text": item.text})
        elif isinstance(item, Table):
            elements.append({"type": "table", "rows": [[cell.text for cell in row.cells] for row in item.rows]})
    return elements


def _docx_extra_content(document):
    if document.element.xpath(".//w:drawing | .//w:pict | .//w:object | .//w:altChunk | .//w:sdt | .//w:customXml"):
        return True
    for section in document.sections:
        for part in (section.header, section.footer, section.first_page_header, section.first_page_footer, section.even_page_header, section.even_page_footer):
            if part._element.xpath(".//w:drawing | .//w:pict | .//w:object | .//w:altChunk | .//w:sdt | .//w:customXml") or any(item["type"] == "table" or item["text"] for item in _docx_elements(part)):
                return True
    return False


def _pdf_extra_content(reader):
    allowed = {b"BT", b"ET", b"Q", b"T*", b"TL", b"Tf", b"Tj", b"Tm", b"cm", b"q", b"rg"}
    if reader.attachments:
        return True
    for page in reader.pages:
        if page.get("/Annots") or any(operator not in allowed for _, operator in page.get_contents().operations):
            return True
    return False


def _slide_extra_content(slide):
    if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None and slide.notes_slide.notes_text_frame.text:
        return True
    return any(shape.shape_type != MSO_SHAPE_TYPE.TEXT_BOX or shape.fill.type == MSO_FILL_TYPE.PICTURE for shape in slide.shapes)


def _xlsx_extra_content(sheet):
    if sheet._images or sheet._charts or sheet.sheet_state != "visible":
        return True
    if any(dimension.hidden for dimension in sheet.row_dimensions.values()) or any(dimension.hidden for dimension in sheet.column_dimensions.values()):
        return True
    if any(cell.comment is not None or cell.hyperlink is not None for row in sheet.iter_rows() for cell in row):
        return True
    return any(getattr(getattr(sheet, name), side).text for name in ("oddHeader", "oddFooter", "evenHeader", "evenFooter", "firstHeader", "firstFooter") for side in ("left", "center", "right"))


def parse_format(format_name, content):
    if format_name not in FORMATS or not isinstance(content, bytes) or not content:
        raise ValueError("成果格式或内容无效")
    if format_name == "MARKDOWN":
        tokens = MarkdownIt("commonmark").parse(content.decode("utf-8"))
        return {"format": format_name, "elements": [{"type": token.type, "text": token.content} for token in tokens if token.type in {"inline", "code_block", "fence", "html_block"}]}
    if format_name == "DOCX":
        document = Document(io.BytesIO(content))
        sections = [{"section": index, "header": _docx_elements(section.header), "footer": _docx_elements(section.footer),
                     "first_page_header": _docx_elements(section.first_page_header), "first_page_footer": _docx_elements(section.first_page_footer),
                     "even_page_header": _docx_elements(section.even_page_header), "even_page_footer": _docx_elements(section.even_page_footer)}
                    for index, section in enumerate(document.sections, 1)]
        return {"format": format_name, "elements": _docx_elements(document), "sections": sections}
    if format_name == "PDF":
        reader = PdfReader(io.BytesIO(content), strict=True)
        pages = []
        for index, page in enumerate(reader.pages, 1):
            text = page.extract_text()
            pages.append({"page": index, "text": text, "text_available": bool(text.strip())})
        return {"format": format_name, "pages": pages}
    if format_name == "XLSX":
        book = load_workbook(io.BytesIO(content), read_only=True, data_only=False)
        sheets = []
        for sheet in book.worksheets:
            rows = []
            for row in sheet.iter_rows():
                cells = []
                for cell in row:
                    value = cell.value
                    if isinstance(value, (datetime, date, time)):
                        value = value.isoformat()
                    cells.append({"value": value, "type": cell.data_type})
                rows.append(cells)
            sheets.append({"name": sheet.title, "rows": rows})
        book.close()
        return {"format": format_name, "sheets": sheets}
    presentation = Presentation(io.BytesIO(content))
    return {"format": format_name, "slides": [{"slide": index, "elements": _slide_elements(slide.shapes),
            "notes": slide.notes_slide.notes_text_frame.text if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None else None}
            for index, slide in enumerate(presentation.slides, 1)]}


def meeting_paragraphs(documents):
    result = ["会议资料简报", "资料性质：SIMULATED"]
    for item in documents:
        result.extend([item["title"], "来源：" + item["source_id"] + "；版本：" + item["version"], item["content"]])
    return result


def create_format(format_name, documents):
    if format_name not in FORMATS or not documents:
        raise ValueError("成果格式或来源无效")
    paragraphs = meeting_paragraphs(documents)
    output = io.BytesIO()
    if format_name == "DOCX":
        document = Document()
        document.add_heading(paragraphs[0], level=0)
        document.add_paragraph(paragraphs[1])
        for index in range(2, len(paragraphs), 3):
            document.add_heading(paragraphs[index], level=1)
            document.add_paragraph(paragraphs[index + 1])
            document.add_paragraph(paragraphs[index + 2])
        document.save(output)
    elif format_name == "MARKDOWN":
        parts = ["# 会议资料简报\n", "资料性质：SIMULATED\n"]
        for index, item in enumerate(documents, 1):
            text = "\n".join([item["title"], "来源：" + item["source_id"] + "；版本：" + item["version"], item["content"]])
            parts.append("## 资料 " + str(index) + "\n\n" + "\n".join("    " + line for line in text.split("\n")) + "\n")
        output.write("\n".join(parts).encode("utf-8"))
    elif format_name == "PDF":
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        style = ParagraphStyle("meeting", fontName="STSong-Light", fontSize=11, leading=17, wordWrap="CJK")
        story = []
        for text in paragraphs:
            story.extend([Paragraph(escape(text).replace("\n", "<br/>"), style), Spacer(1, 7)])
        SimpleDocTemplate(output).build(story)
    elif format_name == "XLSX":
        book = Workbook()
        sheet = book.active
        sheet.title = "会议资料"
        sheet.append(["资料标题", "来源编号", "版本", "正文", "资料性质"])
        for item in documents:
            sheet.append([item["title"], item["source_id"], item["version"], item["content"], "SIMULATED"])
            for cell in sheet[sheet.max_row]:
                cell.data_type = "s"
        book.save(output)
        book.close()
    else:
        presentation = Presentation()
        for item in documents:
            slide = presentation.slides.add_slide(presentation.slide_layouts[6])
            title = slide.shapes.add_textbox(Inches(0.5), Inches(0.4), Inches(9), Inches(0.6))
            title.text_frame.text = "会议资料简报：" + item["title"]
            body = slide.shapes.add_textbox(Inches(0.5), Inches(1.2), Inches(9), Inches(5.5))
            body.text_frame.text = "资料性质：SIMULATED\n来源：" + item["source_id"] + "；版本：" + item["version"] + "\n" + item["content"]
        presentation.save(output)
    content = output.getvalue()
    verify_format(format_name, content, documents)
    return content


def verify_format(format_name, content, documents=None):
    if format_name not in FORMATS or not isinstance(content, bytes) or not content:
        raise ValueError("成果格式或内容无效")
    expected = meeting_paragraphs(documents) if documents is not None else None
    if format_name == "DOCX":
        document = Document(io.BytesIO(content))
        actual = _docx_elements(document)
        if expected is not None and (actual != [{"type": "paragraph", "text": item} for item in expected] or _docx_extra_content(document)):
            raise ValueError("成果内容与来源不一致")
    elif format_name == "MARKDOWN":
        tokens = MarkdownIt("commonmark").parse(content.decode("utf-8"))
        blocks = [token.content.rstrip("\n") for token in tokens if token.type == "code_block"]
        inline = [token.content for token in tokens if token.type == "inline"]
        if not tokens:
            raise ValueError("Markdown 缺少资料内容")
        if expected is not None:
            wanted = ["\n".join(expected[index:index + 3]).rstrip("\n") for index in range(2, len(expected), 3)]
            structure = [(token.type, token.tag) for token in tokens]
            expected_structure = [("heading_open", "h1"), ("inline", ""), ("heading_close", "h1"), ("paragraph_open", "p"), ("inline", ""), ("paragraph_close", "p")]
            expected_structure += [(kind, tag) for _ in documents for kind, tag in (("heading_open", "h2"), ("inline", ""), ("heading_close", "h2"), ("code_block", "code"))]
            if structure != expected_structure or blocks != wanted or inline != ["会议资料简报", "资料性质：SIMULATED"] + ["资料 " + str(index) for index in range(1, len(documents) + 1)]:
                raise ValueError("成果内容与来源不一致")
    elif format_name == "PDF":
        reader = PdfReader(io.BytesIO(content), strict=True)
        extracted = "".join(page.extract_text() for page in reader.pages)
        normalized = "".join(extracted.split())
        if not normalized:
            raise ValueError("PDF 缺少文字内容")
        if expected is not None:
            if _pdf_extra_content(reader) or normalized != "".join("".join(item.split()) for item in expected):
                raise ValueError("成果内容与来源不一致")
    elif format_name == "XLSX":
        book = load_workbook(io.BytesIO(content), read_only=documents is None, data_only=False)
        if not book.sheetnames or documents is not None and book.sheetnames != ["会议资料"]:
            raise ValueError("成果工作表无效")
        cells = list(book.active.iter_rows())
        if documents is not None and _xlsx_extra_content(book.active):
            raise ValueError("成果内容与来源不一致")
        if documents is not None and any(cell.data_type == "f" for row in cells for cell in row):
            raise ValueError("成果含有公式")
        rows = [tuple(cell.value for cell in row) for row in cells]
        book.close()
        if documents is not None and (len(rows) < 2 or rows[0] != ("资料标题", "来源编号", "版本", "正文", "资料性质")):
            raise ValueError("成果表头无效")
        if documents is not None and rows[1:] != [(item["title"], item["source_id"], item["version"], item["content"], "SIMULATED") for item in documents]:
            raise ValueError("成果内容与来源不一致")
    else:
        slides = Presentation(io.BytesIO(content)).slides
        if not slides:
            raise ValueError("成果没有演示页面")
        if documents is not None:
            actual = [[item["text"] for item in _slide_elements(slide.shapes) if item["type"] == "text"] for slide in slides]
            wanted = [["会议资料简报：" + item["title"], "资料性质：SIMULATED\n来源：" + item["source_id"] + "；版本：" + item["version"] + "\n" + item["content"]] for item in documents]
            if actual != wanted or any(_slide_extra_content(slide) for slide in slides):
                raise ValueError("成果内容与来源不一致")


def create_runtime_format(format_name, paragraphs):
    if format_name not in FORMATS or not isinstance(paragraphs, list) or not paragraphs or any(not isinstance(item, str) or not item.strip() for item in paragraphs):
        raise ValueError("会议简报内容无效")
    output = io.BytesIO()
    if format_name == "MARKDOWN":
        output.write("\n\n".join("## 内容 " + str(index) + "\n\n" + "\n".join("    " + line for line in item.split("\n")) for index, item in enumerate(paragraphs, 1)).encode("utf-8"))
    elif format_name == "DOCX":
        document = Document()
        for item in paragraphs:
            document.add_paragraph(item)
        document.save(output)
    elif format_name == "PDF":
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        style = ParagraphStyle("meeting_runtime", fontName="STSong-Light", fontSize=11, leading=17, wordWrap="CJK")
        story = []
        for item in paragraphs:
            story.extend([Paragraph(escape(item).replace("\n", "<br/>"), style), Spacer(1, 7)])
        SimpleDocTemplate(output).build(story)
    elif format_name == "XLSX":
        book = Workbook()
        sheet = book.active
        sheet.title = "会议简报"
        for item in paragraphs:
            sheet.append([item])
            sheet.cell(sheet.max_row, 1).data_type = "s"
        book.save(output)
        book.close()
    else:
        presentation = Presentation()
        for item in paragraphs:
            slide = presentation.slides.add_slide(presentation.slide_layouts[6])
            slide.shapes.add_textbox(Inches(0.5), Inches(0.5), Inches(9), Inches(6)).text_frame.text = item
        presentation.save(output)
    content = output.getvalue()
    verify_runtime_format(format_name, content, paragraphs)
    return content


def verify_runtime_format(format_name, content, paragraphs):
    if format_name not in FORMATS or not isinstance(content, bytes) or not content or not isinstance(paragraphs, list) or not paragraphs:
        raise ValueError("会议简报格式或内容无效")
    if format_name == "MARKDOWN":
        tokens = MarkdownIt("commonmark").parse(content.decode("utf-8"))
        structure = [(token.type, token.tag) for token in tokens]
        expected_structure = [(kind, tag) for _ in paragraphs for kind, tag in (("heading_open", "h2"), ("inline", ""), ("heading_close", "h2"), ("code_block", "code"))]
        headings = [token.content for token in tokens if token.type == "inline"]
        if structure != expected_structure or headings != ["内容 " + str(index) for index in range(1, len(paragraphs) + 1)]:
            raise ValueError("会议简报内容与登记内容不一致")
        actual = [token.content.rstrip("\n") for token in tokens if token.type == "code_block"]
        expected = [item.rstrip("\n") for item in paragraphs]
    elif format_name == "DOCX":
        document = Document(io.BytesIO(content))
        actual = _docx_elements(document)
        expected = [{"type": "paragraph", "text": item} for item in paragraphs]
        if _docx_extra_content(document):
            raise ValueError("会议简报内容与登记内容不一致")
    elif format_name == "PDF":
        reader = PdfReader(io.BytesIO(content), strict=True)
        if _pdf_extra_content(reader):
            raise ValueError("会议简报内容与登记内容不一致")
        actual = "".join("".join(page.extract_text().split()) for page in reader.pages)
        expected = "".join("".join(item.split()) for item in paragraphs)
    elif format_name == "XLSX":
        book = load_workbook(io.BytesIO(content), read_only=False, data_only=False)
        if book.sheetnames != ["会议简报"]:
            raise ValueError("会议简报工作表无效")
        rows = list(book.active.iter_rows())
        if _xlsx_extra_content(book.active):
            raise ValueError("会议简报内容与登记内容不一致")
        if any(len(row) != 1 or row[0].data_type == "f" for row in rows):
            raise ValueError("会议简报单元格无效")
        actual = [row[0].value for row in rows]
        expected = paragraphs
        book.close()
    else:
        slides = Presentation(io.BytesIO(content)).slides
        actual = [[item["text"] for item in _slide_elements(slide.shapes) if item["type"] == "text"] for slide in slides]
        expected = [[item] for item in paragraphs]
        if any(_slide_extra_content(slide) for slide in slides):
            raise ValueError("会议简报内容与登记内容不一致")
    if actual != expected:
        raise ValueError("会议简报内容与登记内容不一致")
