from app.models.request import Options
from app.services.formatter import Formatter
from tests.test_extractor import extract


def test_budget_and_metrics():
    parsed, blocks = extract("<main><h1>Results</h1><p>" + "Useful research. " * 100 + "</p></main>")
    result = Formatter().format(parsed, blocks, Options(max_content_length=100), None, 2000, {})
    assert len(result.content.main_text) == 100
    assert result.optimization.estimated_tokens_saved > 0
    assert result.optimization.returned_characters == len(result.content.main_text)
    assert "Estimated content tokens" in Formatter.markdown(result)
