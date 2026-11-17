"""Write the API's OpenAPI spec to docs/api/openapi.json (the Flutter client is generated
from it). Run after changing an endpoint or a model:

    python scripts/export_openapi.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.api.app import create_app  # noqa: E402

if __name__ == "__main__":
    target = ROOT / "docs" / "api" / "openapi.json"
    target.write_text(json.dumps(create_app().openapi(), indent=2) + "\n")
    print(f"Wrote {target.relative_to(ROOT)}")
