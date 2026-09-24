"""The schema that frontend/src/api/generated.ts is generated from (Step 18)."""

import json

from amber.api.openapi import schema


def test_optional_fields_are_omittable_never_null():
    schemas = schema()["components"]["schemas"]
    role = schemas["DesignEdge"]["properties"]["role"]
    assert role == {"type": "string", "enum": ["llm", "tool"]}
    assert "role" not in schemas["DesignEdge"]["required"]
    assert '"null"' not in json.dumps(schemas)


def test_auto_titles_are_dropped():
    assert '"title"' not in json.dumps(schema()["components"])
