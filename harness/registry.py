"""Mock version registry, exposed to the model as check_latest_version(title_or_id)."""

import re

from . import config


def _norm(s: str) -> str:
    return re.sub(r"[_/]+", " ", s.lower())


def _has_version_alias(text: str, alias: str) -> bool:
    return re.search(r"(?<![\w.])" + re.escape(alias) + r"(?!\w)", text) is not None


class MockRegistry:
    def __init__(self, registry: dict, unavailable: bool = False):
        self.families = registry["families"]
        self.unavailable = unavailable

    def lookup(self, title_or_id: str) -> dict:
        if self.unavailable:
            return {"error": f"TIMEOUT: version registry did not respond within {config.REGISTRY_TIMEOUT_S}s",
                    "query": title_or_id}
        q = _norm(title_or_id or "")
        hits = [name for name, fam in self.families.items()
                if any(a in q for a in fam["aliases"])]
        if not hits:
            return {"query": title_or_id, "found": False,
                    "message": "No registry entry matches this title or id."}
        results = [self._family_result(name, q) for name in hits]
        out = results[0] if len(results) == 1 else {"results": results}
        out["query"] = title_or_id
        return out

    def _family_result(self, name: str, q: str) -> dict:
        fam = self.families[name]
        matched = [v for v in fam["versions"]
                   if any(_has_version_alias(q, a) for a in v["aliases"])]
        if not matched:
            return {
                "found": True, "family": name, "version": "unknown", "latest": fam["latest"],
                "note": "The query doesn't identify a version, so the document's own version can't be confirmed. Known versions:",
                "versions": [self._entry(name, fam, v) for v in fam["versions"]],
            }
        entries = [self._entry(name, fam, v) for v in matched]
        if len(entries) == 1:
            return {"found": True, **entries[0]}
        return {"found": True, "family": name, "latest": fam["latest"],
                "note": "Several versions match the query.", "versions": entries}

    @staticmethod
    def _entry(name: str, fam: dict, v: dict) -> dict:
        e = {"family": name, "version": v["version"], "effective": v["effective"],
             "status": v["status"], "superseded_by": v.get("superseded_by"), "latest": fam["latest"]}
        for k in ("withdrawn", "changes"):
            if k in v:
                e[k] = v[k]
        return e


CHECK_LATEST_VERSION_DECL = {
    "name": "check_latest_version",
    "description": ("Look up a document in the authoritative version registry. Returns the version, "
                    "effective date, status (current / superseded / withdrawn), what supersedes it, "
                    "the latest version, and any in-place changes on record."),
    "parameters": {
        "type": "object",
        "properties": {
            "title_or_id": {"type": "string",
                            "description": "Document title, filename or identifier, including any version or date you know."},
        },
        "required": ["title_or_id"],
    },
}
