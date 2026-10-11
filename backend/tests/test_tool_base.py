from pathlib import Path

import pytest

from app.tools.base import ToolContext, ToolError, map_exception


def _ctx(options):
    return ToolContext(tool="x", inputs=[], options=options, out_dir=Path("."), tmp_dir=Path("."))


def test_opt_int():
    assert _ctx({}).opt_int("n", 5) == 5
    assert _ctx({"n": "7"}).opt_int("n") == 7
    assert _ctx({"n": 3}).opt_int("n", minimum=1, maximum=5) == 3
    for bad in (True, "x", 2.5, None):
        with pytest.raises(ToolError):
            _ctx({"n": bad}).opt_int("n")
    with pytest.raises(ToolError):
        _ctx({"n": 9}).opt_int("n", maximum=5)


def test_opt_str_and_bool():
    assert _ctx({"m": "a"}).opt_str("m", allowed=("a", "b")) == "a"
    with pytest.raises(ToolError):
        _ctx({"m": "c"}).opt_str("m", allowed=("a", "b"))
    with pytest.raises(ToolError):
        _ctx({"m": 1}).opt_str("m")
    assert _ctx({}).opt_bool("flag", True) is True
    with pytest.raises(ToolError):
        _ctx({"flag": "yes"}).opt_bool("flag")


def test_map_exception():
    class PasswordError(Exception):
        pass

    class PdfError(Exception):
        pass

    assert map_exception(PasswordError()).code == "wrong_password"
    assert map_exception(PdfError()).code == "corrupted_file"
    assert map_exception(MemoryError()).code == "too_complex"
    assert map_exception(ValueError("x")).code == "processing_failed"
    original = ToolError("job_timeout")
    assert map_exception(original) is original
