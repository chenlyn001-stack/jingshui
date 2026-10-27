#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""输出层：生成 today.json（给 App 用）和 briefing.html（给人看）。"""
from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any

CAT_LABEL = {"policy": "时政", "fin": "财经", "tech": "科技", "life": "深度"}
CAT_CLASS = {"policy": "c-policy", "fin": "c-fin", "tech": "c-tech", "life": "c-life"}


def to_payload(brief: dict[str, Any], items: list[dict[str, Any]], stats: dict[str, Any]) -> dict[str, Any]:
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "date": stats.get("date", ""),
        "brief": brief,
        "stats": stats,
        "items": [
            {
                "id": i + 1,
                "title": it["title"],
                "url": it["url"],
                "source": it["source_name"],
                "cat": it["cat"],
                "cat_label": CAT_LABEL.get(it["cat"], "其他"),
                "published": it["published"].isoformat(timespec="minutes"),
                "score": it.get("ai_score") or it.get("rule_score"),
                "lead": it.get("lead", ""),
                "points": it.get("points", []),
                "facts": it.get("facts", []),
                "entities": it.get("entities", []),
                "doc_no": it.get("doc_no", ""),
                "org": it.get("org", ""),
                "tags": it.get("tags", []),
                "gap": it.get("gap", ""),
                "attachments": it.get("attachments", []),
                "compare": it.get("compare"),
                "members": it.get("members", []),
            }
            for i, it in enumerate(items)
        ],
    }


def _e(s: Any) -> str:
    return html.escape(str(s or ""), quote=True)


def _time_str(dt: Any) -> str:
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt)
        except ValueError:
            return dt[:10]
    if not isinstance(dt, datetime):
        return ""
    now = datetime.now(dt.tzinfo)
    delta = (now - dt).total_seconds()
    if delta < 3600:
        return f"{max(1, int(delta // 60))} 分钟前"
    if delta < 86400:
        return f"{int(delta // 3600)} 小时前"
    if delta < 86400 * 2:
        return "昨天"
    return dt.strftime("%m月%d日")


