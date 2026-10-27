import math
from typing import Protocol


class TokenEstimator(Protocol):
    def estimate(self, text: str) -> int: ...


class ApproximateTokenizer:
    def estimate(self, text: str) -> int:
        # UTF-8 weighting is more conservative for non-Latin text than len(text)/4.
        return math.ceil(len(text.encode("utf-8")) / 4)
