"""Hybrid BM25 + dense retrieval (reciprocal rank fusion), top-k, with the
question's gold passages always included. Retrieval isn't what's being tested,
so it runs once per question and every arm sees the same passages."""

import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path

import numpy as np

from . import config
from .data import Passage, Question

_TOKEN = re.compile(r"[a-z0-9]+(?:[.\-][a-z0-9]+)*")


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.docs, self.k1, self.b = docs, k1, b
        self.avgdl = sum(map(len, docs)) / max(len(docs), 1)
        df = Counter(t for d in docs for t in set(d))
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self.tfs = [Counter(d) for d in docs]

    def scores(self, query: list[str]) -> list[float]:
        out = []
        for d, tf in zip(self.docs, self.tfs):
            s = 0.0
            for t in query:
                if t in tf:
                    f = tf[t]
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * len(d) / self.avgdl))
            out.append(s)
        return out


class GeminiEmbedder:
    """Embeds text with the Gemini embedding model, cached on disk."""

    def __init__(self, client, model: str = config.EMBED_MODEL, cache_path: Path | None = None):
        self.client, self.model = client, model
        self.cache_path = cache_path or config.CACHE_DIR / "embeddings.json"
        self.cache = json.loads(self.cache_path.read_text()) if self.cache_path.exists() else {}

    def _key(self, text: str) -> str:
        return hashlib.sha256(f"{self.model}\n{text}".encode()).hexdigest()

    def embed(self, texts: list[str]) -> np.ndarray:
        missing = [t for t in dict.fromkeys(texts) if self._key(t) not in self.cache]
        for i in range(0, len(missing), 50):
            batch = missing[i:i + 50]
            resp = self.client.models.embed_content(model=self.model, contents=batch)
            embs = resp.embeddings or []
            if len(embs) != len(batch):
                # Some models fold a multi-part request into one embedding; go one at a time.
                embs = [self.client.models.embed_content(model=self.model, contents=t).embeddings[0]
                        for t in batch]
            for t, e in zip(batch, embs):
                self.cache[self._key(t)] = e.values
        if missing:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(self.cache))
        return np.array([self.cache[self._key(t)] for t in texts], dtype=float)


def _rrf(rankings: list[list[int]], k: int = 60) -> dict[int, float]:
    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, idx in enumerate(ranking):
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (k + rank + 1)
    return fused


def retrieve(q: Question, pool: list[Passage], embedder=None, top_k: int = config.TOP_K) -> list[Passage]:
    texts = [f"{p.title}\n{p.text}" for p in pool]
    bm = BM25([tokenize(t) for t in texts]).scores(tokenize(q.question))
    rankings = [sorted(range(len(pool)), key=lambda i: -bm[i])]
    if embedder is not None:
        vecs = embedder.embed(texts + [q.question])
        vecs = vecs / np.linalg.norm(vecs, axis=1, keepdims=True)
        sims = vecs[:-1] @ vecs[-1]
        rankings.append(sorted(range(len(pool)), key=lambda i: -sims[i]))
    fused = _rrf(rankings)
    order = sorted(range(len(pool)), key=lambda i: (-fused[i], pool[i].pid))

    gold = [i for i in order if pool[i].pid in q.gold_passages]
    missing = set(q.gold_passages) - {pool[i].pid for i in gold}
    if missing:
        raise ValueError(f"{q.id}: gold passages {sorted(missing)} aren't in the question's corpus")
    chosen = set(gold)
    for i in order:
        if len(chosen) >= max(top_k, len(gold)):
            break
        chosen.add(i)
    # Keep fused-score order so gold passages aren't always listed first.
    return [pool[i] for i in order if i in chosen]
