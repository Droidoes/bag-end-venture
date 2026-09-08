"""Thin wrapper around the `gws` CLI.

Why a wrapper: every gws call returns either JSON (stdout, after a
"Using keyring backend" banner) or an error envelope, and the OAuth token
cache lives at ~/.config/gws which sandboxed environments mount read-only.
This module centralizes all of that so callers deal with plain Python.

Sandbox note (DeepSeek Harness): run any command that reaches gws with
sandbox_permissions="danger-full-access", else the CLI fails with
"Failed to set permissions on token directory ... Read-only file system".
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from . import config


class GwsError(RuntimeError):
    pass


TOKEN_CACHE_HINT = (
    "gws failed to access its token cache (~/.config/gws). "
    "In a sandboxed session, re-run with full filesystem access "
    '(bash sandbox_permissions="danger-full-access").'
)


def _run_gws(method: str, params: dict, output: Path | None = None) -> dict | bytes:
    """Execute one gws API call (e.g. 'files.list') and return parsed JSON or bytes."""
    resource, action = method.split(".", 1)
    cmd = ["gws", "drive", resource, action, "--params", json.dumps(params)]
    if output is not None:
        cmd += ["-o", str(output)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    text = proc.stdout
    start = text.find("{")
    if output is not None:
        # Fail loudly: a 0-exit that produced no file (or an empty one) is an
        # error, not a success. Silent pass-through here once hid 19 bad fetches.
        if proc.returncode != 0 or not output.exists() or output.stat().st_size == 0:
            hint = TOKEN_CACHE_HINT if "token directory" in (proc.stdout + proc.stderr) else ""
            raise GwsError(
                f"gws {method} produced no usable file at {output} "
                f"(exit={proc.returncode}):\n{proc.stdout[:400]}\n{proc.stderr[:400]}\n{hint}")
        return output
    if proc.returncode != 0 or start < 0:
        hint = TOKEN_CACHE_HINT if "token directory" in (proc.stdout + proc.stderr) else ""
        raise GwsError(f"gws {method} failed:\n{proc.stdout[:400]}\n{proc.stderr[:400]}\n{hint}")
    return json.loads(text[start:])


@dataclass
class DriveFile:
    id: str
    name: str
    mime_type: str
    size: str
    path: str  # path relative to the walk root, "" for root-level files


def list_children(folder_id: str) -> list[DriveFile]:
    data = _run_gws("files.list", {
        "q": f'"{folder_id}" in parents and trashed=false',
        "fields": "nextPageToken,files(id,name,mimeType,size)",
        "pageSize": 200,
    })
    return [
        DriveFile(f["id"], f["name"], f["mimeType"], f.get("size", ""), "")
        for f in data.get("files", [])
    ]


def walk_tree(root_id: str, root_name: str = "") -> list[DriveFile]:
    """Recursively enumerate all files under a Drive folder.

    Skips subtrees matching config.EXCLUDE_PATH_PATTERNS (owner-ruled
    out-of-scope material, e.g. third-party accounts).
    """
    rows: list[DriveFile] = []
    excludes = [p.lower() for p in config.EXCLUDE_PATH_PATTERNS]

    def _excluded(rel: str) -> bool:
        low = rel.lower()
        return any(pat in low for pat in excludes)

    def _walk(fid: str, rel: str) -> None:
        for f in list_children(fid):
            if _excluded(f"{rel}/{f.name}"):
                continue
            f.path = rel
            rows.append(f)
            if f.mime_type == "application/vnd.google-apps.folder":
                _walk(f.id, f"{rel}/{f.name}")

    _walk(root_id, root_name)
    return rows


def search_files(query: str) -> list[dict]:
    """Raw Drive files.list search; query is a full Drive q-expression."""
    data = _run_gws("files.list", {
        "q": query,
        "fields": "nextPageToken,files(id,name,mimeType,parents,modifiedTime,size)",
        "pageSize": 50,
    })
    return data.get("files", [])


def get_file(file_id: str) -> dict:
    """Metadata for one file via files.get."""
    data = _run_gws("files.get", {
        "fileId": file_id,
        "fields": "id,name,mimeType,modifiedTime,size",
    })
    return data


def export_sheet(file_id: str, dest: Path, mime: str = config.SHEET_EXPORT_MIME) -> Path:
    """Export a Google Sheets document (all tabs) to xlsx (or csv) at dest."""
    _run_gws("files.export", {"fileId": file_id, "mimeType": mime}, output=dest)
    if not dest.exists() or dest.stat().st_size == 0:
        raise GwsError(f"export produced empty output for {file_id}")
    return dest


def download_file(file_id: str, dest: Path) -> Path:
    """Download a binary Drive file (xlsx, pdf, csv) to dest.

    NOTE: `files.download` returns the file's *metadata* envelope, not its
    bytes — the Drive download body requires files.get with alt=media.
    gws also refuses -o paths outside the current directory, so dest must be
    inside the repo (private/raw/ always is).
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    _run_gws("files.get", {"fileId": file_id, "alt": "media"}, output=dest)
    return dest


def resolve(alias_or_id: str) -> str:
    """Map a friendly alias (config keys) to a Drive ID; pass IDs through."""
    if alias_or_id in config.DRIVE_SHEETS:
        return config.DRIVE_SHEETS[alias_or_id]
    if alias_or_id in config.DRIVE_FOLDERS:
        return config.DRIVE_FOLDERS[alias_or_id]
    return alias_or_id


def warn_if_writable_cache() -> None:
    """Surface the token-cache constraint early with a clear message."""
    cache = Path.home() / ".config" / "gws"
    try:
        probe = cache / ".bagend_probe"
        probe.write_text("x")
        probe.unlink()
    except OSError as exc:
        print(f"WARNING: {exc}\n{TOKEN_CACHE_HINT}", file=sys.stderr)
