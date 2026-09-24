"""Write the OpenAPI document and a Swagger UI page to docs/openapi.

Usage:
    python scripts/generate_openapi.py [--check]

With ``--check`` nothing is written; the exit status is 1 when the
committed files differ from the generated ones.
"""

import argparse
import json
import sys
from pathlib import Path

import yaml
from openapi_spec_validator import validate

from jcpy.openapi.spec import build_openapi

OUTPUT = Path(__file__).resolve().parent.parent / "docs" / "openapi"
SWAGGER_VERSION = "5.17.14"
SWAGGER_CDN = f"https://cdn.jsdelivr.net/npm/swagger-ui-dist@{SWAGGER_VERSION}"
SWAGGER_HTML = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Jodit Connector API</title>
  <link rel="stylesheet" href="{SWAGGER_CDN}/swagger-ui.css">
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="{SWAGGER_CDN}/swagger-ui-bundle.js"></script>
  <script>
    window.ui = SwaggerUIBundle({{
      url: "openapi.json",
      dom_id: "#swagger-ui",
      deepLinking: true,
    }});
  </script>
</body>
</html>
"""


def render() -> dict[str, str]:
    """Render every output file.

    Returns:
        File contents by file name.
    """
    spec = build_openapi()
    validate(spec)
    return {
        "openapi.json": json.dumps(spec, indent=2, ensure_ascii=False) + "\n",
        "openapi.yaml": yaml.safe_dump(
            spec, sort_keys=False, allow_unicode=True, width=79
        ),
        "index.html": SWAGGER_HTML,
    }


def main() -> int:
    """Generate or check the files.

    Returns:
        Process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="fail on stale files"
    )
    args = parser.parse_args()
    stale = []
    for name, content in render().items():
        target = OUTPUT / name
        current = target.read_text("utf-8") if target.exists() else None
        if current == content:
            continue
        if args.check:
            stale.append(name)
        else:
            OUTPUT.mkdir(parents=True, exist_ok=True)
            target.write_text(content, "utf-8")
            print(f"wrote {target.relative_to(OUTPUT.parent.parent)}")
    if stale:
        print(
            f"stale: {', '.join(stale)}; run 'make openapi'", file=sys.stderr
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
