from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FieldSpec:
    path: str
    label: str
    required: bool = False
    choices: tuple[str, ...] = ()
    multiline: bool = False
    placeholder: str = ""


STATUS_CHOICES = (
    "idea",
    "experimantal",
    "active",
    "paused",
    "presentable",
    "completed",
    "archived",
    "published",
    "retired",
)

COMPLETENESS_CHOICES = ("missing", "stub", "draft", "presentable", "complete")

TYPE_CHOICES = ("software", "sound", "image", "installation", "other")


FIELD_SPECS: tuple[FieldSpec, ...] = (
    FieldSpec("id", "Project ID", required=True, placeholder="MI-YYYY-AA"),
    FieldSpec("title", "Title", required=True, placeholder="My Project"),
    FieldSpec("year", "Year", required=True, placeholder="YYYY"),
    FieldSpec("type", "Type", choices=TYPE_CHOICES),
    FieldSpec("status", "Status", required=True, choices=STATUS_CHOICES),
    FieldSpec(
        "documentation_level",
        "Documentation level",
        required=True,
        choices=("stub", "presentable", "complete"),
    ),
    FieldSpec("version.kind", "Version kind", placeholder="original"),
    FieldSpec("version.label", "Version label", placeholder="Initial version"),
    FieldSpec("version.date", "Version date", placeholder="YYYY-MM-DD"),
    FieldSpec("description.short", "Short description"),
    FieldSpec("description.long", "Long description", multiline=True),
    FieldSpec("documents.artwork_sheet", "Artwork sheet", choices=COMPLETENESS_CHOICES),
    FieldSpec("documents.presentation", "Presentation", choices=COMPLETENESS_CHOICES),
    FieldSpec(
        "documents.technical_description",
        "Technical description",
        choices=("missing", "stub", "presentable", "complete"),
    ),
    FieldSpec("website.publish", "Publish website", required=True, choices=("true", "false")),
    FieldSpec("website.slug", "Website slug", placeholder="my-project"),
    FieldSpec("website.visibility", "Website visibility", choices=("public", "private")),
    FieldSpec("relations.revised_by", "Revised by", multiline=True),
    FieldSpec("relations.related", "Related projects", multiline=True),
    FieldSpec("keywords", "Keywords", multiline=True),
    FieldSpec("software", "Software", multiline=True),
    FieldSpec("hardware", "Hardware", multiline=True),
    FieldSpec("rights.copyright", "Copyright", placeholder="© monointerferenz"),
    FieldSpec("rights.license", "License", placeholder="all rights reserved"),
)


LIST_FIELDS = {"relations.revised_by", "relations.related", "keywords", "software", "hardware"}
MAPPING_FIELDS = {"version", "description", "documents", "website", "relations", "rights"}


DEFAULT_MANIFEST: dict[str, Any] = {
    "id": "",
    "title": "",
    "year": "",
    "type": "",
    "status": "",
    "documentation_level": "",
    "version": {"kind": "original", "label": "", "date": ""},
    "description": {"short": "", "long": ""},
    "documents": {
        "artwork_sheet": "missing",
        "presentation": "missing",
        "technical_description": "missing",
    },
    "website": {"publish": "", "slug": "", "visibility": ""},
    "relations": {"revised_by": [], "related": []},
    "keywords": [],
    "software": [],
    "hardware": [],
    "rights": {"copyright": "© monointerferenz", "license": "all rights reserved"},
}


def new_manifest() -> dict[str, Any]:
    return _deep_copy(DEFAULT_MANIFEST)


def get_value(data: dict[str, Any], path: str) -> Any:
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, dict):
            return ""
        current = current.get(part, "")
    return current


def set_value(data: dict[str, Any], path: str, value: Any) -> None:
    current: dict[str, Any] = data
    parts = path.split(".")
    for part in parts[:-1]:
        nested = current.setdefault(part, {})
        if not isinstance(nested, dict):
            nested = {}
            current[part] = nested
        current = nested
    current[parts[-1]] = value


