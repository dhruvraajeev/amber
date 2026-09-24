"""Print the API's OpenAPI schema, which the frontend's types are generated from (plan §7, Step 18).

    uv run python -m amber.api.openapi > openapi.json

`npm run gen:types` (in frontend/) pipes this into openapi-typescript to write src/api/generated.ts,
and CI fails if that file differs from what is committed. No server needed: FastAPI builds the schema
from the routes and the Pydantic models in amber/contracts.py.
"""

import json
import sys

from amber.api.app import app


def schema() -> dict:
    """The schema minus Pydantic's auto titles ("Llmcallsmean"), noise on every generated field."""
    return _untitled(app.openapi())


def _untitled(node: object) -> object:
    if isinstance(node, list):
        return [_untitled(v) for v in node]
    if isinstance(node, dict):
        # A string "title" is a label; a field that happens to be called "title" would be a dict.
        return {k: _untitled(v) for k, v in node.items() if not (k == "title" and isinstance(v, str))}
    return node


if __name__ == "__main__":
    json.dump(schema(), sys.stdout, indent=2)
    sys.stdout.write("\n")
