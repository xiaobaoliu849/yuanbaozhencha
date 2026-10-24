"""The investigation: read the rumor, split it into checkable claims, search in rounds, judge on evidence.

Every verdict must point at sources that 元宝搜索 actually returned. Citations of unknown sources
are dropped, quotes are checked against the source text, and a claim left with no evidence is
forced to 「查不到」 — the model is never allowed to answer from its own memory.
"""
from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any

from . import credibility, llm, yuanbao

logger = logging.getLogger(__name__)

MAX_CLAIMS = 3
MAX_ROUNDS = 3
PAGES_PER_QUERY = 6
PASSAGE_CHARS = 700
QUOTE_MATCH = 0.85
DIGEST_CAP = 60  # max confidence when only roundups / self-media back a verdict
STALE_DAYS = 730
# Users are in China and Beijing has no DST, so a fixed offset avoids needing tzdata on Windows.
BEIJING = timezone(timedelta(hours=8))
VERDICTS = {"true": "属实", "false": "不实", "mixed": "部分属实", "unknown": "查不到"}
# Which quote stances can carry each verdict.
BACKS = {"true": ("support",), "false": ("refute",), "mixed": ("support", "refute")}

Emit = Callable[[dict[str, Any]], Awaitable[None]]

PLAN = """你是「查得到，信得过」的调查员，专门帮普通人查证家族群、朋友圈里的传言。
今天是 {today}。

用户给你的内容：
<<<
{text}
>>>
{image_note}

请完成：
1. 如果有截图，把截图里的文字和要查证的说法原样读出来，写进 readable_text；没有截图就复述用户的文字。
2. 判断是否属于不能查的范围：时政（政党、领导人、国家政策争议、选举、战争立场）或针对某个普通个人的消息（隐私、八卦、人肉）。是的话 off_limits=true 并说明原因，claims 留空。
3. 先数一数内容里一共有几条可以独立查证的事实，写进 total_facts。
4. 拆成最多 {max_claims} 条说法。每条只能是「一件事」：谁、做了什么/是什么、什么时候或多少，能明确判断对错。
   - 不能把几件事合成一条（错误示例：「本周 AI 领域有多项重大进展」「文中提到的几条新闻都是真的」）。
   - 内容里的事实超过 {max_claims} 条时（比如新闻合集），只挑最值得查的：最反常识、最容易传错、或对读者影响最大的。
   - 空泛的情绪话、祝福、广告不算。
5. 每条说法标 changes：结论会不会随时间变化（价格、收费、政策、召回、停运、限行、上映/发布日期、还没定论的事件 = true；科学常识、已经发生的历史事实 = false）。
6. 每条说法给 2 个搜索词，适合在中文搜索引擎里搜：一个直接搜说法本身，一个搜原始出处或权威来源（如 "官方"、"辟谣"、"研究"、机构名、公司官网）。

只输出 JSON：
{{"title": "10字以内的标题", "readable_text": "...", "off_limits": false, "off_limits_reason": "", "total_facts": 1,
  "claims": [{{"claim": "具体说法", "changes": false, "queries": ["搜索词1", "搜索词2"]}}]}}"""

