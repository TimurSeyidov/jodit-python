"""Check an installation of jodit-python without extras.

The core must import and serve files, while PDF, DOCX and S3 answer
``501`` naming the missing extra. Run it in an environment holding only
the core dependencies:

    uv sync --frozen --no-dev
    uv run --no-sync python scripts/check_core_install.py
"""

import asyncio
import json
import os
import sys
import tempfile
from importlib.util import find_spec
from pathlib import Path

from httpx import ASGITransport, AsyncClient

OPTIONAL = ("weasyprint", "boto3", "docx", "html4docx", "bs4")


async def check() -> list[str]:
    """Run the requests and collect failed expectations.

    Returns:
        Descriptions of failures; empty when everything holds.
    """
    # Imported late: CONFIG is set by the caller first.
    from jcpy import create_app

    failures: list[str] = []
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://c") as http:
        expectations = [
            ("/ping", {}, 200, None),
            ("/files", {"source": "local"}, 200, None),
            ("/generatePdf", {"html": "<p>x</p>"}, 501, "[pdf]"),
            ("/generateDocx", {"html": "<p>x</p>"}, 501, "[docx]"),
            ("/files", {"source": "bucket"}, 501, "[s3]"),
        ]
        for path, params, status, text in expectations:
            response = await http.get(path, params=params)
            if response.status_code != status or (
                text is not None and text not in response.text
            ):
                failures.append(
                    f"{path} {params}: {response.status_code} {response.text}"
                )
    return failures


def main() -> int:
    """Check the installation.

    Returns:
        Process exit status.
    """
    present = [name for name in OPTIONAL if find_spec(name) is not None]
    if present:
        print(f"not a core install, found: {', '.join(present)}")
        return 1
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        os.environ["CONFIG"] = json.dumps(
            {
                "debug": False,
                "sources": {
                    "local": {
                        "title": "Local",
                        "root": str(root),
                        "baseurl": "http://localhost/files/",
                    },
                    "bucket": {
                        "title": "Bucket",
                        "baseurl": "http://localhost/bucket/",
                        "storageAdapter": "s3",
                        "s3": {"bucket": "b"},
                    },
                },
            }
        )
        failures = asyncio.run(check())
    for failure in failures:
        print(f"FAIL {failure}")
    print("core install ok" if not failures else "core install broken")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
