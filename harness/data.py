"""Loading the corpus and question set."""

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import config


@dataclass
class Passage:
    pid: str
    doc_id: str
    family: str
    filename: str
    title: str
    text: str
    locator: str
    ingest: dict


@dataclass
class Question:
    id: str
    family: str
    case: str
    question: str
    corpus: list
    gold_passages: list
    gold_answer: str
    alt_answer: str
    accept: list = field(default_factory=list)
    alt: list = field(default_factory=list)
    pilot: bool = False
    live: bool = False
    verified: bool = False


class Corpus:
    def __init__(self, docs_path: Path | None = None):
        raw = json.loads(Path(docs_path or config.DATA_DIR / "docs.json").read_text())
        self.docs = {d["doc_id"]: d for d in raw["docs"]}
        self.passages: dict[str, Passage] = {}
        for d in raw["docs"]:
            for p in d["passages"]:
                self.passages[p["pid"]] = Passage(
                    pid=p["pid"], doc_id=d["doc_id"], family=d["family"],
                    filename=d["filename"], title=d["title"], text=p["text"],
                    locator=p["locator"], ingest=d["ingest"],
                )

    def pool_for(self, q: Question) -> list[Passage]:
        """Passages 'in the corpus' for this question: its own docs plus the
        default docs of every other family as distractors."""
        doc_ids = set(q.corpus)
        for d in self.docs.values():
            if d.get("default_pool") and d["family"] != q.family:
                doc_ids.add(d["doc_id"])
        return [p for p in self.passages.values() if p.doc_id in doc_ids]


def load_questions(path: Path | None = None) -> list[Question]:
    raw = json.loads(Path(path or config.DATA_DIR / "questions.json").read_text())
    return [Question(**q) for q in raw["questions"]]


def load_registry(path: Path | None = None) -> dict:
    return json.loads(Path(path or config.DATA_DIR / "registry.json").read_text())
