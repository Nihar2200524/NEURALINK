from app.models.response import ContentBlock
from app.services.relevance import RelevanceEngine


def test_query_ranks_relevant_information():
    blocks = [
        ContentBlock(id="a", tag="p", text="Apple released a new AI model for on-device inference."),
        ContentBlock(id="b", tag="p", text="The orchard produced many apples this summer."),
    ]
    ranked = RelevanceEngine().rank("What did Apple announce about its new AI model?", blocks)
    assert ranked[0].id == "a"
    assert len(ranked) == 1


def test_no_match_is_empty():
    assert RelevanceEngine().rank("quantum", [ContentBlock(id="a", tag="p", text="Bananas.")]) == []


def test_generic_page_question_returns_main_content():
    blocks = [ContentBlock(id="a", tag="p", text="Example Domain.")]
    assert RelevanceEngine().rank("What is this page about?", blocks) == blocks
