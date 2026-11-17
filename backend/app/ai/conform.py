"""Make a model's JSON reply fit the output schema before strict validation.

Hosted models do not always honour Ollama's ``format`` constraint. Their near-misses are mechanical:
prose or a code fence around the JSON, the answer wrapped in an extra object, ``"Low"`` for ``"low"``,
``"Title"`` for ``"title"``, a summary a few characters over the limit, ``"5"`` for ``5``. Repairing those
here is far cheaper and more reliable than another model round-trip. Anything that changes meaning
(missing fields, unknown keys, wrong structure) is left for validation to reject.
"""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ValidationError


def extract_json(text: str) -> Any:
    """Parse ``text`` as JSON, falling back to the outermost ``{...}`` span (prose/fences around it)."""
    text = (text or "").strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except ValueError:
            pass
    return None


def _resolve(node: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    while "$ref" in node:
        node = defs[node["$ref"].rsplit("/", 1)[-1]]
    return node


def _match_key(key: str, props: dict[str, Any]) -> str | None:
    if key in props:
        return key
    norm = key.strip().lower().replace(" ", "_").replace("-", "_")
    for p in props:
        if p.lower() == norm:
            return p
    return None


def _conform(value: Any, node: dict[str, Any], defs: dict[str, Any]) -> Any:
    node = _resolve(node, defs)
    if "anyOf" in node:  # Optional[X]: keep None, otherwise conform to the first non-null branch
        if value is None:
            return None
        for branch in node["anyOf"]:
            if _resolve(branch, defs).get("type") != "null":
                return _conform(value, branch, defs)
        return value
    if "enum" in node or "const" in node:
        options = node.get("enum") or [node["const"]]
        if isinstance(value, str):
            for opt in options:
                if isinstance(opt, str) and opt.lower() == value.strip().lower():
                    return opt
        return value
    typ = node.get("type")
    if typ == "object" and isinstance(value, dict):
        props = node.get("properties", {})
        out: dict[str, Any] = {}
        for k, v in value.items():
            target = _match_key(k, props) if props else k
            if target is None:
                out[k] = v  # unknown key: left as is (pydantic ignores extras)
            elif target not in out:
                out[target] = _conform(v, props[target], defs) if props else v
        return out
    if typ == "array":
        if isinstance(value, (str, dict)) and value != "":
            value = [value]  # a single item where a list was expected
        if isinstance(value, list):
            items = node.get("items", {})
            value = [_conform(v, items, defs) for v in value]
            if "maxItems" in node:
                value = value[: node["maxItems"]]
        return value
    if typ == "string":
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            value = str(value)
        if isinstance(value, str) and "maxLength" in node and len(value) > node["maxLength"]:
            cut = value[: node["maxLength"] - 1]
            space = cut.rfind(" ")
            value = (cut[:space] if space > node["maxLength"] * 0.8 else cut).rstrip(" ,;:") + "…"
        return value
    if typ == "integer":
        if isinstance(value, str) and value.strip().lstrip("+-").isdigit():
            value = int(value.strip())
        elif isinstance(value, float) and value.is_integer():
            value = int(value)
        if isinstance(value, int) and not isinstance(value, bool):
            if "minimum" in node:
                value = max(value, node["minimum"])
            if "maximum" in node:
                value = min(value, node["maximum"])
        return value
    if typ == "boolean" and isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    return value


def _unwrap(data: Any, required: list[str]) -> Any:
    """If the reply nests the answer one or two levels deep (``{"result": {...}}``), return the inner object."""
    if not isinstance(data, dict) or not required:
        return data

    def score(d: dict) -> int:
        keys = {k.lower() for k in d}
        return sum(1 for r in required if r.lower() in keys)

    best, best_score = data, score(data)
    frontier = [data]
    for _ in range(2):
        nxt = []
        for d in frontier:
            for v in d.values():
                if isinstance(v, dict):
                    s = score(v)
                    if s > best_score:
                        best, best_score = v, s
                    nxt.append(v)
        frontier = nxt
    return best


def conform(text: str, model: type[BaseModel]) -> BaseModel:
    """Parse, repair and validate a model reply. Raises ``ValueError`` for empty/non-JSON text and
    ``ValidationError`` when the repaired object still does not fit the schema."""
    if not (text or "").strip():
        raise ValueError("empty reply")
    data = extract_json(text)
    if data is None:
        raise ValueError("reply is not JSON")
    schema = model.model_json_schema()
    data = _unwrap(data, schema.get("required", []))
    data = _conform(data, schema, schema.get("$defs", {}))
    return model.model_validate(data)


def describe_errors(exc: Exception, limit: int = 12) -> str:
    """A short, input-free description of what is wrong, for the repair prompt and the call log."""
    if not isinstance(exc, ValidationError):
        return str(exc)[:300]
    parts = []
    for e in exc.errors()[:limit]:
        loc = ".".join(str(p) for p in e.get("loc", ())) or "(root)"
        parts.append(f"{loc}: {e.get('msg', 'invalid')}")
    more = len(exc.errors()) - limit
    if more > 0:
        parts.append(f"... and {more} more")
    return "; ".join(parts)
