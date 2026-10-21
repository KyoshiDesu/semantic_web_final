"""Text normalization, alias lookup into concept ids, and concept similarity (plan Section 4, sim)."""
import re
import unicodedata

import numpy as np

from autograde import io

STOPWORDS = {"yang", "dan", "di", "ke", "dari", "itu", "ini", "untuk", "dengan", "oleh", "pada", "adalah",
             "sebagai", "juga", "akan", "atau", "para", "serta", "lalu", "kemudian", "sang", "si", "nya",
             "tersebut", "dalam", "secara", "bisa", "dapat", "maka", "karena", "agar", "supaya", "the"}


def norm_text(text):
    text = unicodedata.normalize("NFKC", text or "").lower()
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text)).strip()


def content_tokens(text):
    return [t for t in norm_text(text).split() if t not in STOPWORDS]


class ConceptIndex:
    """Maps surface text to a gold concept id through the lecturer's alias table."""

    def __init__(self, concepts):
        self.lookup_table = {}
        for cid, spec in concepts.items():
            for surface in [cid, *((spec or {}).get("aliases") or [])]:
                self.lookup_table[norm_text(surface)] = cid
                self.lookup_table[" ".join(content_tokens(surface))] = cid

    def lookup(self, text):
        return self.lookup_table.get(norm_text(text)) or self.lookup_table.get(" ".join(content_tokens(text)))


def fill_concepts(triples, index):
    return [t.model_copy(update={"s_concept": index.lookup(t.s_text), "o_concept": index.lookup(t.o_text)})
            for t in triples]


class Embedder:
    """Sentence-transformers embeddings with an on-disk cache keyed by model name and text."""

    def __init__(self, model_name=None):
        self.model_name = model_name or io.load_config()["embedding_model"]
        self.path = io.ROOT / "outputs" / "cache" / "embeddings" / (self.model_name.replace("/", "__") + ".json")
        self.cache = io.load_json(self.path) if self.path.exists() else {}
        self._model = None

    def vector(self, text):
        if text not in self.cache:
            if self._model is None:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(self.model_name)
            self.cache[text] = self._model.encode(text, normalize_embeddings=True).tolist()
            io.save_json(self.cache, self.path)
        return np.asarray(self.cache[text])

    def cosine(self, a, b):
        if a == b:
            return 1.0
        return float(np.clip(self.vector(a) @ self.vector(b), 0.0, 1.0))


def make_sim(cosine):
    """sim(concept_a, text_a, concept_b, text_b): two known concepts compare by id only (no embedding)."""
    def sim(ca, ta, cb, tb):
        if ca and cb:
            return 1.0 if ca == cb else 0.0
        return cosine(norm_text(ca or ta), norm_text(cb or tb))
    return sim
