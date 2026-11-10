import csv
import io
from pathlib import Path
from zipfile import BadZipFile

from fastapi import HTTPException, UploadFile

SUPPORTED_EXTENSIONS = {".txt", ".md", ".csv", ".pdf", ".docx"}


async def extract_document(upload: UploadFile, max_bytes: int) -> tuple[str, str, str]:
    filename = Path((upload.filename or "").replace("\\", "/")).name
    extension = Path(filename).suffix.lower()
    if not filename or extension not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=415, detail={"code": "unsupported_file_type"})

    content = await upload.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail={"code": "file_too_large"})
    if not content:
        raise HTTPException(status_code=422, detail={"code": "empty_file"})

    try:
        if extension in {".txt", ".md", ".csv"}:
            text = content.decode("utf-8-sig")
            if extension == ".csv":
                rows = csv.reader(io.StringIO(text))
                text = "\n".join(", ".join(row) for row in rows)
        elif extension == ".pdf":
            import fitz

            with fitz.open(stream=content, filetype="pdf") as document:
                text = "\n".join(page.get_text("text") for page in document)
        else:
            from docx import Document

            document = Document(io.BytesIO(content))
            paragraphs = [paragraph.text for paragraph in document.paragraphs if paragraph.text]
            tables = [
                " | ".join(cell.text for cell in row.cells)
                for table in document.tables
                for row in table.rows
            ]
            text = "\n".join(paragraphs + tables)
    except (UnicodeDecodeError, csv.Error, OSError, ValueError, BadZipFile, KeyError):
        raise HTTPException(status_code=422, detail={"code": "document_extraction_failed"}) from None

    if not text.strip():
        raise HTTPException(status_code=422, detail={"code": "no_extractable_text"})
    media_type = upload.content_type or "application/octet-stream"
    return filename, text, media_type
