from backend.services import credibility, notify


def test_alert_escapes_user_text():
    watch = {"claim": '<img src=x onerror="alert(1)">', "verdict": "false", "previous_verdict": "true",
             "history": [{"explanation": "<script>steal()</script> & 更多"}]}
    title, body = notify.message(watch, 'https://example.com/r/abc"><script>')
    assert title == "盯梢提醒：结论从「属实」变成「不实」"
    assert "<img" not in body and "<script>" not in body
    assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in body
    assert "&lt;script&gt;steal()&lt;/script&gt; &amp; 更多" in body
    assert 'href="https://example.com/r/abc&quot;&gt;&lt;script&gt;"' in body


def test_alert_without_history():
    _, body = notify.message({"claim": "说法", "verdict": "true", "previous_verdict": "x", "history": []}, "/r/1")
    assert "<b>说法</b>" in body


def test_tiers():
    assert credibility.tier("https://www.piyao.org.cn/a") == "debunk"
    assert credibility.tier("https://wsjkw.sh.gov.cn/x") == "official"
    assert credibility.tier("https://mp.weixin.qq.com/s/x") == "self"
    assert credibility.tier("https://www.dxy.cn/x") == "expert"
    assert credibility.tier("https://news.people.com.cn/x") == "media"
    assert credibility.tier("https://notpeople.com.cn/x") == "other"
    assert credibility.tier("https://example.com/x") == "other"


def test_digest_only_for_self_media_and_unknown_sites():
    assert credibility.is_digest("https://mp.weixin.qq.com/s/x", "AI 日报：今日要闻", "self")
    assert credibility.is_digest("https://weekly.example.com/x", "news", "other")
    assert not credibility.is_digest("https://www.people.com.cn/x", "人民日报评论", "media")
    assert not credibility.is_digest("https://example.com/x", "一篇普通文章", "other")
