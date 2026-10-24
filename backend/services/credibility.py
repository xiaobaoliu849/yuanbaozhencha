"""Rough source tiers so readers (and the judge) can tell an official notice from a repost."""
from __future__ import annotations

from urllib.parse import urlparse

TIERS = {
    "official": "官方",
    "debunk": "辟谣平台",
    "expert": "专业机构",
    "media": "权威媒体",
    "self": "自媒体",
    "other": "其他网站",
}

_DEBUNK = ("piyao.org.cn", "jiaozhen", "kepuchina.cn", "factpaper.cn", "piyao")
_EXPERT = (".edu.cn", ".ac.cn", "cas.cn", "who.int", "chinacdc.cn", "nih.gov", "cma.org.cn", "dxy.cn",
           "dxy.com", "cmt.com.cn", "nature.com", "thelancet.com", "nejm.org", "sciencedirect.com")
_MEDIA = ("people.com.cn", "xinhuanet.com", "news.cn", "cctv.com", "cctv.cn", "chinanews.com", "gmw.cn",
          "chinadaily.com.cn", "thepaper.cn", "caixin.com", "bjnews.com.cn", "cnr.cn", "youth.cn", "ce.cn",
          "cri.cn", "workercn.cn", "legaldaily.com.cn", "china.com.cn", "jiemian.com", "yicai.com",
          "21jingji.com", "stcn.com", "cls.cn", "nfnews.com", "southcn.com", "jfdaily.com", "bbc.com",
          "reuters.com", "apnews.com", "nytimes.com")
_SELF = ("mp.weixin.qq.com", "zhihu.com", "baijiahao.baidu.com", "toutiao.com", "sohu.com/a/", "douyin.com",
         "bilibili.com", "xiaohongshu.com", "weibo.com", "weibo.cn", "csdn.net", "jianshu.com", "kuaishou.com",
         "163.com/dy/", "ixigua.com", "tieba.baidu.com", "zhidao.baidu.com", "douban.com")
_OFFICIAL_WORDS = ("人民政府", "卫健委", "卫生健康委员会", "市场监管", "公安", "国务院", "部官网", "管理局", "疾控")


_DIGEST_WORDS = ("日报", "周报", "早报", "速递", "速览", "合集", "汇总", "盘点", "一周",
                 "daily", "weekly", "digest", "roundup", "round-up", "this week", "newsletter", "briefing")


def is_digest(url: str, title: str = "", tier_: str = "other") -> bool:
    """News roundups and reposts: they repeat other people's headlines, so they are not independent evidence.

    Only self-media and unknown sites qualify — 人民日报 or chinadaily are newspapers, not roundups.
    """
    if tier_ not in ("self", "other"):
        return False
    text = f"{title} {urlparse(url).netloc}".lower()
    return any(w in text for w in _DIGEST_WORDS)


def tier(url: str, site: str = "") -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    full = host + parsed.path.lower()
    if any(d in full for d in _DEBUNK) or "辟谣" in site:
        return "debunk"
    if host.endswith(".gov.cn") or host.endswith(".gov") or ".gov." in host or any(w in site for w in _OFFICIAL_WORDS):
        return "official"
    if any(d in full for d in _SELF):
        return "self"
    if any(host.endswith(d.lstrip(".")) or d in host for d in _EXPERT):
        return "expert"
    if any(host == d or host.endswith("." + d) for d in _MEDIA):
        return "media"
    return "other"