JUDGE = """你是严谨的事实核查员。今天是 {today}。只能依据下面搜索到的来源判断，绝不能用你自己的记忆补充事实。

要查证的说法：{claim}

已经搜索过的词：{queries}

来源（编号 / 网站（类型）/ 日期 / 标题 / 摘录）：
{sources}

判断规则：
- true=属实，false=不实，mixed=部分属实或要看条件，unknown=来源不足以判断。
- 每个判断必须引用来源编号，并从该来源的摘录里原样摘一句话作为 quote（必须是摘录里出现过的原文）。
- stance 是这句原文对「要查证的说法」本身的态度，不是对你结论的态度：support=原文说明这条说法是对的，refute=原文说明这条说法是错的，context=只是背景、不直接证明对错。判 true 至少要有一句 support，判 false 至少要有一句 refute，否则会被改判为「查不到」。
- 优先相信官方机构、权威媒体、专业机构的来源；自媒体、营销号的说法要打折扣。来源之间互相矛盾时写进 conflicts。
- 引用的原文必须正面说到这一件事本身（同一个主体、同一个动作、时间/数字对得上）。同一篇文章里讲别的事的句子不能当证据；说法里有几个细节（时间、数字、名称），要分别有原文对上，对不上的细节写进 explanation。
- 标了「资讯汇总」的是新闻合集、日报周报或转载，它们只是复述别人的标题。几篇汇总说同一句话只算一个弱来源；要判 true/false 并给高把握，最好找到原始出处（当事机构/公司官网、官方账号）或权威媒体的报道，找不到就降低把握，并在 next_queries 里去搜原始出处。
- 来源按日期从新到旧排列。会随时间变化的事（政策、收费、召回、停运、价格等）以最新的权威来源为准；标了「两年前的旧文」的只能当背景，不能单独证明现在的情况。
- 证据不够、来源都不权威、或者只是有人这么说但没有证实，就判 unknown。宁可说不知道，也不要猜。
- 如果再搜一轮可能查清楚（第 {round} 轮，最多 {max_rounds} 轮），need_more=true，并给 1-2 个新的搜索词（换个角度，不要重复已经搜过的）。

只输出 JSON：
{{"verdict": "true|false|mixed|unknown", "confidence": 0到100的整数,
  "explanation": "两三句话，用长辈能看懂的大白话解释结论和依据",
  "evidence": [{{"source": "S1", "quote": "原文摘句", "stance": "support|refute|context"}}],
  "conflicts": "来源之间的矛盾，没有就留空",
  "need_more": false, "next_queries": []}}"""

SUMMARY = """你在帮用户把查证结果转发回家族群。今天是 {today}。
原始传言：{text}
逐条结论：
{results}

写：
- headline：一句话说清真相（20字以内），不要以「不实」「属实」这类结论词开头（页面上已经有结论印章），比如「隔夜茶本身不会致癌」。
- family_message：一段可以直接发到家族群的话，80字以内，语气亲切尊重，不嘲讽长辈，说清楚结论，提醒看下面的来源链接。
只输出 JSON：{{"headline": "...", "family_message": "..."}}"""


def _today() -> str:
    return datetime.now(BEIJING).strftime("%Y年%m月%d日")


def _day(s: dict[str, Any]) -> str:
    """The source's date as YYYY-MM-DD, or "" when 元宝搜索 gave none we can read."""
    m = re.match(r"(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})", s.get("date") or "")
    return f"{m[1]}-{int(m[2]):02d}-{int(m[3]):02d}" if m else ""


def _norm(s: str) -> str:
    return re.sub(r"[\s　，。、,.!！?？:：;；\"'“”‘’()（）\[\]【】…—-]+", "", s or "").lower()


def _quote_found(quote: str, passage: str) -> bool:
    """True when the quote is in the page, allowing the model a few changed characters.

    Short quotes must match exactly. Longer ones pass when runs of 3+ characters, in order,
    cover at least QUOTE_MATCH of the quote — enough for 「的」 swapped for 「了」, not for a paraphrase.
    """
    q, p = _norm(quote), _norm(passage)
    if not q:
        return False
    if q in p:
        return True
    if len(q) < 12:
        return False
    blocks = SequenceMatcher(None, q, p, autojunk=False).get_matching_blocks()
    return sum(b.size for b in blocks if b.size >= 3) >= QUOTE_MATCH * len(q)


class SourcePool:
    """All pages one investigation has seen, numbered S1, S2… and deduped by URL."""

    def __init__(self) -> None:
        self.by_id: dict[str, dict[str, Any]] = {}
        self._by_url: dict[str, str] = {}

    def add(self, page: yuanbao.Page, query: str) -> str:
        if page.url in self._by_url:
            sid = self._by_url[page.url]
            src = self.by_id[sid]
            if query not in src["queries"]:
                src["queries"].append(query)
            if len(page.passage) > len(src["passage"]):
                src["passage"] = page.passage
            return sid
        sid = f"S{len(self.by_id) + 1}"
        self._by_url[page.url] = sid
        t = credibility.tier(page.url, page.site)
        self.by_id[sid] = {"id": sid, **page.to_dict(), "queries": [query],
                           "tier": t, "tier_label": credibility.TIERS[t],
                           "digest": credibility.is_digest(page.url, page.title, t)}
        return sid


