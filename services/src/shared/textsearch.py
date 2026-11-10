"""Tiny keyword search (BM25) so search does not depend on the embedding model alone.

BM25 is the classic "how well do the query words match this document" score used by search engines:
- a word that appears in few documents counts more than a word that appears in many (rare = informative),
- repeating a word in one document helps, but with diminishing returns,
- long documents are not favoured just for being long.
Embeddings are good at meaning ("robots in the future"); BM25 is good at exact words ("llama", "Koro"). Search uses both.
Pure Python, no dependencies; with ~20 titles it runs in microseconds.
"""
import math
import re

STOPWORDS = frozenset(
    ["a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from", "has", "have", "he", "her", "his", "i", "in", "into", "is", "it", "its", "of", "on", "or", "she", "that", "the", "their", "them", "then", "there", "they", "this", "to", "was", "were", "what", "when", "where", "which", "who", "will", "with", "you", "your", "about", "like", "movie", "film", "films"])
K1, B = 1.5, 0.75
TITLE_BOOST = 3  # the title is repeated this many times so a name match outweighs a passing mention in a description


def stem(word):
    """Very light stemming so 'robots' matches 'robot' and 'dragons' matches 'dragon' (not a full stemmer)."""
    for suffix in ("ies", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[:-len(suffix)] + ("y" if suffix == "ies" else "")
    return word


def tokenize(text):
    return [stem(w) for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOPWORDS]


def doc_tokens(item):
    """Tokens of one catalogue item: boosted title + the searchable text (genres and description) stored in the index."""
    title = item.get("title", "")
    return tokenize(" ".join([title] * TITLE_BOOST) + " " + item.get("text", ""))


def bm25_scores(query, items):
    """Return {item id: BM25 score} for the items that share at least one word with the query (others are omitted)."""
    q_terms = set(tokenize(query))
    docs = {it["id"]: doc_tokens(it) for it in items}
    if not q_terms or not docs:
        return {}
    n = len(docs)
    avg_len = sum(len(d) for d in docs.values()) / n or 1.0
    df = {t: sum(1 for d in docs.values() if t in d) for t in q_terms}
    scores = {}
    for doc_id, tokens in docs.items():
        s = 0.0
        for t in q_terms:
            tf = tokens.count(t)
            if tf:
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                s += idf * tf * (K1 + 1) / (tf + K1 * (1 - B + B * len(tokens) / avg_len))
        if s > 0:
            scores[doc_id] = s
    return scores
