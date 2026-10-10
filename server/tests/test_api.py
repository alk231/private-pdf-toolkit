import io
import os
from pathlib import Path

os.environ["API_KEY"] = "test-key-that-is-at-least-32-chars"
os.environ["MAX_UPLOAD_MB"] = "1"

import fitz
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app, parse_pages

KEY = "test-key-that-is-at-least-32-chars"
client = TestClient(app)
HEADERS = {"X-API-Key": KEY}

def pdf_bytes(pages=3):
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"Page {i+1}")
    data = doc.tobytes()
    doc.close()
    return data

def pdf_file(data=None, name="a.pdf", field="file"):
    return (field, (name, data or pdf_bytes(), "application/pdf"))

def test_health_no_auth():
    assert client.get("/health").json() == {"status": "ok"}

def test_auth_missing_and_wrong_key():
    assert client.post("/info", files=[pdf_file()]).status_code == 401
    assert client.post("/info", headers={"X-API-Key":"wrong"}, files=[pdf_file()]).status_code == 401

def test_merge():
    r=client.post("/merge",headers=HEADERS,files=[pdf_file(name="one.pdf", field="files"),pdf_file(name="two.pdf", field="files")])
    assert r.status_code==200
    doc=fitz.open(stream=r.content,filetype="pdf")
    assert len(doc)==6

def test_page_spec_valid_invalid():
    assert parse_pages("1-3,5,8-10",10)==[0,1,2,4,7,8,9]
    for spec in ("0","3-2","1,1","11","a","1,,2"):
        with pytest.raises(Exception): parse_pages(spec,10)

def test_split():
    r=client.post("/split",headers=HEADERS,files=[pdf_file()],data={"pages":"1,3"})
    assert r.status_code==200 and len(fitz.open(stream=r.content,filetype="pdf"))==2

def test_rotate():
    r=client.post("/rotate",headers=HEADERS,files=[pdf_file()],data={"degrees":"90","pages":"1"})
    assert r.status_code==200

def test_protect_unlock_roundtrip():
    protected=client.post("/protect",headers=HEADERS,files=[pdf_file()],data={"password":"secret"})
    assert protected.status_code==200
    unlocked=client.post("/unlock",headers=HEADERS,files=[pdf_file(protected.content)],data={"password":"secret"})
    assert unlocked.status_code==200
    assert len(fitz.open(stream=unlocked.content,filetype="pdf"))==3

def test_images_to_pdf():
    buff=io.BytesIO(); Image.new("RGB",(80,120),(255,0,0)).save(buff,format="PNG")
    r=client.post("/images-to-pdf",headers=HEADERS,files=[("files",("x.png",buff.getvalue(),"image/png"))])
    assert r.status_code==200 and len(fitz.open(stream=r.content,filetype="pdf"))==1

def test_oversize_rejection():
    r=client.post("/info",headers=HEADERS,files=[pdf_file(b"%PDF-"+b"x"*(1024*1024+1))])
    assert r.status_code==413

def test_wrong_file_type():
    r=client.post("/info",headers=HEADERS,files=[pdf_file(b"not a pdf")])
    assert r.status_code==415

def test_temp_dir_cleanup_on_error(monkeypatch):
    import app.main as m
    created=[]; original=m.new_job
    def tracked():
        p=original(); created.append(p); return p
    monkeypatch.setattr(m,"new_job",tracked)
    r=client.post("/split",headers=HEADERS,files=[pdf_file()],data={"pages":"bad"})
    assert r.status_code==400
    assert created and all(not p.exists() for p in created)
