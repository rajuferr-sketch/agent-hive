"""Pragmatic JSON-Schema (subset) validator for tool input validation.

Supports the constructs used by the 18 platform tools: ``type``
(string/number/integer/boolean/object/array/null), ``properties``,
``required``, ``items``, ``enum``, ``minLength``/``maxLength``,
``minimum``/``maximum``, ``additionalProperties``. Unknown keywords are
ignored (permissive by design); validation failures raise
:class:`SchemaError` with a JSON-pointer-ish path.
"""

from __future__ import annotations

from typing import Any


class SchemaError(ValueError):
    """Input does not match the tool schema."""


_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "null": type(None),
}


def validate_schema(instance: Any, schema: dict[str, Any], path: str = "$") -> None:
    """Validate ``instance`` against ``schema``; raise SchemaError on failure."""
    if not isinstance(schema, dict):
        return
    expected = schema.get("type")
    if expected is not None and not _check_type(instance, expected):
        raise SchemaError(f"{path}: expected type '{expected}', got {_json_type(instance)}")

    if "enum" in schema and instance not in schema["enum"]:
        raise SchemaError(f"{path}: value {instance!r} not in enum {schema['enum']!r}")

    if isinstance(instance, str):
        _check_bounds_len(instance, schema, path)
    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        _check_bounds_num(instance, schema, path)

    if isinstance(instance, dict):
        props = schema.get("properties", {})
        for req in schema.get("required", []):
            if req not in instance:
                raise SchemaError(f"{path}: missing required property '{req}'")
        additional = schema.get("additionalProperties", True)
        for key, value in instance.items():
            if key in props:
                validate_schema(value, props[key], f"{path}.{key}")
            elif additional is False:
                raise SchemaError(f"{path}: unexpected property '{key}'")
    if isinstance(instance, list):
        items = schema.get("items")
        if isinstance(items, dict):
            for idx, item in enumerate(instance):
                validate_schema(item, items, f"{path}[{idx}]")


def _json_type(instance: Any) -> str:
    if instance is None:
        return "null"
    if isinstance(instance, bool):
        return "boolean"
    if isinstance(instance, (int, float)):
        return "number" if isinstance(instance, float) else "integer"
    if isinstance(instance, str):
        return "string"
    if isinstance(instance, list):
        return "array"
    if isinstance(instance, dict):
        return "object"
    return type(instance).__name__


def _check_type(instance: Any, expected: Any) -> bool:
    if isinstance(expected, list):
        return any(_check_type(instance, e) for e in expected)
    if expected == "number":
        return isinstance(instance, (int, float)) and not isinstance(instance, bool)
    if expected == "integer":
        return isinstance(instance, int) and not isinstance(instance, bool)
    if expected in _TYPES:
        return isinstance(instance, _TYPES[expected])
    return True


def _check_bounds_len(instance: str, schema: dict[str, Any], path: str) -> None:
    if "minLength" in schema and len(instance) < schema["minLength"]:
        raise SchemaError(f"{path}: shorter than minLength {schema['minLength']}")
    if "maxLength" in schema and len(instance) > schema["maxLength"]:
        raise SchemaError(f"{path}: longer than maxLength {schema['maxLength']}")


def _check_bounds_num(instance: float, schema: dict[str, Any], path: str) -> None:
    if "minimum" in schema and instance < schema["minimum"]:
        raise SchemaError(f"{path}: below minimum {schema['minimum']}")
    if "maximum" in schema and instance > schema["maximum"]:
        raise SchemaError(f"{path}: above maximum {schema['maximum']}")
