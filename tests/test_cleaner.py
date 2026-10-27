from tests.test_extractor import extract


def test_cleaning_preserves_useful_aside():
    useful = "Important scientific context with evidence and caveats. " * 6
    _, blocks = extract(f"""<body><nav><a>Home</a></nav><div class="cookie-banner">Accept cookies</div>
        <p hidden>Secret</p><p style="display: none">Hidden</p><script>evil()</script>
        <aside><p>{useful}</p></aside><p>Main finding.</p></body>""")
    text = " ".join(b.text for b in blocks)
    assert useful.strip() in text
    for noise in ["Home", "Accept cookies", "Secret", "Hidden", "evil"]:
        assert noise not in text
