from __future__ import annotations

import io

import pikepdf
import pytest

from tests.pdf_fixtures import failure_code, numbered_pdf, result_pdf, run_tool


def test_protect_requires_a_password(client):
    files = [("d.pdf", numbered_pdf(1))]
    assert failure_code(client, "protect", files) == "invalid_options"
    assert failure_code(client, "protect", files, {"password": ""}) == "invalid_options"


def test_protect_encrypts_with_aes256(client):
    data = result_pdf(client, "protect", [("d.pdf", numbered_pdf(2))], {"password": "pw1"})
    with pytest.raises(pikepdf.PasswordError):
        pikepdf.open(io.BytesIO(data))
    with pytest.raises(pikepdf.PasswordError):
        pikepdf.open(io.BytesIO(data), password="wrong")
    with pikepdf.open(io.BytesIO(data), password="pw1") as pdf:
        assert len(pdf.pages) == 2
        assert pdf.encryption.bits == 256


def test_protect_aes128_option(client):
    data = result_pdf(
        client, "protect", [("d.pdf", numbered_pdf(1))], {"password": "pw1", "strength": "128"}
    )
    with pikepdf.open(io.BytesIO(data), password="pw1") as pdf:
        assert pdf.encryption.bits == 128


def test_protect_applies_permissions(client):
    data = result_pdf(
        client,
        "protect",
        [("d.pdf", numbered_pdf(1))],
        {"password": "pw1", "owner_password": "owner1", "allow_print": False, "allow_copy": False},
    )
    with pikepdf.open(io.BytesIO(data), password="pw1") as pdf:
        assert not pdf.allow.print_highres
        assert not pdf.allow.extract


def test_protect_can_re_encrypt_an_encrypted_input(client):
    files = [("d.pdf", numbered_pdf(2, password="old"))]
    assert failure_code(client, "protect", files, {"password": "new"}) == "password_required"
    data = result_pdf(client, "protect", files, {"password": "new", "current_password": "old"})
    with pikepdf.open(io.BytesIO(data), password="new") as pdf:
        assert len(pdf.pages) == 2


def test_protect_option_errors(client):
    files = [("d.pdf", numbered_pdf(1))]
    assert failure_code(client, "protect", files, {"password": "x" * 101}) == "invalid_options"
    assert failure_code(client, "protect", files, {"password": "pw", "strength": "512"}) == "invalid_options"
    assert failure_code(client, "protect", files, {"password": "pw", "allow_print": "yes"}) == "invalid_options"


def test_unlock_roundtrip(client):
    protected = result_pdf(client, "protect", [("d.pdf", numbered_pdf(2))], {"password": "pw1"})
    files = [("p.pdf", protected)]
    assert failure_code(client, "unlock", files) == "password_required"
    assert failure_code(client, "unlock", files, {"password": "nope"}) == "wrong_password"
    data = result_pdf(client, "unlock", files, {"password": "pw1"})
    with pikepdf.open(io.BytesIO(data)) as pdf:
        assert not pdf.is_encrypted
        assert len(pdf.pages) == 2


def test_unlock_reports_when_nothing_was_locked(client):
    body, result = run_tool(client, "unlock", [("d.pdf", numbered_pdf(1))])
    assert body["status"] == "done", body
    assert body["meta"]["was_encrypted"] is False
    with pikepdf.open(io.BytesIO(result.content)) as pdf:
        assert len(pdf.pages) == 1
