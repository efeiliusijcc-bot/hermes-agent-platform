from __future__ import annotations

import hashlib
import math
import re
import unicodedata

EMBEDDING_MODEL = "hash-ngram-v1"
EMBEDDING_DIMENSIONS = 384
WORD_PATTERN = re.compile(r"\w+", re.UNICODE)


def embed_text(text: str) -> list[float]:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    compact = "".join(character for character in normalized if character.isalnum())
    features: list[tuple[str, float]] = [(f"word:{token}", 2.0) for token in WORD_PATTERN.findall(normalized)]
    for width, weight in ((1, 0.5), (2, 1.5), (3, 1.0)):
        features.extend(
            (f"char{width}:{compact[index:index + width]}", weight)
            for index in range(max(0, len(compact) - width + 1))
        )

    vector = [0.0] * EMBEDDING_DIMENSIONS
    for feature, weight in features:
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "big") % EMBEDDING_DIMENSIONS
        sign = 1.0 if digest[4] & 1 else -1.0
        vector[index] += sign * weight
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        vector[0] = 1.0
        return vector
    return [value / norm for value in vector]


def vector_literal(vector: list[float]) -> str:
    if len(vector) != EMBEDDING_DIMENSIONS:
        raise ValueError("embedding dimension mismatch")
    return "[" + ",".join(f"{value:.9f}" for value in vector) + "]"
