import math
from collections import Counter
from typing import Protocol

from app.models.response import ContentBlock
from app.utils.text import terms


class Ranker(Protocol):
    def rank(self, query: str, blocks: list[ContentBlock]) -> list[ContentBlock]: ...


class RelevanceEngine:
    def rank(self, query: str, blocks: list[ContentBlock]) -> list[ContentBlock]:
        keywords = set(terms(query))
        if keywords <= {"page", "website", "site", "main", "summary", "summarize", "overview", "give", "me"}:
            return blocks
        if not keywords or not blocks:
            return blocks
        documents = [terms(block.text) for block in blocks]
        average = sum(map(len, documents)) / len(documents) or 1
        frequency = Counter(term for document in documents for term in set(document))
        ranked = []
        for block, document in zip(blocks, documents):
            counts = Counter(document)
            score = 0.0
            for term in keywords:
                tf = counts[term]
                idf = math.log(1 + (len(blocks) - frequency[term] + 0.5) / (frequency[term] + 0.5))
                score += idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * len(document) / average))
            score += len(keywords & set(terms(block.heading))) * 1.5
            positions = [i for i, term in enumerate(document) if term in keywords]
            if len(set(document) & keywords) > 1:
                score += len(positions) / (1 + positions[-1] - positions[0])
            if score > 0:
                ranked.append(block.model_copy(update={"relevance_score": round(score, 4)}))
        return sorted(ranked, key=lambda b: (b.relevance_score, b.score), reverse=True)
