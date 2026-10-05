"""Extractor guards: traversal, links, special files, size/count caps."""

import io
import tarfile
from pathlib import Path

import pytest

from app import config, extractor


def _tar(path: Path, members: list[tuple[tarfile.TarInfo, bytes | None]]) -> Path:
    with tarfile.open(path, "w:gz") as tar:
        for info, data in members:
            if data is not None:
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
            else:
                tar.addfile(info)
    return path


def _file(name: str, data: bytes = b"x = 1\n") -> tuple[tarfile.TarInfo, bytes]:
    return tarfile.TarInfo(name=name), data


def test_extracts_nested_files(tmp_path):
    archive = tmp_path / "a.tar.gz"
    _tar(archive, [_file("src/pkg/mod.py", b"print(1)\n")])
    dest = tmp_path / "out"
    extractor.safe_extract_tar_gz(archive, dest)
    assert (dest / "src/pkg/mod.py").read_text() == "print(1)\n"


def test_parent_traversal_rejected(tmp_path):
    archive = tmp_path / "a.tar.gz"
    _tar(archive, [_file("../evil.py")])
    with pytest.raises(extractor.ExtractError, match="unsafe path"):
        extractor.safe_extract_tar_gz(archive, tmp_path / "out")


def test_nested_traversal_rejected(tmp_path):
    archive = tmp_path / "a.tar.gz"
    _tar(archive, [_file("pkg/../../../evil.py")])
    with pytest.raises(extractor.ExtractError, match="unsafe path"):
        extractor.safe_extract_tar_gz(archive, tmp_path / "out")


def test_absolute_path_rejected(tmp_path):
    archive = tmp_path / "a.tar.gz"
    _tar(archive, [_file("/etc/passwd")])
    with pytest.raises(extractor.ExtractError, match="unsafe path"):
        extractor.safe_extract_tar_gz(archive, tmp_path / "out")


def test_symlink_member_rejected(tmp_path):
    archive = tmp_path / "a.tar.gz"
    link = tarfile.TarInfo(name="innocent")
    link.type = tarfile.SYMTYPE
    link.linkname = "/etc/passwd"
    _tar(archive, [(link, None)])
    with pytest.raises(extractor.ExtractError, match="link member"):
        extractor.safe_extract_tar_gz(archive, tmp_path / "out")


def test_hardlink_member_rejected(tmp_path):
    archive = tmp_path / "a.tar.gz"
    link = tarfile.TarInfo(name="alias")
    link.type = tarfile.LNKTYPE
    link.linkname = "target.py"
    _tar(archive, [(link, None)])
    with pytest.raises(extractor.ExtractError, match="link member"):
        extractor.safe_extract_tar_gz(archive, tmp_path / "out")


def test_fifo_member_rejected(tmp_path):
    archive = tmp_path / "a.tar.gz"
    fifo = tarfile.TarInfo(name="pipe")
    fifo.type = tarfile.FIFOTYPE
    _tar(archive, [(fifo, None)])
    with pytest.raises(extractor.ExtractError, match="special file"):
        extractor.safe_extract_tar_gz(archive, tmp_path / "out")


def test_invalid_archive_rejected(tmp_path):
    archive = tmp_path / "a.tar.gz"
    archive.write_bytes(b"this is definitely not a tarball")
    with pytest.raises(extractor.ExtractError, match="invalid tar.gz"):
        extractor.safe_extract_tar_gz(archive, tmp_path / "out")


def test_size_cap_enforced(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MAX_EXTRACTED_BYTES", 100)
    archive = tmp_path / "a.tar.gz"
    _tar(archive, [_file("big.py", b"x" * 200)])
    with pytest.raises(extractor.ExtractError, match="MAX_EXTRACTED_BYTES") as exc:
        extractor.safe_extract_tar_gz(archive, tmp_path / "out")
    assert exc.value.resource is True


def test_cumulative_size_cap_enforced(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MAX_EXTRACTED_BYTES", 100)
    archive = tmp_path / "a.tar.gz"
    _tar(archive, [_file("one.py", b"a" * 60), _file("two.py", b"b" * 60)])
    with pytest.raises(extractor.ExtractError) as exc:
        extractor.safe_extract_tar_gz(archive, tmp_path / "out")
    assert exc.value.resource is True


def test_file_count_cap_enforced(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MAX_EXTRACTED_FILES", 2)
    archive = tmp_path / "a.tar.gz"
    _tar(archive, [_file("a.py"), _file("b.py"), _file("c.py")])
    with pytest.raises(extractor.ExtractError, match="MAX_EXTRACTED_FILES") as exc:
        extractor.safe_extract_tar_gz(archive, tmp_path / "out")
    assert exc.value.resource is True


def test_unsafe_content_is_not_a_resource_error(tmp_path):
    archive = tmp_path / "a.tar.gz"
    _tar(archive, [_file("../evil.py")])
    with pytest.raises(extractor.ExtractError) as exc:
        extractor.safe_extract_tar_gz(archive, tmp_path / "out")
    assert exc.value.resource is False
