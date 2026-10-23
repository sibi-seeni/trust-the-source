"""Prompt text shared by the arms. Everything except the freshness line and the
per-arm extras is identical across arms."""

BASE_SYSTEM = (
    "You answer questions using the source passages provided with each question. "
    "Answer in one to three sentences and cite the passage numbers you relied on, like [2]."
)

# The A1 line from the design doc. Arms A1-A7 all carry it; A0 doesn't.
FRESHNESS_LINE = "Check document dates or versions; prefer the most current; say if a source may be outdated."

A4_NOTE = ("Each passage carries a 'Registry check' line written by the system after looking the "
           "document up in the authoritative version registry.")

A7_NOTE = ("A separate verifier has already checked the retrieved documents against the authoritative "
           "version registry; its report follows the passages.")

VERIFIER_SYSTEM = """You verify the source documents behind a set of retrieved passages before anyone answers from them.

For each distinct document, call check_latest_version with its title or filename (include any version or date you know). Compare what the registry returns with what the passage text itself says.

When you're done, reply with only a JSON array, one object per document:
[{"doc": "<filename>", "status": "current|superseded|withdrawn|amended|unverifiable|inconsistent|unable_to_verify", "latest_value": "<newer version or value if known, else null>", "confidence": "high|medium|low", "note": "<one sentence>"}]

Status meanings: superseded/withdrawn = registry says a newer version replaces it; amended = registry lists in-place changes dated after the text; unverifiable = the text and title carry no date or version you can match; inconsistent = filename and text disagree on the date or version; unable_to_verify = the registry errored or timed out."""

LOAD_SKILL_DECL = {
    "name": "load_skill",
    "description": ("Load a skill: a short procedure for a specific kind of task, which may also unlock extra tools. "
                    "Available skills: 'version-check' (how to verify whether source documents are the latest version)."),
    "parameters": {
        "type": "object",
        "properties": {"name": {"type": "string", "description": "Skill name, e.g. 'version-check'."}},
        "required": ["name"],
    },
}

VERIFY_SOURCES_DECL = {
    "name": "verify_sources",
    "description": ("Hand the retrieved passages to a verifier agent that checks each source document against "
                    "the authoritative version registry. Returns one JSON object per document: "
                    "{doc, status, latest_value, confidence, note}."),
}


def format_passages(passages, metadata: bool = False, annotations: dict | None = None) -> str:
    blocks = []
    for i, p in enumerate(passages, 1):
        head = f'[{i}] Source: {p.filename} | "{p.title}"'
        if metadata:
            m = p.ingest
            head += f"\n    Metadata: date={m['date']} | version={m['version']} | status={m['status']}"
        if annotations and p.pid in annotations:
            head += f"\n    Registry check: {annotations[p.pid]}"
        blocks.append(f"{head}\n{p.text}")
    return "\n\n".join(blocks)


def user_message(question: str, passages_block: str, extra: str = "") -> str:
    msg = f"Question: {question}\n\nSource passages:\n\n{passages_block}"
    if extra:
        msg += f"\n\n{extra}"
    return msg