async def _search(query: str, pool: SourcePool) -> tuple[list[str], str | None]:
    try:
        pages = await yuanbao.search(query)
    except Exception as exc:  # noqa: BLE001 — a failed query is reported, not fatal
        logger.warning("search %r failed: %s", query, exc)
        return [], str(exc)
    return [pool.add(p, query) for p in pages[:PAGES_PER_QUERY]], None


def _card(s: dict[str, Any]) -> dict[str, Any]:
    return {k: s[k] for k in ("id", "title", "url", "site", "date", "tier", "tier_label")}


def _format_sources(ids: list[str], pool: SourcePool) -> str:
    """Newest first, undated last, so the judge reads current news before old reposts."""
    stale = (datetime.now(BEIJING) - timedelta(days=STALE_DAYS)).strftime("%Y-%m-%d")
    lines = []
    for sid in sorted(ids, key=lambda i: _day(pool.by_id[i]) or "0", reverse=True):
        s = pool.by_id[sid]
        passage = re.sub(r"\s+", " ", s["passage"])[:PASSAGE_CHARS]
        day = _day(s)
        when = (s["date"] or "日期不详") + ("（两年前的旧文）" if day and day < stale else "")
        kind = s["tier_label"] + ("·资讯汇总" if s.get("digest") else "")
        lines.append(f"[{sid}] {s['site'] or '-'}（{kind}）/ {when} / {s['title']}\n    {passage}")
    return "\n".join(lines) or "（没有搜到任何来源）"


def _check(judged: dict[str, Any], claim: str, seen: list[str], pool: SourcePool) -> dict[str, Any]:
    """Keep only evidence that cites a source this claim actually saw, and check each quote."""
    evidence = []
    for ev in judged.get("evidence") or []:
        sid = str(ev.get("source", "")).strip().upper()
        if sid not in seen:
            continue
        quote = str(ev.get("quote", "")).strip()
        if any(e["source"] == sid and e["quote"] == quote for e in evidence):
            continue
        evidence.append({
            "source": sid,
            "quote": quote,
            "stance": ev.get("stance") if ev.get("stance") in ("support", "refute", "context") else "context",
            # True when the quote really appears in the page text 元宝搜索 returned.
            "quote_found": _quote_found(quote, pool.by_id[sid]["passage"]),
        })
    verdict = judged.get("verdict") if judged.get("verdict") in VERDICTS else "unknown"
    try:
        confidence = max(0, min(100, int(judged.get("confidence", 0))))
    except (TypeError, ValueError):
        confidence = 0
    explanation = str(judged.get("explanation", ""))
    guard = ""
    # A verified 「背景」 quote does not back a verdict: true needs a verified support, false a verified refute.
    if verdict != "unknown" and not any(e["quote_found"] and e["stance"] in BACKS[verdict] for e in evidence):
        guard = f"AI 本来想判「{VERDICTS[verdict]}」，但支撑这个结论的原文在搜到的网页里核对不上，按规则改判为「查不到」。"
        verdict, confidence = "unknown", min(confidence, 30)
        explanation = "搜到的来源不足以确认这条说法，先不下结论。"
    caution = ""
    next_queries = [str(q) for q in (judged.get("next_queries") or []) if str(q).strip()][:2]
    need_more = bool(judged.get("need_more"))
    if verdict in ("true", "false") and not _independent(verdict, evidence, pool):
        # Five roundups quoting one headline are one weak source: cap the confidence and go look for the original.
        caution = "能对上原文的只有资讯汇总或自媒体转载，没找到原始出处或权威媒体，把握打了折扣。"
        confidence = min(confidence, DIGEST_CAP)
        need_more = True
        next_queries = next_queries or [f"{claim[:40]} 官方"]
    return {
        "verdict": verdict,
        "verdict_label": VERDICTS[verdict],
        "confidence": confidence,
        "explanation": explanation,
        "conflicts": str(judged.get("conflicts", "") or ""),
        "evidence": evidence,
        "guard": guard,
        "caution": caution,
        "need_more": need_more,
        "next_queries": next_queries,
    }


