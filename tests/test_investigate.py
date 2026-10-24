from backend.services import investigate as inv
from backend.services.yuanbao import Page

OFFICIAL = "https://wsjkw.example.gov.cn/notice"
MEDIA = "https://www.people.com.cn/n1/2026/tea.html"
BLOG = "https://example.com/post"
DIGEST = "https://mp.weixin.qq.com/s/abc"


def make_pool(*pages: tuple[str, str, str]) -> tuple[inv.SourcePool, list[str]]:
    pool = inv.SourcePool()
    ids = [pool.add(Page(title=title, url=url, passage=passage), "q") for url, title, passage in pages]
    return pool, ids


def judged(verdict: str, *evidence: tuple[str, str, str], confidence: int = 90) -> dict:
    return {"verdict": verdict, "confidence": confidence, "explanation": "解释",
            "evidence": [{"source": s, "quote": q, "stance": st} for s, q, st in evidence]}


# --- the verdict guard ---------------------------------------------------------------------------

def test_true_backed_by_verified_support_stands():
    pool, (s1,) = make_pool((OFFICIAL, "通知", "经检测，隔夜茶中亚硝酸盐含量远低于安全标准。"))
    r = inv._check(judged("true", (s1, "隔夜茶中亚硝酸盐含量远低于安全标准", "support")), "c", [s1], pool)
    assert r["verdict"] == "true"
    assert r["confidence"] == 90
    assert not r["guard"]


def test_false_backed_only_by_verified_context_is_downgraded():
    # The verified quote is only background; the refuting quote is made up.
    pool, (s1, s2) = make_pool((OFFICIAL, "通知", "隔夜茶中亚硝酸盐含量很低。"), (BLOG, "文章", "无关内容"))
    r = inv._check(judged("false", (s1, "隔夜茶中亚硝酸盐含量很低", "context"),
                          (s2, "隔夜茶致癌的说法已被证实是谣言", "refute")), "c", [s1, s2], pool)
    assert r["verdict"] == "unknown"
    assert r["guard"]
    assert r["confidence"] <= 30


def test_true_backed_only_by_verified_refute_is_downgraded():
    pool, (s1,) = make_pool((OFFICIAL, "通知", "微信转账不会收取手续费。"))
    r = inv._check(judged("true", (s1, "微信转账不会收取手续费", "refute")), "c", [s1], pool)
    assert r["verdict"] == "unknown"
    assert r["guard"]


def test_mixed_accepts_either_stance():
    pool, (s1,) = make_pool((OFFICIAL, "通知", "部分地区自下月起执行新的限行规定。"))
    r = inv._check(judged("mixed", (s1, "部分地区自下月起执行新的限行规定", "refute")), "c", [s1], pool)
    assert r["verdict"] == "mixed"
    assert not r["guard"]


def test_unknown_needs_no_backing():
    pool, (s1,) = make_pool((OFFICIAL, "通知", "内容"))
    r = inv._check(judged("unknown", confidence=40), "c", [s1], pool)
    assert r["verdict"] == "unknown"
    assert not r["guard"]


def test_citations_of_unseen_sources_are_dropped():
    pool, (s1, s2) = make_pool((OFFICIAL, "通知", "隔夜茶可以喝。"), (MEDIA, "报道", "隔夜茶可以喝。"))
    # s2 exists in the pool but this claim never saw it, and S99 does not exist at all.
    r = inv._check(judged("true", (s2, "隔夜茶可以喝", "support"), ("S99", "隔夜茶可以喝", "support")),
                   "c", [s1], pool)
    assert r["evidence"] == []
    assert r["verdict"] == "unknown"


def test_bad_verdict_and_confidence_are_normalised():
    pool, (s1,) = make_pool((OFFICIAL, "通知", "内容"))
    r = inv._check({"verdict": "maybe", "confidence": "lots", "stance": "x"}, "c", [s1], pool)
    assert r["verdict"] == "unknown"
    assert r["confidence"] == 0


def test_digest_only_support_caps_confidence_and_asks_for_more():
    pool, (s1,) = make_pool((DIGEST, "AI 日报：本周大事汇总", "某公司发布了新一代大模型，参数量翻倍。"))
    r = inv._check(judged("true", (s1, "某公司发布了新一代大模型", "support")), "某公司发布新模型", [s1], pool)
    assert r["verdict"] == "true"
    assert r["caution"]
    assert r["confidence"] <= inv.DIGEST_CAP
    assert r["need_more"]
    assert r["next_queries"]


def test_independent_source_avoids_the_cap():
    pool, (s1, s2) = make_pool((DIGEST, "AI 日报", "某公司发布了新一代大模型。"),
                               (MEDIA, "报道", "某公司今天发布了新一代大模型。"))
    r = inv._check(judged("true", (s1, "某公司发布了新一代大模型", "support"),
                          (s2, "某公司今天发布了新一代大模型", "support")), "c", [s1, s2], pool)
    assert not r["caution"]
    assert r["confidence"] == 90


# --- quote matching ------------------------------------------------------------------------------

def test_quote_found_exact_and_ignores_punctuation():
    passage = "专家表示：隔夜茶，只要没有变质，是可以喝的。"
    assert inv._quote_found("隔夜茶只要没有变质是可以喝的", passage)
    assert inv._quote_found("“隔夜茶，只要没有变质”", passage)


def test_quote_found_tolerates_a_changed_character_in_long_quotes():
    passage = "国家卫健委相关负责人表示隔夜茶中的亚硝酸盐含量远远低于国家安全标准"
    assert inv._quote_found("国家卫健委相关负责人表示隔夜茶里的亚硝酸盐含量远远低于国家安全标准", passage)


def test_quote_found_rejects_short_near_misses_and_paraphrases():
    passage = "国家卫健委相关负责人表示隔夜茶中的亚硝酸盐含量远远低于国家安全标准"
    assert not inv._quote_found("隔夜茶里亚硝酸盐", passage)
    assert not inv._quote_found("卫生部门认为喝隔夜的茶水不会对健康造成任何影响", passage)
    assert not inv._quote_found("", passage)


# --- overall verdict -----------------------------------------------------------------------------

def test_overall():
    def o(*vs):
        return inv.overall([{"verdict": v} for v in vs])
    assert o() == "unknown"
    assert o("unknown", "unknown") == "unknown"
    assert o("true", "true") == "true"
    assert o("false", "unknown") == "false"
    assert o("true", "unknown") == "true"
    assert o("true", "false") == "mixed"
    assert o("mixed") == "mixed"


# --- sources -------------------------------------------------------------------------------------

def test_source_pool_dedupes_by_url_and_keeps_longer_passage():
    pool = inv.SourcePool()
    a = pool.add(Page(title="t", url=OFFICIAL, passage="短"), "q1")
    b = pool.add(Page(title="t", url=OFFICIAL, passage="长一点的摘录"), "q2")
    assert a == b == "S1"
    assert pool.by_id["S1"]["passage"] == "长一点的摘录"
    assert pool.by_id["S1"]["queries"] == ["q1", "q2"]
    assert pool.by_id["S1"]["tier"] == "official"


def test_prompts_format():
    # A stray brace in a prompt only shows up as a KeyError mid-investigation.
    assert "S1" in inv.JUDGE.format(today="今天", claim="c", queries="q", sources="[S1] x", round=1, max_rounds=3)
    assert inv.PLAN.format(today="今天", text="t", image_note="", max_claims=3)
    assert inv.SUMMARY.format(today="今天", text="t", results="r")