def missing_required_fields(data: dict[str, Any]) -> list[FieldSpec]:
    return [spec for spec in FIELD_SPECS if spec.required and _is_empty(get_value(data, spec.path))]


def load_manifest(path: Path) -> dict[str, Any]:
    data = new_manifest()
    if not path.exists():
        return data

    raw_data = _parse_simple_yaml(path.read_text(encoding="utf-8"))
    _merge(data, raw_data)
    return data


def dump_manifest(data: dict[str, Any]) -> str:
    lines: list[str] = []
    _write_mapping(lines, data, 0)
    return "\n".join(lines).rstrip() + "\n"


def save_manifest(path: Path, data: dict[str, Any]) -> None:
    path.write_text(dump_manifest(data), encoding="utf-8")


def text_to_value(path: str, text: str) -> Any:
    if path in LIST_FIELDS:
        return [line.strip() for line in text.splitlines() if line.strip()]
    return text.strip()


def value_to_text(path: str, value: Any) -> str:
    if path in LIST_FIELDS and isinstance(value, list):
        return "\n".join(str(item) for item in value)
    if value is None:
        return ""
    return str(value)


def _deep_copy(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _deep_copy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_deep_copy(item) for item in value]
    return value


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, list):
        return len(value) == 0
    return False


def _merge(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge(target[key], value)
        else:
            target[key] = value


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]
    list_targets: dict[tuple[int, str], list[str]] = {}

    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        if line.startswith("- "):
            parent_indent, parent = stack[-1]
            key = next(reversed(parent), None)
            if key is not None:
                target_key = (parent_indent, key)
                items = list_targets.setdefault(target_key, [])
                parent[key] = items
                items.append(_strip_yaml_value(line[2:]))
            continue

        while stack and indent <= stack[-1][0]:
            stack.pop()

        key, _, value = line.partition(":")
        key = key.strip()
        parsed_value: Any = _strip_yaml_value(value)
        parent = stack[-1][1]
        if value.strip() == "":
            parent_path = _path_for_mapping(root, parent)
            field_path = f"{parent_path}.{key}" if parent_path else key
            if field_path in LIST_FIELDS:
                parsed_value = []
            elif field_path in MAPPING_FIELDS:
                parsed_value = {}
                stack.append((indent, parsed_value))
            else:
                parsed_value = ""
        parent[key] = parsed_value

    return root


def _strip_yaml_value(value: str) -> Any:
    value = value.strip()
    if not value or value.startswith("#"):
        return ""
    if value == "[]":
        return []
    if " #" in value:
        value = value.split(" #", 1)[0].rstrip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _path_for_mapping(root: dict[str, Any], target: dict[str, Any]) -> str:
    if root is target:
        return ""

    def visit(node: dict[str, Any], prefix: str) -> str | None:
        for key, value in node.items():
            if not isinstance(value, dict):
                continue
            path = f"{prefix}.{key}" if prefix else key
            if value is target:
                return path
            found = visit(value, path)
            if found is not None:
                return found
        return None

    return visit(root, "") or ""


def _write_mapping(lines: list[str], data: dict[str, Any], indent: int) -> None:
    prefix = " " * indent
    for key, value in data.items():
        if isinstance(value, dict):
            lines.append(f"{prefix}{key}:")
            _write_mapping(lines, value, indent + 2)
        elif isinstance(value, list):
            if value:
                lines.append(f"{prefix}{key}:")
                for item in value:
                    lines.append(f"{prefix}  - {_format_scalar(item)}")
            else:
                lines.append(f"{prefix}{key}: []")
        else:
            lines.append(f"{prefix}{key}: {_format_scalar(value)}")


def _format_scalar(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    if text == "":
        return ""
    if any(char in text for char in [":", "#", "{", "}", "[", "]"]) or text[:1] in {"@", "`", "-", "!"}:
        escaped = text.replace('"', '\\"')
        return f'"{escaped}"'
    return text
