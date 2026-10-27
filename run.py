#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""静水 · 每日简报生成器（P0）

用法：
    set ZP_KEY=xxxx            (Windows)
    export ZP_KEY=xxxx         (mac/Linux)
    python run.py

流程：抓取 → 硬去重 → 粗筛 → AI 打分 → 取高分者做事件归并 → 配额挑选
      → 抓正文/附件 → AI 摘要 → 输出

为什么"先打分再归并"：归并难免出错，若先归并，一次错并就会连带丢掉好内容；
先打分再归并，最坏情况只是少了一条多源对比，不会让今天的清单变薄。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

# 云端（GitHub Actions）容器默认是 UTC，会让 06:30 那次被标成"前一天"。
# 这里强制切到北京时间，本地跑也不受影响。
os.environ.setdefault("TZ", "Asia/Shanghai")
if hasattr(time, "tzset"):
    time.tzset()

sys.path.insert(0, str(Path(__file__).parent))

from engine import ai, build, fetch, nlp  # noqa: E402

ROOT = Path(__file__).parent
DAILY_TOTAL = 18
SCORE_POOL = 46    # 送去 AI 打分的条数
CLUSTER_POOL = 34  # 送去 AI 归并的条数（只对高分者做，控制成本）
MIN_SCORE = 46.0   # 入选分数线，低于此分不凑数


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--total", type=int, default=DAILY_TOTAL)
    ap.add_argument("--pool", type=int, default=SCORE_POOL)
    ap.add_argument("--cluster-pool", type=int, default=CLUSTER_POOL)
    ap.add_argument("--hours", type=int, default=36)
    ap.add_argument("--min-score", type=float, default=MIN_SCORE)
    ap.add_argument("--no-ai", action="store_true", help="不调模型，只测抓取与规则")
    ap.add_argument("--sources", default=str(ROOT / "engine" / "sources.json"))
    ap.add_argument("--out", default=str(ROOT / "output"))
    args = ap.parse_args()

    t0 = time.time()
    today = datetime.now().strftime("%Y年%m月%d日")
    print(f"\n静水 · {today}\n" + "=" * 62)

    if not args.no_ai and not (os.environ.get("ZP_KEY") or os.environ.get("ZHIPU_API_KEY")):
        print("缺少 ZP_KEY 环境变量。先设置：set ZP_KEY=你的密钥")
        return 2

    # ---------- 1. 抓取 ----------
    sources = json.loads(Path(args.sources).read_text(encoding="utf-8"))
    print(f"\n[1/6] 抓取 {len(sources)} 个来源")
    raw, errors = fetch.fetch_all(sources, hours=args.hours)
    print(f"      合计 {len(raw)} 条")
    if not raw:
        print("没有抓到任何内容，检查网络或源配置。")
        return 1

    # ---------- 2. 硬去重 + 粗筛 ----------
    print("\n[2/6] 去重与粗筛")
    uniq = nlp.dedupe(raw)
    for it in uniq:
        it["source_count"] = 1
        it["rule_score"] = nlp.rule_score(it)
    uniq.sort(key=lambda x: -x["rule_score"])
    pool_items = uniq[: args.pool]
    print(f"      {len(raw)} 条 → 去重后 {len(uniq)} 条 → 送审 {len(pool_items)} 条")

    # ---------- 3. AI 打分 ----------
    print(f"\n[3/6] AI 评估 {len(pool_items)} 条")
    if args.no_ai:
        for c in pool_items:
            c["ai_score"] = c["rule_score"]
            c["flag"] = "ok"
    else:
        CHUNK = 16
        for start in range(0, len(pool_items), CHUNK):
            batch = pool_items[start : start + CHUNK]
            rows = ai.score_batch(batch, today)
            for c, r in zip(batch, rows):
                c["ai_score"] = (
                    round(float(r["score"]) * 0.72 + c["rule_score"] * 0.28, 1)
                    if r.get("score") is not None
                    else c["rule_score"]
                )
                c["flag"] = r.get("flag", "ok")
                if r.get("cat") in build.CAT_LABEL:
                    c["cat"] = r["cat"]
                c["tags"] = [str(t)[:14] for t in (r.get("tags") or [])][:3]
                c["why"] = str(r.get("why") or "")[:40]
            print(f"      已评估 {min(start + CHUNK, len(pool_items))}/{len(pool_items)}")

    clean = [c for c in pool_items if c.get("flag", "ok") == "ok"]
    if len(clean) < len(pool_items):
        print(f"      剔除软文/噪音/旧闻 {len(pool_items) - len(clean)} 条")
    clean.sort(key=lambda c: -(c.get("ai_score") or 0))

    # ---------- 4. 事件归并 ----------
    print("\n[4/6] 判断哪些报道是同一件事")
    top = clean[: args.cluster_pool]
    if args.no_ai:
        groups = [g for g in nlp.greedy_cluster(top) if len(g) >= 2]
    else:
        groups = ai.cluster_events(
            [i["title"] for i in top], [i["source_name"] for i in top]
        )
    if groups:
        merged = sum(len(g) - 1 for g in groups)
        print(f"      {len(groups)} 个多源事件，合并 {merged} 条重复报道")
    else:
        print("      今天没有明显的多源报道")
    clusters = nlp.build_clusters(top, groups)
    print(f"      → {len(clusters)} 个事件")

    # ---------- 5. 配额挑选 + 抓正文 ----------
    picked = nlp.pick(clusters, total=args.total, min_score=args.min_score)
    dist: dict[str, int] = {}
    for c in picked:
        k = build.CAT_LABEL.get(c["cat"], "其他")
        dist[k] = dist.get(k, 0) + 1
    print(f"\n[5/6] 选定 {len(picked)} 条（分数线 {args.min_score}）："
          + " / ".join(f"{k}{v}" for k, v in dist.items()))

    def grab(c):
        got = fetch.extract_article_full(c["url"])
        body = got["body"]
        atts = got["attachments"]
        c["from_pdf"] = False
        # 政府文件的正文页往往只有抬头和套话，实质内容在附件 PDF 里。
        # 所以不能只看"正文是否过短"，而要比一比：附件比正文长，就以附件为准。
        if atts:
            for a in atts[:2]:
                if not a["url"].lower().endswith(".pdf"):
                    continue
                t = fetch.pdf_text(a["url"])
                if len(t) > 300 and len(t) > len(body) * 1.15:
                    body = f"{body[:600]}\n\n【文件正文】\n{t}"[:11000]
                    c["from_pdf"] = True
                    break
        c["body"] = body
        c["attachments"] = atts
        return c

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(grab, picked))

    thin = sum(1 for c in picked if len(c["body"]) < 400)
    if thin:
        print(f"      {thin} 条正文过短（实质内容在附件中），摘要会如实标注")

    for i, c in enumerate(picked, 1):
        if args.no_ai:
            c.update({"lead": c.get("summary", "")[:60],
                      "points": [c.get("summary", "")[:80]], "facts": [],
                      "entities": [], "gap": ""})
        else:
            c.update(ai.summarize(c))
            if c["source_count"] >= 2:
                c["compare"] = ai.compare(c["members"])
        print(f"      {i:02d}/{len(picked)}  {c['title'][:32]}")

    # ---------- 6. 导语 + 输出 ----------
    print("\n[6/6] 生成今日导语与页面")
    if args.no_ai:
        brief = {"headline": "（未启用模型，仅测试抓取）", "themes": [], "watch": ""}
    else:
        brief = ai.daily_brief([c["title"] for c in picked], today)

    u = ai.usage()
    tokens = u["prompt"] + u["completion"]
    failed_ids = {e["id"] for e in errors}
    stats = {
        "date": today,
        "raw_count": len(raw),
        "uniq_count": len(uniq),
        "source_names": [s["name"] for s in sources if s["id"] not in failed_ids],
        "gen_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "model": os.environ.get("ZP_MODEL", ai.MODEL),
        "tokens": tokens,
        "elapsed": round(time.time() - t0, 1),
    }
    payload = build.to_payload(brief, picked, stats)
    if errors:
        payload["stats"]["failed_sources"] = errors
    paths = build.save(payload, stats, args.out)

    print("\n" + "=" * 62)
    print(f"完成，用时 {stats['elapsed']}s，消耗 {tokens} tokens")
    print(f"  人看：{paths['html']}")
    print(f"  App ：{paths['json']}")
    if errors:
        print(f"  失败源 {len(errors)} 个：" + "、".join(e["name"] for e in errors))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
