"""
Text Chunking

Splits long documents into overlapping chunks small enough to embed
meaningfully and retrieve precisely. Chunking on paragraph/sentence
boundaries (rather than a hard character cut) keeps each chunk coherent,
which matters for retrieval quality — a chunk truncated mid-sentence
embeds poorly and reads worse if it ends up quoted back to a caller.
"""

import re

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _split_into_sentences(text: str) -> list[str]:
    """Split on sentence boundaries, collapsing internal whitespace."""
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []
    return [s for s in _SENTENCE_SPLIT_RE.split(normalized) if s]


def chunk_text(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """
    Split text into chunks of roughly `chunk_size` characters, built up
    from whole sentences, with roughly `chunk_overlap` characters of
    overlap carried into the next chunk for retrieval continuity across
    a chunk boundary.

    Args:
        text: Raw document text.
        chunk_size: Target maximum characters per chunk.
        chunk_overlap: Target characters of trailing context repeated at
            the start of the next chunk. Must be smaller than chunk_size.

    Returns:
        Non-empty chunks, in document order. Empty input returns [].
    """
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")

    sentences = _split_into_sentences(text)
    if not sentences:
        return []

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for sentence in sentences:
        # A single sentence longer than chunk_size gets its own chunk
        # rather than being silently dropped or blowing past the target.
        if len(sentence) > chunk_size:
            if current:
                chunks.append(" ".join(current))
                current, current_len = [], 0
            chunks.append(sentence)
            continue

        if current_len + len(sentence) + 1 > chunk_size and current:
            chunks.append(" ".join(current))

            # Carry trailing sentences into the next chunk as overlap,
            # up to the requested overlap budget.
            overlap_sentences: list[str] = []
            overlap_len = 0
            for s in reversed(current):
                if overlap_len + len(s) > chunk_overlap:
                    break
                overlap_sentences.insert(0, s)
                overlap_len += len(s) + 1
            current, current_len = overlap_sentences, overlap_len

        current.append(sentence)
        current_len += len(sentence) + 1

    if current:
        chunks.append(" ".join(current))

    return chunks