def _independent(verdict: str, evidence: list[dict[str, Any]], pool: SourcePool) -> bool:
    """Whether a verified quote backing the verdict comes from somewhere other than a roundup or self-media."""
    stance = "support" if verdict == "true" else "refute"
    for e in evidence:
        s = pool.by_id[e["source"]]
        if e["quote_found"] and e["stance"] == stance and not s.get("digest") and s["tier"] != "self":
            return True
    return False


async def check_claim(index: int, claim: str, queries: list[str], pool: SourcePool, emit: Emit,
                      changes: bool = True) -> dict[str, Any]:
    """Search → judge, up to MAX_ROUNDS rounds, and return the claim's result with its evidence chain."""
    seen: list[str] = []
    asked: list[str] = []
    chain: list[dict[str, Any]] = []
    result: dict[str, Any] = {}
    todo = [q for q in queries if q.strip()][:2] or [claim]
    for rnd in range(1, MAX_ROUNDS + 1):
        todo = [q for q in todo if q not in asked]
        if not todo:
            break
        asked += todo
        await emit({"type": "searching", "claim": index, "round": rnd, "queries": todo,
                    "why": "" if rnd == 1 else chain[-1]["next_reason"]})
        searches = []
        for q, (ids, err) in zip(todo, await asyncio.gather(*(_search(q, pool) for q in todo))):
            new = [i for i in ids if i not in seen]
            seen += new
            searches.append({"query": q, "found": len(ids), "new": len(new), "sources": ids, "error": err})
            await emit({"type": "search", "claim": index, "round": rnd, "query": q,
                        "found": len(ids), "new": len(new), "error": err,
                        "sources": [_card(pool.by_id[i]) for i in new]})
        await emit({"type": "judging", "claim": index, "round": rnd, "sources": len(seen)})
        try:
            judged = await llm.generate_json(JUDGE.format(
                today=_today(), claim=claim, queries="、".join(asked), sources=_format_sources(seen, pool),
                round=rnd, max_rounds=MAX_ROUNDS,
            ))
        except Exception as exc:  # noqa: BLE001 — one claim failing must not sink the report
            logger.warning("judge failed for %r: %s", claim, exc)
            judged = {"verdict": "unknown", "explanation": "这一条在分析证据时出错了，暂时给不出结论。"}
        result = _check(judged, claim, seen, pool)
        settled = result["verdict"] != "unknown" and result["confidence"] >= 75
        more = not settled and result["need_more"] and rnd < MAX_ROUNDS and bool(result["next_queries"])
        step = {"round": rnd, "searches": searches, "sources": len(seen), "verdict": result["verdict"],
                "confidence": result["confidence"], "note": result["explanation"],
                "evidence": len(result["evidence"]),
                "verified": sum(1 for e in result["evidence"] if e["quote_found"]),
                "guard": bool(result["guard"]),
                "caution": bool(result["caution"]),
                "next_reason": ("只有资讯汇总在说，去找原始出处" if result["caution"] else "证据还不够，换个角度再搜一轮")
                if more else ""}
        chain.append(step)
        await emit({"type": "round", "claim": index, **{k: v for k, v in step.items() if k != "searches"},
                    "next_queries": result["next_queries"] if more else []})
        if not more:
            break
        todo = result["next_queries"]
    out = {
        "index": index,
        "claim": claim,
        "changes": changes,
        **{k: v for k, v in result.items() if k not in ("need_more", "next_queries")},
        "chain": chain,
        "searched": asked,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    await emit({"type": "claim", "claim": index, "result": out})
    return out


async def plan(text: str, image_b64: str | None, mime: str) -> dict[str, Any]:
    note = "用户还附了一张截图（见图片），里面的说法也要查。" if image_b64 else ""
    data = await llm.generate_json(
        PLAN.format(today=_today(), text=text.strip() or "（只有截图）", image_note=note, max_claims=MAX_CLAIMS),
        image_b64=image_b64, mime=mime, thinking="minimal",
    )
    claims = []
    for c in (data.get("claims") or [])[:MAX_CLAIMS]:
        claim = str(c.get("claim", "")).strip()
        if claim:
            claims.append({"claim": claim, "changes": c.get("changes") is True,
                           "queries": [str(q) for q in (c.get("queries") or [])][:2]})
    try:
        total = max(len(claims), int(data.get("total_facts") or 0))
    except (TypeError, ValueError):
        total = len(claims)
    return {
        "total_facts": total,
        "title": str(data.get("title") or "查证报告"),
        "readable_text": str(data.get("readable_text") or text),
        "off_limits": bool(data.get("off_limits")),
        "off_limits_reason": str(data.get("off_limits_reason") or ""),
        "claims": claims,
    }


def overall(results: list[dict[str, Any]]) -> str:
    verdicts = {r["verdict"] for r in results}
    if not verdicts or verdicts == {"unknown"}:
        return "unknown"
    if len(verdicts - {"unknown"}) == 1 and "unknown" not in verdicts:
        return verdicts.pop()
    if verdicts <= {"false", "unknown"}:
        return "false"
    if verdicts <= {"true", "unknown"}:
        return "true"
    return "mixed"


async def run(text: str, image_b64: str | None, mime: str, emit: Emit) -> dict[str, Any]:
    await emit({"type": "step", "stage": "plan", "text": "AI 正在阅读内容，拆解成可以查证的说法…"})
    p = await plan(text, image_b64, mime)
    await emit({"type": "plan", **p})
    report: dict[str, Any] = {
        "title": p["title"], "input_text": text, "readable_text": p["readable_text"],
        "had_image": bool(image_b64), "created_at": datetime.now(timezone.utc).isoformat(),
        "claims": [], "sources": [], "headline": "", "family_message": "", "verdict": "unknown",
        "off_limits": p["off_limits"], "off_limits_reason": p["off_limits_reason"],
        "total_facts": p["total_facts"],
    }
    if p["off_limits"] or not p["claims"]:
        report["headline"] = ("这类内容不在查证范围内" if p["off_limits"] else "没找到可以查证的具体说法")
        report["verdict_label"] = VERDICTS["unknown"]
        return report

    pool = SourcePool()
    await emit({"type": "step", "stage": "search", "text": f"拆出 {len(p['claims'])} 条说法，开始用元宝搜索多轮查证…"})
    results = await asyncio.gather(*(
        check_claim(i, c["claim"], c["queries"], pool, emit, c["changes"]) for i, c in enumerate(p["claims"])
    ))
    report["claims"] = list(results)
    cited = {e["source"] for r in results for e in r["evidence"]}
    report["sources"] = [{**s, "cited": s["id"] in cited} for s in pool.by_id.values()]
    report["verdict"] = overall(report["claims"])
    report["verdict_label"] = VERDICTS[report["verdict"]]

    await emit({"type": "step", "stage": "summary", "text": "所有说法查完了，正在整理证据链、写一句话结论…"})
    lines = "\n".join(f"{i + 1}. {r['claim']} → {r['verdict_label']}：{r['explanation']}" for i, r in enumerate(results))
    try:
        s = await llm.generate_json(SUMMARY.format(today=_today(), text=p["readable_text"], results=lines),
                                       thinking="minimal")
        report["headline"] = str(s.get("headline", ""))
        report["family_message"] = str(s.get("family_message", ""))
    except Exception as exc:  # noqa: BLE001 — the report stands without the summary
        logger.warning("summary failed: %r", exc)
        report["headline"] = f"{report['verdict_label']}：{p['title']}"
    return report


async def recheck(claim: str, queries: list[str]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Re-run one claim from scratch (for 盯梢). Returns the result and the sources it saw."""
    pool = SourcePool()

    async def _quiet(_: dict[str, Any]) -> None:
        return None

    result = await check_claim(0, claim, queries, pool, _quiet)
    cited = {e["source"] for e in result["evidence"]}
    return result, [{**s, "cited": s["id"] in cited} for s in pool.by_id.values()]
