#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""处理层：去重、事件聚类、规则打分、配额挑选。

关键设计（血泪换来的）：
1. 字符串相似度只用来"硬去重"（几乎完全一样的标题）。
2. 事件聚类交给 AI 判断，因为「胡塞称打击沙特炼油厂」与「胡塞首次袭击沙特最大
   石油出口终端」是同一件事，但标题相似度只有 0.2；而字符算法一旦用并查集做
   传递合并（A~B, B~C 则 A~C），就会滚雪球把无关内容并进来。
3. 字符串兜底聚类用"贪心 + 只与簇代表比较"，刻意不做传递，避免雪球效应。
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable

_STOP_PREFIX = re.compile(
    r"^(?:【[^】]{0,12}】|\[[^\]]{0,12}\]|独家|重磅|突发|最新|快讯|图解|视频|直播|"
    r"评论|社评|观察|深度|专访|组图|H5|海报|热议)[:：\s]*"
)
_PUNCT = re.compile(
    r"[\s\u3000\-—－_·、，。；：！？,.;:!?\"'“”‘’（）()《》〈〉\[\]【】<>/\\|~`@#$%^&*+=…]+"
)


def normalize_title(title: str) -> str:
    t = unicodedata.normalize("NFKC", title or "")
    t = _STOP_PREFIX.sub("", t)
    return _PUNCT.sub("", t).lower()


def shingles(text: str, n: int = 2) -> set[str]:
    if len(text) <= n:
        return {text} if text else set()
    return {text[i : i + n] for i in range(len(text) - n + 1)}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / (len(a) + len(b) - inter)


