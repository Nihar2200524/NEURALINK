import re


def compact(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def terms(text: str) -> list[str]:
    stop = {
        "a",
        "an",
        "the",
        "and",
        "or",
        "of",
        "to",
        "in",
        "is",
        "are",
        "what",
        "how",
        "did",
        "about",
        "this",
        "it",
        "for",
        "with",
    }
    return [word for word in re.findall(r"[^\W_]+", text.casefold()) if word not in stop]
