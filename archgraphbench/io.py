"""Local data I/O. No network, manuscript reader, or cached-score loader."""
from __future__ import annotations
from .execution_log import info, debug
import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable
try:
    import yaml
except ModuleNotFoundError:
    yaml = None  # JSON-only diagnostic calculations need only the standard library.


def read_json(path: Path) -> Any:
    """Load local UTF-8 JSON and reject duplicate keys rather than silently merge."""
    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError(f"Duplicate JSON key {key!r} in {path}")
            out[key] = value
        return out
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    debug("IO", "JSON_READ", "Read a local JSON artifact without logging its entire contents.", file=path)
    return value


def write_json(path: Path, value: Any) -> None:
    """Write inspectable deterministic JSON; undefined scores must be None."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    debug("IO", "JSON_WRITTEN", "Write a newly generated JSON artifact.", file=path)


def write_csv(path: Path, rows: Iterable[dict], fields: list[str] | None = None) -> None:
    """Write rows in stable order and serialize nested evidence inside cells."""
    rows = list(rows)
    if fields is None:
        fields = list(dict.fromkeys(k for row in rows for k in row))
    if not fields:
        raise ValueError(f"No columns specified for empty table: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    def cell(v):
        if isinstance(v, (dict, list, tuple)):
            return json.dumps(v, sort_keys=True, allow_nan=False)
        return v
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows({k: cell(v) for k, v in row.items()} for row in rows)
    debug("IO", "CSV_WRITTEN", "Write calculated records in stable row order.", file=path, rows=len(rows), columns=fields)


def sha256(path: Path) -> str:
    """Digest bytes for local consistency checks, not publisher authentication."""
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def inventory(root: Path) -> dict[str, str]:
    """Return a stable relative-path to SHA-256 inventory of existing files."""
    return {p.relative_to(root).as_posix(): sha256(p) for p in sorted(root.rglob("*")) if p.is_file()}


def child(root: Path, relative: str) -> Path:
    """Resolve a manifest-relative filename without allowing directory traversal."""
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"Path leaves data directory: {relative}")
    return path


def check_data_manifest(root: Path) -> dict:
    """Compare retained source bytes with the declared frozen input inventory."""
    manifest = read_json(root / "input_manifest.json")
    checked, mismatches = [], []
    for row in manifest["files"]:
        path = child(root, row["path"])
        actual = sha256(path) if path.is_file() else None
        checked.append({"path": row["path"], "expected": row["sha256"], "actual": actual,
                        "match": actual == row["sha256"]})
        if actual != row["sha256"]:
            mismatches.append(row["path"])
    return {"checked_files": len(checked), "matches": not mismatches,
            "mismatches": mismatches, "records": checked, "caveats": manifest.get("caveats", [])}


class UniqueSafeLoader(yaml.SafeLoader if yaml is not None else object):
    """Safe YAML plus duplicate mapping-key rejection."""


def _mapping(loader, node, deep=False):
    """Build a YAML mapping while rejecting repeated keys in the same mapping."""
    loader.flatten_mapping(node)
    out = {}
    for k, v in node.value:
        key = loader.construct_object(k, deep=deep)
        if key in out:
            raise ValueError(f"Duplicate YAML key {key!r} at line {k.start_mark.line + 1}")
        out[key] = loader.construct_object(v, deep=deep)
    return out


if yaml is not None:
    UniqueSafeLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


class YamlSource:
    """Parsed objects plus line/field witnesses computed from the actual YAML."""
    def __init__(self, path: Path, file_id: str | None = None):
        if yaml is None:
            raise ImportError("YAML reconstruction requires PyYAML; install requirements.txt")
        debug("IO", "YAML_READ", "Read source bytes and parse mappings with duplicate-key/resource checks.", file=path)
        self.path = path
        self.file_id = file_id or path.name
        self.digest = sha256(path)
        text = path.read_text(encoding="utf-8")
        docs = list(yaml.load_all(text, Loader=UniqueSafeLoader))
        nodes = list(yaml.compose_all(text, Loader=yaml.SafeLoader))
        self.objects = []
        self.index = {}
        self.fields = {}
        for doc, node in zip(docs, nodes):
            if doc is None:
                continue
            if not isinstance(doc, dict):
                raise ValueError(f"Non-object YAML document in {path}")
            pairs = [(doc, node)]
            if doc.get("kind") == "List":
                item_node = self._lookup(node, ["items"])
                pairs = list(zip(doc.get("items", []), item_node.value))
            for obj, obj_node in pairs:
                if not isinstance(obj, dict) or "kind" not in obj or "name" not in obj.get("metadata", {}):
                    raise ValueError(f"Resource lacks kind/metadata.name in {path}")
                ident = (obj["kind"], obj["metadata"].get("namespace", "default"), obj["metadata"]["name"])
                if ident in self.index:
                    raise ValueError(f"Duplicate resource {ident} in {path}")
                self.objects.append(obj)
                self.index[ident] = obj
                self.fields[ident] = obj_node
        info("IO", "YAML_PARSED", "Retain the source hash and parser locations for later witnesses.",
             file=self.file_id, sha256=self.digest, resources=len(self.objects))

    @staticmethod
    def _lookup(node, parts):
        """Walk YAML syntax nodes so provenance uses source lines, not guesses."""
        for part in parts:
            if isinstance(node, yaml.nodes.MappingNode):
                matches = [v for k, v in node.value if k.value == str(part)]
                if len(matches) != 1:
                    raise KeyError(part)
                node = matches[0]
            elif isinstance(node, yaml.nodes.SequenceNode):
                node = node.value[int(part)]
            else:
                raise KeyError(part)
        return node

    def locate(self, kind: str, name: str, field: str = "", namespace: str = "default") -> dict:
        """Return the real parser-derived source line range for a resource field."""
        ident = (kind, namespace, name)
        try:
            node = self._lookup(self.fields[ident], [p for p in field.split("/") if p])
        except (KeyError, IndexError, ValueError) as exc:
            raise ValueError(f"Unresolvable locator {kind}/{namespace}/{name}/{field}") from exc
        end = node.end_mark.line + (1 if node.end_mark.column else 0)
        return {"file": self.file_id, "sha256": self.digest, "kind": kind, "namespace": namespace,
                "name": name, "field": field, "lines": [node.start_mark.line + 1, max(node.start_mark.line + 1, end)]}

    def legacy_locator(self, locator: str) -> dict:
        """Resolve the historical Kind/name/field notation in the default namespace."""
        kind, name, *field = locator.split("/")
        return self.locate(kind, name, "/".join(field))
