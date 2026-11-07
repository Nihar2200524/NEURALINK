import pytest
from agentra.session_manager import SessionManager
from agentra.page_reader import read_page, classify


async def test_read_during_continuous_mutation():
    manager = SessionManager()
    await manager.start()
    try:
        session = await manager.create('read-test')
        page = session.pages['tab_0']
        await page.set_content('<h1>Live report</h1><p>Hyderabad price report with useful content.</p><div id="tick"></div><script>setInterval(()=>document.querySelector("#tick").textContent=Date.now(),10)</script>')
        result = await read_page(page)
        assert result['status'] == 'CONTENT_AVAILABLE'
        assert 'Hyderabad' in result['content']
        assert result['task_completed'] is False
    finally:
        await manager.close()


def test_google_challenge_is_not_success():
    assert classify('https://google.com/sorry/index', '', 'Our systems have detected unusual traffic') == 'HUMAN_REQUIRED'


def test_article_mentioning_captcha_is_readable():
    assert classify('https://example.com/article', 'How CAPTCHA works', 'A long educational article about CAPTCHA and accessibility for ordinary readers.') == 'CONTENT_AVAILABLE'