def hash64(s: str) -> int:
    h = 0xCBF29CE484222325
    for ch in s:
        h ^= ord(ch)
        h = (h * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


def simhash(text: str) -> int:
    if not text:
        return 0
    vec = [0] * 64
    for sh in shingles(text):
        h = hash64(sh)
        for i in range(64):
            vec[i] += 1 if (h >> i) & 1 else -1
    out = 0
    for i in range(64):
        if vec[i] > 0:
            out |= 1 << i
    return out


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def normalize_url(url: str) -> str:
    u = (url or "").split("#")[0]
    u = re.sub(r"^(https?)://(www\.)?", "", u)
    u = re.sub(r"[?&](utm_[^&]*|from=[^&]*|spm=[^&]*)", "", u)
    return u.rstrip("/")


# --------------------------------------------------------------------------
# 1. 硬去重（同一篇文章被转载多次时只留一条）
# --------------------------------------------------------------------------
def dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for it in items:
        it["_ntitle"] = normalize_title(it["title"])
        it["_sh"] = shingles(it["_ntitle"])
        it["_sim"] = simhash(it["_ntitle"])
        it["_nurl"] = normalize_url(it["url"])

    kept: list[dict[str, Any]] = []
    for it in items:
        dup_idx = None
        for j, k in enumerate(kept):
            if it["_nurl"] == k["_nurl"] or hamming(it["_sim"], k["_sim"]) <= 2:
                dup_idx = j
                break
        if dup_idx is None:
            kept.append(it)
        elif len(it.get("summary", "")) > len(kept[dup_idx].get("summary", "")):
            kept[dup_idx] = it
    return kept


# --------------------------------------------------------------------------
# 2. 事件聚类
# --------------------------------------------------------------------------
def greedy_cluster(items: list[dict[str, Any]]) -> list[list[int]]:
    """字符串兜底聚类：贪心，只与簇代表比较，不做传递合并。"""
    order = sorted(range(len(items)), key=lambda i: (-items[i]["source_weight"], -len(items[i]["title"])))
    clusters: list[list[int]] = []
    reps: list[int] = []
    for i in order:
        it = items[i]
        placed = False
        for ci, rep in enumerate(reps):
            r = items[rep]
            la, lb = len(it["_ntitle"]), len(r["_ntitle"])
            if min(la, lb) / max(la, lb, 1) < 0.55:
                continue
            if jaccard(it["_sh"], r["_sh"]) >= 0.62 or hamming(it["_sim"], r["_sim"]) <= 10:
                clusters[ci].append(i)
                placed = True
                break
        if not placed:
            clusters.append([i])
            reps.append(i)
    return clusters


def build_clusters(
    items: list[dict[str, Any]], ai_groups: list[list[int]] | None = None
) -> list[dict[str, Any]]:
    """把条目组装成事件组。

    ai_groups 为 AI 给出的同事件编号分组（0 基）；未出现在任何组里的条目自成一簇。
    """
    used: dict[int, list[int]] = {}
    for gi, g in enumerate(ai_groups or []):
        for i in g:
            used[i] = g

    seen: set[int] = set()
    groups: list[list[int]] = []
    for i in range(len(items)):
        if i in seen:
            continue
        g = used.get(i)
        if g:
            groups.append([x for x in g if 0 <= x < len(items)])
            seen.update(g)
        else:
            groups.append([i])
            seen.add(i)

    clusters = []
    for members_idx in groups:
        members = [items[i] for i in members_idx]
        members.sort(key=lambda x: (-x["source_weight"], -(x["published"] or 0).timestamp()))
        best = max(
            members,
            key=lambda x: len(x.get("summary", "")) + 200 * (x["source_weight"] >= 90),
        )
        cluster = dict(best)
        cluster["members"] = [
            {
                "source": m["source_name"],
                "title": m["title"],
                "url": m["url"],
                "summary": m.get("summary", "")[:300],
            }
            for m in members
        ]
        cluster["source_count"] = len({m["source_name"] for m in members})
        cluster["cat"] = members[0]["cat"]
        # 事件分取组内最高分：一篇被多家转载的稿子不该因为主条目分数低而被埋没
        cluster["ai_score"] = max(
            (m.get("ai_score") or m.get("rule_score") or 0) for m in members
        )
        cluster["tags"] = best.get("tags", [])
        cluster["rule_score"] = rule_score(cluster)
        clusters.append(cluster)

    clusters.sort(key=lambda c: -c["rule_score"])
    return clusters


# --------------------------------------------------------------------------
# 3. 规则打分（只做粗筛，权重保守）
# --------------------------------------------------------------------------
POLICY_WORDS = (
    "印发", "通知", "意见", "办法", "条例", "规定", "决定", "批复", "公告",
    "会议", "部署", "规划", "纲要", "方案", "试点", "改革", "出台",
)
DATA_WORDS = ("同比", "环比", "增长", "下降", "指数", "统计", "数据", "规模", "总额", "个百分点")
TREND_WORDS = ("首次", "首个", "突破", "加快", "深化", "构建", "转型", "新质生产力")
NOISE_WORDS = (
    "明星", "恋情", "综艺", "球赛", "比分", "彩票", "优惠券", "秒杀", "开奖",
    "星座", "运势", "游戏攻略", "探店", "招聘", "痴呆", "养生", "减肥",
)


def rule_score(c: dict[str, Any]) -> float:
    text = c["title"] + " " + (c.get("summary") or "")[:200]
    score = c["source_weight"] * 0.30

    hits = sum(1 for w in POLICY_WORDS if w in text)
    score += min(hits, 4) * 5.5
    score += min(sum(1 for w in DATA_WORDS if w in text), 3) * 3.0
    score += min(sum(1 for w in TREND_WORDS if w in text), 2) * 3.0
    score += min(c.get("source_count", 1) - 1, 3) * 9.0
    if c.get("doc_no"):
        score += 16.0

    tl = len(c["title"])
    if tl < 8:
        score -= 12
    elif tl > 60:
        score -= 5

    score -= sum(3.5 for w in NOISE_WORDS if w in text)
    if len(c.get("summary") or "") < 30:
        score -= 6
    return round(max(0.0, min(100.0, score)), 1)


# --------------------------------------------------------------------------
# 4. 配额挑选（不足不凑数）
# --------------------------------------------------------------------------
def pick(
    clusters: list[dict[str, Any]],
    quotas: dict[str, int] | None = None,
    total: int = 18,
    min_score: float = 46.0,
) -> list[dict[str, Any]]:
    """按分类配额挑选。低于 min_score 的一律不选，宁可今天只有 12 条。"""
    quotas = quotas or {"policy": 7, "fin": 4, "tech": 5, "life": 2}
    ranked = sorted(clusters, key=lambda c: -(c.get("ai_score") or c["rule_score"]))
    picked: list[dict[str, Any]] = []
    used: set[int] = set()

    for cat, quota in quotas.items():
        taken = 0
        for c in ranked:
            if taken >= quota:
                break
            if id(c) in used or c["cat"] != cat:
                continue
            if (c.get("ai_score") or c["rule_score"]) < min_score:
                continue
            picked.append(c)
            used.add(id(c))
            taken += 1

    for c in ranked:  # 未满额时跨类补足，但同样守分数线
        if len(picked) >= total:
            break
        if id(c) not in used and (c.get("ai_score") or c["rule_score"]) >= min_score:
            picked.append(c)
            used.add(id(c))

    picked.sort(key=lambda c: -(c.get("ai_score") or c["rule_score"]))
    return picked[:total]


def groups_for_compare(picked: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [c for c in picked if c.get("source_count", 1) >= 2]
