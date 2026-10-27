from app.services.cleaner import ContentCleaner
from app.services.extractor import ContentExtractor
from app.services.parser import HTMLParser


def extract(html):
    parsed = HTMLParser().parse(html, "https://example.com")
    return parsed, ContentExtractor().extract(ContentCleaner().clean(parsed.soup), "https://example.com")


def test_metadata_links_tables_code_and_duplicates():
    page, blocks = extract("""<html lang="en"><title>Guide</title><meta name="description" content="A guide">
    <script type="application/ld+json">{"@type":"Article"}</script><main><h1>Setup</h1>
    <p>Install the <a href="/sdk">SDK</a> to begin.</p><p>Install the <a href="/sdk">SDK</a> to begin.</p>
    <pre>if True:\n    print("ok")</pre><table><tr><th>Speed</th><td>42</td></tr></table></main></html>""")
    assert page.page.title == "Guide"
    assert page.metadata["structured_data"][0]["@type"] == "Article"
    assert len(blocks) == 3
    assert blocks[0].links[0].url == "https://example.com/sdk"
    assert "    print" in blocks[1].text
    assert "Speed | 42" in blocks[2].text


def test_plain_fragment():
    assert extract("Hello, meaningful plain text.")[1][0].text == "Hello, meaningful plain text."
