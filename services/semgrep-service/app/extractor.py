"""Hardened tar.gz extraction for uploaded scan inputs.

Every archive is treated as hostile. Rejected with ``ExtractError``:

- absolute paths or ``..`` traversal in member names,
- symlink / hardlink members (link escapes),
- device / FIFO members,
- cumulative extracted bytes over ``MAX_EXTRACTED_BYTES``,
- more than ``MAX_EXTRACTED_FILES`` regular files,

``ExtractError.resource`` distinguishes resource-cap hits (caller maps to
413) from unsafe content / invalid archives (caller maps to 400).
"""

import tarfile
from pathlib import Path, PurePosixPath

from app import config


class ExtractError(Exception):
    """Archive rejected — ``resource=True`` means a size/count cap."""

    def __init__(self, message: str, *, resource: bool = False):
        super().__init__(message)
        self.resource = resource


def _member_target(dest: Path, name: str) -> Path:
    """Resolve a member name under ``dest`` or raise (traversal guard)."""
    posix = PurePosixPath(name)
    if not posix.parts:
        raise ExtractError("archive contains a member with an empty name")
    if posix.is_absolute() or ".." in posix.parts:
        raise ExtractError(f"archive contains an unsafe path: {name}")

    target = (dest / Path(*posix.parts)).resolve()
    if target != dest and dest not in target.parents:
        raise ExtractError(f"archive member escapes the destination: {name}")
    return target


def safe_extract_tar_gz(archive: Path, dest: Path) -> None:
    """Extract ``archive`` into ``dest`` with all guards applied."""
    dest = dest.resolve()
    dest.mkdir(parents=True, exist_ok=True)
    total_bytes = 0
    file_count = 0

    try:
        with tarfile.open(archive, "r:gz") as tar:
            for member in tar:
                if member.issym() or member.islnk():
                    raise ExtractError(f"archive contains a link member: {member.name}")
                if member.ischr() or member.isblk() or member.isfifo():
                    raise ExtractError(
                        f"archive contains a special file: {member.name}"
                    )
                if member.isdir():
                    _member_target(dest, member.name).mkdir(parents=True, exist_ok=True)
                    continue
                if not member.isfile():
                    raise ExtractError(
                        f"archive contains an unsupported member: {member.name}"
                    )

                total_bytes += max(int(member.size), 0)
                if total_bytes > config.MAX_EXTRACTED_BYTES:
                    raise ExtractError(
                        f"archive exceeds MAX_EXTRACTED_BYTES="
                        f"{config.MAX_EXTRACTED_BYTES}",
                        resource=True,
                    )
                file_count += 1
                if file_count > config.MAX_EXTRACTED_FILES:
                    raise ExtractError(
                        f"archive exceeds MAX_EXTRACTED_FILES="
                        f"{config.MAX_EXTRACTED_FILES}",
                        resource=True,
                    )

                target = _member_target(dest, member.name)
                source = tar.extractfile(member)
                if source is None:
                    raise ExtractError(f"could not read member: {member.name}")
                target.parent.mkdir(parents=True, exist_ok=True)
                with source, open(target, "wb") as out:
                    written = 0
                    while chunk := source.read(1024 * 1024):
                        written += len(chunk)
                        if written > config.MAX_EXTRACTED_BYTES:
                            raise ExtractError(
                                "archive expands past MAX_EXTRACTED_BYTES",
                                resource=True,
                            )
                        out.write(chunk)
    except ExtractError:
        raise
    except tarfile.TarError as exc:
        raise ExtractError(f"invalid tar.gz archive: {exc}") from exc
