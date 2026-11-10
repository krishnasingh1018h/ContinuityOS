import asyncio
from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile

from backend.app.parsers import extract_document


def test_markdown_parser_preserves_utf8_and_rejects_path_components():
    upload = UploadFile(
        file=BytesIO("AURORA — synthetic project\nSecond line".encode()),
        filename="../../synthetic.md",
        headers={"content-type": "text/markdown"},
    )
    filename, text, media_type = asyncio.run(extract_document(upload, 1024))

    assert filename == "synthetic.md"
    assert "AURORA — synthetic project" in text
    assert media_type == "text/markdown"


@pytest.mark.parametrize(
    ("filename", "content", "limit", "expected_status"),
    [
        ("bad.exe", b"no", 1024, 415),
        ("empty.md", b"", 1024, 422),
        ("large.txt", b"12345", 4, 413),
        ("bad.md", b"\xff", 1024, 422),
    ],
)
def test_ingestion_rejects_invalid_files(filename, content, limit, expected_status):
    upload = UploadFile(file=BytesIO(content), filename=filename)
    with pytest.raises(HTTPException) as exception:
        asyncio.run(extract_document(upload, limit))
    assert exception.value.status_code == expected_status
