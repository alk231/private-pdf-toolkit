from types import SimpleNamespace

from app.security import client_ip, detect_file_type, parse_device_id, sanitize_filename


def test_sanitize_strips_paths():
    assert sanitize_filename("../../etc/passwd") == "passwd"
    assert sanitize_filename("a\\b\\c.pdf") == "c.pdf"


def test_sanitize_defaults_and_control_chars():
    assert sanitize_filename(None) == "file"
    assert sanitize_filename("") == "file"
    assert sanitize_filename("  ..  ") == "file"
    assert sanitize_filename("evil\x00name.pdf") == "evilname.pdf"
    assert sanitize_filename("evil\u202efdp.exe") == "evilfdp.exe"


def test_sanitize_replaces_unsafe_characters_and_keeps_unicode():
    assert sanitize_filename("a<b>.pdf") == "a_b_.pdf"
    assert sanitize_filename("résumé.pdf") == "résumé.pdf"


def test_sanitize_limits_length():
    name = sanitize_filename("a" * 300 + ".pdf")
    assert len(name) == 100
    assert name.endswith(".pdf")


def test_detect_file_type():
    assert detect_file_type(b"%PDF-1.7\n...").kind == "pdf"
    assert detect_file_type(b"junk" * 10 + b"%PDF-1.4").kind == "pdf"
    assert detect_file_type(b"\x89PNG\r\n\x1a\n0000").ext == ".png"
    assert detect_file_type(b"\xff\xd8\xff\xe0abc").ext == ".jpg"
    assert detect_file_type(b"RIFF\x00\x00\x00\x00WEBPVP8 ").ext == ".webp"
    assert detect_file_type(b"hello world") is None
    assert detect_file_type(b"") is None


def test_parse_device_id():
    assert parse_device_id("11111111-1111-4111-8111-111111111111") == "11111111-1111-4111-8111-111111111111"
    assert parse_device_id("AAAAAAAA-1111-4111-8111-111111111111") == "aaaaaaaa-1111-4111-8111-111111111111"
    assert parse_device_id("not-a-uuid") is None
    assert parse_device_id(None) is None
    assert parse_device_id("1" * 100) is None


def test_client_ip():
    request = SimpleNamespace(headers={"x-forwarded-for": "1.2.3.4, 10.0.0.1"}, client=SimpleNamespace(host="9.9.9.9"))
    assert client_ip(request, True) == "1.2.3.4"
    assert client_ip(request, False) == "9.9.9.9"
    garbage = SimpleNamespace(headers={"x-forwarded-for": "garbage"}, client=SimpleNamespace(host="9.9.9.9"))
    assert client_ip(garbage, True) == "9.9.9.9"
