"""Send the same edge-case requests to jodit-nodejs and jodit-python.

Both connectors serve identical copies of a small file tree; answers are
compared after replacing each root with ``<ROOT>`` and dropping the
``changed`` timestamps. Needs ``make parity`` first (for the jodit-nodejs
checkout with its dependencies in ``.cache/parity``).

Usage:
    python scripts/parity/compare.py
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parents[2]
WORK = REPO / ".cache" / "parity"
PORTS = {"nodejs": 8091, "python": 8092}
STARTUP_ATTEMPTS = 100

KNOWN: dict[str, str] = {
    "files": "thumb of an undecodable image is the file itself, not a "
    "path relative to the server's working directory",
    "folderMove into itself": "the storage root is hidden from errors",
}
"""Deliberate differences, by case label."""

CASES: list[tuple[str, dict[str, str]]] = [
    ("files", {"action": "files"}),
    ("files, unknown source", {"action": "files", "source": "zzz"}),
    ("files, missing path", {"action": "files", "path": "nope"}),
    ("files, bad offset", {"action": "files", "mods[offset]": "x"}),
    ("files, bad sort", {"action": "files", "mods[sortBy]": "weird"}),
    ("folders", {"action": "folders"}),
    ("folders, sub-folder", {"action": "folders", "path": "a"}),
    (
        "folderMove into itself",
        {"action": "folderMove", "from": "a", "path": "a/b"},
    ),
    (
        "folderCopy into itself",
        {"action": "folderCopy", "from": "a", "path": "a/b"},
    ),
    (
        "folderMove, missing",
        {"action": "folderMove", "from": "z", "path": "a"},
    ),
    (
        "fileMove, missing",
        {"action": "fileMove", "from": "z.txt", "path": "a"},
    ),
    ("fileMove, no from", {"action": "fileMove", "path": "a"}),
    (
        "fileCopy into same folder",
        {"action": "fileCopy", "from": "t.txt", "path": "/"},
    ),
    ("fileRemove, missing", {"action": "fileRemove", "name": "z.txt"}),
    ("fileRemove, no name", {"action": "fileRemove"}),
    (
        "fileRemove, dot-dot name",
        {"action": "fileRemove", "name": "../t.txt", "path": "a"},
    ),
    (
        "fileRename onto existing",
        {"action": "fileRename", "name": "t.txt", "newname": "p"},
    ),
    (
        "fileRename, slash in name",
        {"action": "fileRename", "name": "t.txt", "newname": "a/b"},
    ),
    ("folderCreate, exists", {"action": "folderCreate", "name": "a"}),
    ("folderCreate, empty name", {"action": "folderCreate", "name": ""}),
    (
        "folderCreate, unsafe name",
        {"action": "folderCreate", "name": "we<i>rd?"},
    ),
    ("folderRemove, missing", {"action": "folderRemove", "name": "zz"}),
    ("folderRemove, a file", {"action": "folderRemove", "name": "t.txt"}),
    (
        "folderRename, missing",
        {"action": "folderRename", "name": "zz", "newname": "q"},
    ),
    ("imageResize, no box", {"action": "imageResize", "name": "p.png"}),
    (
        "imageResize, bad box",
        {
            "action": "imageResize",
            "name": "p.png",
            "box[w]": "-1",
            "box[h]": "a",
        },
    ),
    (
        "imageResize, not an image",
        {
            "action": "imageResize",
            "name": "t.txt",
            "box[w]": "10",
            "box[h]": "10",
        },
    ),
    (
        "imageResize, corrupt image",
        {
            "action": "imageResize",
            "name": "bad.png",
            "box[w]": "10",
            "box[h]": "10",
        },
    ),
    (
        "imageCrop out of bounds",
        {
            "action": "imageCrop",
            "name": "p.png",
            "box[x]": "30",
            "box[y]": "20",
            "box[w]": "50",
            "box[h]": "50",
        },
    ),
    (
        "imageResize",
        {
            "action": "imageResize",
            "name": "p.png",
            "box[w]": "20",
            "box[h]": "15",
            "newname": "small.png",
        },
    ),
    ("fileDownload, missing", {"action": "fileDownload", "name": "z.txt"}),
    ("fileDownload, a folder", {"action": "fileDownload", "name": "a"}),
    (
        "getLocalFileByUrl",
        {"action": "getLocalFileByUrl", "url": "http://localhost/f/a/x.txt"},
    ),
    (
        "getLocalFileByUrl, other host",
        {"action": "getLocalFileByUrl", "url": "http://other/x.txt"},
    ),
    (
        "getLocalFileByUrl, missing file",
        {"action": "getLocalFileByUrl", "url": "http://localhost/f/z.txt"},
    ),
    ("fileUploadRemote, bad URL", {"action": "fileUploadRemote", "url": "x"}),
    (
        "fileUploadRemote, ftp",
        {"action": "fileUploadRemote", "url": "ftp://example.com/a.png"},
    ),
    (
        "fileUploadRemote, private host",
        {"action": "fileUploadRemote", "url": "http://127.0.0.1:1/a.png"},
    ),
    ("generatePdf, no html", {"action": "generatePdf"}),
    ("generateDocx, no html", {"action": "generateDocx"}),
    ("unknown action", {"action": "zzz"}),
    ("permissions, sub-folder", {"action": "permissions", "path": "a"}),
    ("imageLoad with GET", {"action": "imageLoad", "name": "p.png"}),
]


def make_tree(root: Path) -> None:
    """Create the file tree both connectors serve."""
    shutil.rmtree(root, ignore_errors=True)
    (root / "a" / "b").mkdir(parents=True)
    (root / "empty").mkdir()
    (root / "a" / "x.txt").write_text("x")
    (root / "t.txt").write_text("t")
    Image.new("RGB", (40, 30), "red").save(root / "p.png")
    (root / "bad.png").write_bytes(b"not an image")


def start(kind: str, base: Path) -> tuple[subprocess.Popen[bytes], Path]:
    """Start one connector on its port with a fresh tree."""
    port = PORTS[kind]
    root = base / kind
    make_tree(root)
    config = base / f"{kind}.json"
    config.write_text(
        json.dumps(
            {
                "debug": False,
                "allowCrossOrigin": True,
                "sources": {
                    "s": {
                        "name": "s",
                        "title": "S",
                        "root": str(root),
                        "baseurl": "http://localhost/f/",
                    }
                },
            }
        )
    )
    env = {
        **os.environ,
        "CONFIG_FILE": str(config),
        "PORT": str(port),
        "HOST": "127.0.0.1",
    }
    if sys.platform == "darwin":
        env["DYLD_FALLBACK_LIBRARY_PATH"] = "/opt/homebrew/lib:/usr/local/lib"
    if kind == "nodejs":
        command = [
            str(WORK / "node_modules/.bin/tsx"),
            str(WORK / "src/run.ts"),
        ]
        cwd = WORK
    else:
        command = ["uv", "run", "--project", str(REPO), "jcpy"]
        cwd = REPO
    process = subprocess.Popen(  # noqa: S603 - fixed commands
        command,
        cwd=cwd,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(STARTUP_ATTEMPTS):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/ping")
        except OSError:
            time.sleep(0.2)
        else:
            return process, root
    process.terminate()
    msg = f"{kind} connector did not start"
    raise SystemExit(msg)


def call(kind: str, root: Path, params: dict[str, str]) -> tuple[int, str]:
    """Send one request; return the status and the normalized body."""
    query = urllib.parse.urlencode(params)
    url = f"http://127.0.0.1:{PORTS[kind]}/?{query}"
    try:
        with urllib.request.urlopen(url) as response:
            status, body = response.status, response.read()
    except urllib.error.HTTPError as error:
        status, body = error.code, error.read()
    try:
        text = json.dumps(json.loads(body))
    except ValueError:
        text = f"<{len(body)} bytes>"
    for spelling in {str(root), os.path.realpath(root)}:
        text = text.replace(spelling, "<ROOT>")
    return status, re.sub(r'"changed": "[^"]*"', '"changed": "*"', text)


def main() -> int:
    """Compare every case and print the differences.

    Returns:
        Process exit status: 1 when any answer differs.
    """
    base = Path(tempfile.mkdtemp(prefix="jcpy-compare-"))
    processes: list[subprocess.Popen[bytes]] = []
    roots: dict[str, Path] = {}
    try:
        for kind in PORTS:
            process, roots[kind] = start(kind, base)
            processes.append(process)
        same = known = 0
        for label, params in CASES:
            nodejs = call("nodejs", roots["nodejs"], params)
            python = call("python", roots["python"], params)
            if nodejs == python:
                same += 1
                continue
            if label in KNOWN:
                known += 1
                print(f"## {label} (known: {KNOWN[label]})")
            else:
                print(f"## {label}")
            print(f"  nodejs {nodejs[0]} {nodejs[1][:400]}")
            print(f"  python {python[0]} {python[1][:400]}")
        print(f"\n{same}/{len(CASES)} identical, {known} known differences")
        return 0 if same + known == len(CASES) else 1
    finally:
        for process in processes:
            process.terminate()
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