def render_item(idx: int, it: dict[str, Any]) -> str:
    cat = it["cat"]
    score = it.get("ai_score") or it.get("rule_score") or 0
    hot = score >= 78
    points = "".join(f"<li>{_e(p)}</li>" for p in it.get("points", []))
    facts = it.get("facts") or []
    facts_html = ""
    if facts:
        facts_html = (
            '<div class="facts"><div class="fh">可引用的事实</div><ul>'
            + "".join(f"<li>{_e(f)}</li>" for f in facts)
            + "</ul></div>"
        )
    meta_bits = [f'<em>{_e(it.get("source"))}</em>', f"<span>{_time_str(it['published'])}</span>"]
    if it.get("doc_no"):
        meta_bits.append(f'<span class="dno">{_e(it["doc_no"])}</span>')
    elif it.get("org"):
        meta_bits.append(f'<span>{_e(it["org"])}</span>')

    cmp_html = ""
    cmp = it.get("compare")
    if cmp and (cmp.get("diff") or cmp.get("gap")):
        cards = "".join(
            f'<div class="cmp"><div class="cn">{_e(d.get("source"))}</div>'
            f'<div class="ct">{_e(d.get("focus"))}</div></div>'
            for d in cmp.get("diff", [])
        )
        gap = f'<div class="gap">{_e(cmp.get("gap"))}</div>' if cmp.get("gap") else ""
        cmp_html = (
            f'<div class="sec">多源对比 · {it.get("source_count", 2)} 家怎么说</div>'
            f'<div class="cmps">{cards}</div>{gap}'
        )

    gap_html = ""
    if it.get("gap"):
        gap_html = f'<div class="gap-note">材料缺口：{_e(it["gap"])}</div>'
    atts = it.get("attachments") or []
    att_html = ""
    if atts:
        att_html = '<div class="atts">附件：' + " ".join(
            f'<a href="{_e(a.get("url"))}" target="_blank" rel="noopener">{_e(a.get("name"))}</a>'
            for a in atts[:4]
        ) + "</div>"

    members = it.get("members") or []
    src_list = ""
    if len(members) > 1:
        src_list = '<div class="srcs">同一事件另有：' + "、".join(
            _e(m["source"]) for m in members[1:4]
        ) + " 报道</div>"

    return f"""
    <details class="item" data-cat="{cat}" {'open' if idx <= 3 else ''}>
      <summary>
        <div class="r1">
          <span class="cat {CAT_CLASS.get(cat,'')}">{CAT_LABEL.get(cat,'其他')}</span>
          {'<span class="hot">重点</span>' if hot else ''}
          <span class="score">{int(score)}</span>
        </div>
        <h2><span class="no">{idx:02d}</span>{_e(it['title'])}</h2>
        <div class="lead">{_e(it.get('lead',''))}</div>
        <div class="meta">{' '.join(meta_bits)}</div>
        <div class="expand">展开要点</div>
      </summary>
      <div class="body">
        <div class="digest"><div class="dh">要点</div><ul>{points}</ul></div>
        {gap_html}
        {facts_html}
        {cmp_html}
        {src_list}
        {att_html}
        <a class="origin" href="{_e(it['url'])}" target="_blank" rel="noopener">阅读原文 ↗</a>
      </div>
    </details>"""


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>静水 · {date} 今日简报</title>
<style>
  :root{{
    --paper:#F6F5F1; --surface:#FFFFFF; --line:#E4E1D8; --line-soft:#EFEDE6;
    --ink:#15161A; --ink-2:#3C3F46; --muted:#7C7972; --muted-2:#A09C93;
    --navy:#1C3557; --red:#A62F26; --gold:#B08334;
    --serif:"Noto Serif SC","Source Han Serif SC","Songti SC",serif;
    --sans:"PingFang SC","Microsoft YaHei","Noto Sans SC",system-ui,sans-serif;
  }}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{
    background:var(--paper); color:var(--ink); font-family:var(--sans);
    -webkit-font-smoothing:antialiased; line-height:1.7;
    padding:0 0 80px;
  }}
  .wrap{{max-width:760px;margin:0 auto;padding:0 20px}}

  header{{padding:34px 20px 20px; max-width:760px; margin:0 auto}}
  .brand{{font-family:var(--serif); font-size:13px; letter-spacing:5px; color:var(--navy); opacity:.85}}
  .date-row{{display:flex; align-items:baseline; gap:12px; margin:18px 0 12px}}
  .date-row h1{{font-family:var(--serif); font-size:30px; font-weight:600; letter-spacing:1px}}
  .date-row .wd{{font-size:12px; color:var(--muted-2); letter-spacing:1px}}
  .headline{{
    font-family:var(--serif); font-size:19px; line-height:1.75; color:var(--ink-2);
    padding:16px 18px; background:linear-gradient(180deg,#FFFDF6,#FBF8EE);
    border:1px solid #EDE7D6; border-radius:12px; margin-bottom:14px;
  }}
  .themes{{display:flex; gap:8px; flex-wrap:wrap; margin-bottom:8px}}
  .themes span{{font-size:11px; padding:3px 10px; border:1px solid var(--line); border-radius:20px; color:var(--muted)}}
  .watch{{font-size:12.5px; color:var(--muted); line-height:1.9; padding-left:12px; border-left:2px solid var(--gold)}}

  .filters{{display:flex; gap:8px; padding:18px 20px 12px; max-width:760px; margin:0 auto; overflow-x:auto; scrollbar-width:none}}
  .filters::-webkit-scrollbar{{display:none}}
  .filters button{{
    flex:0 0 auto; padding:6px 15px; border-radius:20px; border:1px solid var(--line);
    background:var(--surface); font-size:12.5px; color:var(--ink-2); cursor:pointer;
    font-family:var(--sans); transition:.2s;
  }}
  .filters button.on{{background:var(--navy); border-color:var(--navy); color:#fff}}

  .item{{
    background:var(--surface); border:1px solid var(--line); border-radius:14px;
    margin-bottom:12px; overflow:hidden; transition:.2s;
  }}
  .item[open]{{box-shadow:0 6px 24px -12px rgba(28,35,55,.18)}}
  .item summary{{list-style:none; padding:17px 18px 15px; cursor:pointer; position:relative}}
  .item summary::-webkit-details-marker{{display:none}}
  .r1{{display:flex; align-items:center; gap:7px; margin-bottom:9px}}
  .cat{{font-size:9.5px; padding:2px 7px; border-radius:4px; letter-spacing:.5px}}
  .c-policy{{background:#EDF1F7;color:#2A4A72}}
  .c-fin{{background:#FBF1E8;color:#8A5A21}}
  .c-tech{{background:#EDF4F0;color:#2C6349}}
  .c-life{{background:#F4EFF6;color:#6A4A72}}
  .hot{{font-size:9.5px;color:var(--red)}}
  .hot::before{{content:"●"; margin-right:3px; font-size:6px; vertical-align:2px}}
  .score{{margin-left:auto; font-size:11px; color:var(--muted-2); font-variant-numeric:tabular-nums; letter-spacing:.5px}}
  .item h2{{
    font-family:var(--serif); font-size:17.5px; line-height:1.6; font-weight:600; letter-spacing:.2px;
    display:flex; gap:9px; align-items:baseline;
  }}
  .item h2 .no{{
    font-family:var(--sans); font-size:11px; color:var(--muted-2); font-weight:400;
    flex:0 0 auto; padding-top:2px; font-variant-numeric:tabular-nums;
  }}
  .lead{{font-size:13px; color:var(--muted); line-height:1.85; margin:9px 0 10px; padding-left:26px}}
  .meta{{font-size:10.5px; color:var(--muted-2); display:flex; gap:10px; flex-wrap:wrap; padding-left:26px; align-items:center}}
  .meta em{{font-style:normal; color:var(--navy); opacity:.8}}
  .dno{{color:var(--gold); border:1px solid #EDE2C9; background:#FDFAF2; padding:0 5px; border-radius:3px}}
  .expand{{position:absolute; right:18px; bottom:15px; font-size:10.5px; color:var(--muted-2)}}
  .item[open] .expand{{display:none}}

  .body{{padding:0 18px 18px; border-top:1px solid var(--line-soft); margin-top:2px}}
  .digest{{background:linear-gradient(180deg,#FCFBF7,#F8F6EF); border:1px solid #EDE9DC; border-radius:10px; padding:14px 15px; margin:15px 0 0}}
  .dh{{font-size:10px; letter-spacing:2px; color:var(--gold); margin-bottom:9px}}
  .digest ul{{list-style:none}}
  .digest li{{font-size:13.5px; line-height:1.95; color:var(--ink-2); padding-left:14px; position:relative; margin-bottom:6px}}
  .digest li::before{{content:""; position:absolute; left:2px; top:12px; width:4px; height:4px; background:var(--gold); border-radius:50%; opacity:.8}}
  .digest li:last-child{{margin-bottom:0}}
  .facts{{margin-top:12px; padding:12px 15px; border:1px dashed var(--line); border-radius:10px}}
  .fh{{font-size:10px; letter-spacing:2px; color:var(--muted-2); margin-bottom:7px}}
  .facts ul{{list-style:none}}
  .facts li{{font-size:12.5px; line-height:1.9; color:var(--ink-2); font-variant-numeric:tabular-nums}}
  .facts li::before{{content:"·"; margin-right:7px; color:var(--gold)}}
  .sec{{font-size:10px; letter-spacing:2px; color:var(--muted-2); margin:18px 0 9px; display:flex; align-items:center; gap:8px}}
  .sec::after{{content:""; flex:1; height:1px; background:var(--line-soft)}}
  .cmps{{display:grid; grid-template-columns:1fr; gap:8px}}
  @media(min-width:560px){{ .cmps{{grid-template-columns:repeat(auto-fit,minmax(160px,1fr))}} }}
  .cmp{{background:var(--paper); border:1px solid var(--line); border-radius:9px; padding:10px 12px}}
  .cn{{font-size:11.5px; color:var(--navy); font-weight:600; margin-bottom:5px}}
  .ct{{font-size:12px; line-height:1.8; color:var(--ink-2)}}
  .gap{{font-size:12px; color:var(--muted); line-height:1.85; margin-top:9px; padding-left:11px; border-left:2px solid var(--line)}}
  .srcs{{font-size:11px; color:var(--muted-2); margin-top:12px}}
  .gap-note{{font-size:11.5px; color:var(--muted-2); margin-top:10px; padding:7px 11px; background:#FBFAF6; border-left:2px solid var(--line); border-radius:0 6px 6px 0}}
  .atts{{font-size:11.5px; color:var(--muted-2); margin-top:12px}}
  .atts a{{color:var(--navy); text-decoration:none; border-bottom:1px dotted #BFC9D8; margin-right:10px; opacity:.85}}
  .origin{{display:inline-block; margin-top:14px; font-size:12px; color:var(--navy); text-decoration:none; border-bottom:1px solid #C9D2DF}}

  footer{{max-width:760px; margin:26px auto 0; padding:18px 20px 0; border-top:1px solid var(--line); font-size:11px; color:var(--muted-2); line-height:2}}
  footer b{{color:var(--ink-2); font-weight:500}}
  .empty{{text-align:center; padding:60px 20px; color:var(--muted-2); font-size:13px}}
</style>
</head>
<body>
<header>
  <div class="brand">静 水 · 今 日 简 报</div>
  <div class="date-row"><h1>{date}</h1><span class="wd">{weekday}</span></div>
  <div class="headline">{headline}</div>
  <div class="themes">{themes}</div>
  <div class="watch">{watch}</div>
</header>

<div class="filters">
  <button class="on" data-f="all">全部 {count}</button>
  {filter_buttons}
</div>

<div class="wrap">
{items_html}
</div>

<footer>
  本期抓取 <b>{raw_count}</b> 条 → 去重后 <b>{uniq_count}</b> 个事件 → 精选 <b>{count}</b> 条<br>
  来源：{source_names}<br>
  生成时间 {gen_time} · 模型 {model} · 消耗 {tokens} tokens · 用时 {elapsed}s
</footer>

<script>
document.querySelectorAll('.filters button').forEach(function(b){{
  b.onclick = function(){{
    document.querySelectorAll('.filters button').forEach(function(x){{x.classList.remove('on')}});
    b.classList.add('on');
    var f = b.dataset.f;
    document.querySelectorAll('.item').forEach(function(el){{
      el.style.display = (f === 'all' || el.dataset.cat === f) ? '' : 'none';
    }});
  }};
}});
</script>
</body>
</html>"""

WEEKDAY = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def render_html(payload: dict[str, Any], stats: dict[str, Any]) -> str:
    items = payload["items"]
    brief = payload["brief"]
    counts: dict[str, int] = {}
    for it in items:
        counts[it["cat"]] = counts.get(it["cat"], 0) + 1
    filter_buttons = "".join(
        f'<button data-f="{c}">{CAT_LABEL[c]} {counts[c]}</button>'
        for c in ("policy", "fin", "tech", "life") if counts.get(c)
    )
    d = datetime.now()
    themes = "".join(f"<span>{_e(t)}</span>" for t in brief.get("themes", []))
    return HTML_TEMPLATE.format(
        date=stats.get("date", ""),
        weekday=WEEKDAY[d.weekday()],
        headline=_e(brief.get("headline") or "今日无特别重要的变化"),
        themes=themes,
        watch=_e(brief.get("watch") or ""),
        count=len(items),
        filter_buttons=filter_buttons,
        items_html="".join(render_item(i + 1, it) for i, it in enumerate(items))
        or '<div class="empty">今天没有筛出足够重要的内容</div>',
        raw_count=stats.get("raw_count", 0),
        uniq_count=stats.get("uniq_count", 0),
        source_names=_e("、".join(stats.get("source_names", []))),
        gen_time=stats.get("gen_time", ""),
        model=stats.get("model", ""),
        tokens=stats.get("tokens", 0),
        elapsed=stats.get("elapsed", 0),
    )


def save(payload: dict[str, Any], stats: dict[str, Any], out_dir: str = "output") -> dict[str, str]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    jpath = out / "today.json"
    jpath.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    hpath = out / "briefing.html"
    hpath.write_text(render_html(payload, stats), encoding="utf-8")
    # 供 App 直接读取的扁平文件
    (out / "latest.json").write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    return {"json": str(jpath), "html": str(hpath)}
