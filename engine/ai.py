#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""智能层：调用智谱 GLM 完成打分、摘要、多源对比。

三个动作：
  score_batch()  —— 批量判断重要性（便宜，只喂标题+摘要）
  summarize()    —— 对入选条目写三条要点（喂正文，质量优先）
  compare()      —— 对多源报道说清各家侧重差异
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from typing import Any

API_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
MODEL = os.environ.get("ZP_MODEL", "glm-4-flash")

_usage = {"prompt": 0, "completion": 0, "calls": 0, "errors": 0}


def usage() -> dict[str, int]:
    return dict(_usage)


def _post(payload: dict[str, Any], timeout: int = 90, retries: int = 3) -> dict[str, Any]:
    key = os.environ.get("ZP_KEY") or os.environ.get("ZHIPU_API_KEY") or ""
    if not key:
        raise RuntimeError("缺少 ZP_KEY 环境变量")
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    last: Exception | None = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(
            API_URL,
            data=body,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            _usage["calls"] += 1
            u = data.get("usage") or {}
            _usage["prompt"] += int(u.get("prompt_tokens") or 0)
            _usage["completion"] += int(u.get("completion_tokens") or 0)
            return data
        except urllib.error.HTTPError as exc:  # 4xx/5xx
            last = exc
            detail = exc.read().decode("utf-8", "ignore")[:300]
            if exc.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(2.0 * (attempt + 1))
                continue
            raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt < retries:
                time.sleep(2.0 * (attempt + 1))
                continue
    _usage["errors"] += 1
    raise RuntimeError(str(last))


def chat(system: str, user: str, temperature: float = 0.3, max_tokens: int = 1800) -> str:
    data = _post(
        {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
    )
    return (data.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""


# --------------------------------------------------------------------------
def _loads_json_array(text: str) -> list[Any]:
    """从可能带 ``` 包裹或前后废话的回复里，抠出 JSON 数组。"""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.I | re.M)
    try:
        v = json.loads(t)
        return v if isinstance(v, list) else [v]
    except json.JSONDecodeError:
        pass
    start = t.find("[")
    end = t.rfind("]")
    if start >= 0 and end > start:
        frag = t[start : end + 1]
        frag = frag.replace("，", ",").replace("：", ":")
        try:
            return json.loads(frag)
        except json.JSONDecodeError:
            # 逐个对象挽救
            objs = []
            for m in re.finditer(r"\{[^{}]*\}", frag):
                try:
                    objs.append(json.loads(m.group(0)))
                except json.JSONDecodeError:
                    continue
            return objs
    return []


SCORE_SYSTEM = """你是一名资深的信息分析员，服务对象是政府机关从事公文写作与政策研究的干部。
你的任务是判断资讯的"必读价值"，标准非常严格：宁可漏掉，不可让用户读到垃圾。

【分类定义】必须严格按下列定义归类：
- policy：中央与地方政策文件、部委发文、重要会议与会议精神、领导人重要讲话、
  宏观治理动向；国际重大事件（战争、制裁、能源供应中断、主要经济体货币政策转向）
  因其对我国政策环境有影响，也归此类。
- fin：经济与金融数据、市场行情、企业经营与财报、产业与投资动向。
- tech：技术进展、产品发布、AI 与芯片、开源项目、技术方法论。
- life：深度报道、写作与思维方法、文化历史、值得慢读的长文。

【评分标准（0-100）】
- 85-100：中央或省级重大政策出台、重要会议精神、权威数据首次发布、影响面广的制度性变化
- 70-84：部委层面的政策/规划/试点、重要行业数据、结构性趋势的明确证据
- 55-69：有价值的行业分析、方法论、深度报道
- 40-54：一般性新闻，知道即可
- 0-39：娱乐八卦、体育赛事、促销广告、纯观点软文、标题党、旧闻翻炒、
         与企业股价涨跌无关痛痒的公司琐闻、健康科普、生活小窍门

【flag 判定】
- "ok"    正常内容
- "promo" 软文、广告、课程推广、企业通稿
- "noise" 与政策研究、公文写作无关的消遣内容
- "old"   明显是旧闻重新发布"""

SCORE_TEMPLATE = """今天是 {today}。请对下列 {n} 条资讯逐条打分。

{items}

严格输出 JSON 数组，每条一个对象，字段如下：
{{"i": 序号, "score": 0-100整数, "cat": "policy|fin|tech|life", "flag": "ok|promo|noise|old", "tags": ["不超过3个短标签"], "why": "20字以内说明为什么值得/不值得读", "event": "8字以内的事件名"}}

只输出 JSON 数组，不要任何解释。"""


def score_batch(items: list[dict[str, Any]], today: str) -> list[dict[str, Any]]:
    """批量打分。返回与 items 一一对应的结果（失败时给保守默认值）。"""
    lines = []
    for idx, it in enumerate(items, 1):
        brief = (it.get("summary") or "").replace("\n", " ")[:150]
        lines.append(f'{idx}. [{it["source_name"]}] {it["title"]}\n   摘要：{brief or "（无）"}')

    prompt = SCORE_TEMPLATE.format(today=today, n=len(items), items="\n".join(lines))
    try:
        raw = chat(SCORE_SYSTEM, prompt, temperature=0.15, max_tokens=3000)
        rows = _loads_json_array(raw)
    except Exception as exc:  # noqa: BLE001
        print(f"    [warn] 打分失败，退回规则分：{str(exc)[:90]}")
        return [{"i": i, "score": None} for i in range(1, len(items) + 1)]

    by_i = {}
    for r in rows:
        if isinstance(r, dict) and isinstance(r.get("i"), (int, str)):
            try:
                by_i[int(r["i"])] = r
            except (TypeError, ValueError):
                continue
    return [by_i.get(i, {"i": i, "score": None}) for i in range(1, len(items) + 1)]


# --------------------------------------------------------------------------
CLUSTER_SYSTEM = """你是新闻事件归并专家。任务：判断哪些标题在讲"同一件事"。

【必须满足】同一件事 = 同一个政策文件、同一场会议、同一笔交易、同一起突发事件、
同一组数据发布。允许表述不同、角度不同、标题措辞完全不同。

【绝对禁止归并的情况】
1. 不同的政策文件，即使标题格式一模一样。
   反例（这些是四个不同文件，严禁归并）：
   「关于印发《综合交通枢纽发展"十五五"规划》的通知」
   「关于印发《产业基础能力提升"十五五"规划》的通知」
   「关于印发《广告产业发展"十五五"规划》的通知」
   —— 判断依据是书名号《》里的名称、以及事件的具体对象是否相同。
2. 同一家公司/部门在同一天发布的两条不同消息。
3. 只是同属一个主题（都叫"人工智能"、都是"十五五"、都在"碳排放"），
   但讲的是不同文件、不同项目、不同产品。
4. 产品发布类：不同产品、不同厂商的发布，一律不归并。

【判断方法】先提取每条的核心对象（文件全名 / 公司 / 地区 / 事件），
只有当核心对象完全相同，才算同一件事。

【输出】宁可少归并，不可错归并。错归并把用户不需要的内容混进来，比漏归并严重得多。"""

CLUSTER_TEMPLATE = """下列 {n} 条标题，请把描述同一事件的编号归入一组。

{items}

输出 JSON：
{{"groups": [[3, 11], [7, 8, 20]]}}

只列出"包含 2 条及以上"的组，孤立的编号不必列出。
注意：来自同一个媒体的两条，几乎不可能是"多源报道"，请勿归并。只输出 JSON。"""


def cluster_events(titles: list[str], sources: list[str]) -> list[list[int]]:
    """让模型判断哪些条目是同一事件。返回 0 基索引的分组（只含 >=2 条的组）。"""
    if len(titles) < 2:
        return []
    items = "\n".join(
        f"{i + 1}. [{sources[i]}] {t}" for i, t in enumerate(titles)
    )
    try:
        raw = chat(
            CLUSTER_SYSTEM,
            CLUSTER_TEMPLATE.format(n=len(titles), items=items),
            temperature=0.1,
            max_tokens=1200,
        )
        obj = _loads_json_array(raw)
        obj = obj[0] if obj and isinstance(obj[0], dict) else {}
        groups = obj.get("groups") or []
    except Exception as exc:  # noqa: BLE001
        print(f"    [warn] 事件归并失败，改用字符相似：{str(exc)[:80]}")
        return []

    out: list[list[int]] = []
    for g in groups:
        if not isinstance(g, list):
            continue
        idxs = []
        for x in g:
            try:
                i = int(x) - 1
            except (TypeError, ValueError):
                continue
            if 0 <= i < len(titles) and i not in idxs:
                idxs.append(i)
        # 硬规则：同一来源不可能构成"多源报道"，每组每个来源只留一条
        seen_src: set[str] = set()
        uniq_idx = []
        for i in idxs:
            s = sources[i]
            if s in seen_src:
                continue
            seen_src.add(s)
            uniq_idx.append(i)
        # 必须跨至少两个来源，否则不算同一事件的多源报道
        if len(uniq_idx) >= 2:
            out.append(uniq_idx)
    return out


# --------------------------------------------------------------------------
SUM_SYSTEM = """你是一名给领导干部写《信息摘报》的资深编辑。
要求：
1. 只依据给定材料提炼，不得添加材料中没有的事实、数字和判断。
2. 语言用规范的书面语，简洁、准确，不用网络词、不用感叹句。
3. 每条要点 25-45 字，独立成句，信息密度高。
4. 严禁写"印发了某文件""要求各地贯彻落实"这类空话——
   要写这份文件到底规定了什么、管谁、什么时候生效、改变了什么。
5. 导语不得复述标题。标题说"印发了什么"，导语就要说"这份文件最实质的变化是什么"。
6. 材料中出现"【文件正文】"段落时，优先从其中提炼目标、指标、重点任务、时间节点。
7. 如果材料只是通知的抬头、实质内容在附件中，就如实说明
   "具体任务指标见附件"，并把能确认的信息（文号、发文机关、实施期限、适用对象）写清楚，
   不要编造附件里的内容。"""

SUM_TEMPLATE = """标题：{title}
来源：{source}｜分类：{cat}{extra}{attach}

材料：
{body}

请输出 JSON：
{{"lead": "一句话导语，30字以内，点出这件事的本质或最实质的变化",
  "points": ["要点1", "要点2", "要点3"],
  "facts": ["可供引用的具体数字、表述或文号，最多3条，没有则空数组"],
  "entities": ["涉及的关键主体，如部委名、文件号、地区，最多4个"],
  "gap": "材料缺失了什么（如无则空字符串）"}}

只输出 JSON。"""


def summarize(item: dict[str, Any]) -> dict[str, Any]:
    body = (item.get("body") or item.get("summary") or "")[:4000]
    if len(body) < 80:
        body = (item.get("summary") or "") + "\n（原文可访问链接查看）"
    extra = ""
    if item.get("doc_no"):
        extra = f"｜文号：{item['doc_no']}"
    if item.get("org"):
        extra += f"｜发文机关：{item['org']}"
    attach = ""
    if item.get("attachments"):
        names = "、".join(a["name"][:20] for a in item["attachments"][:3])
        attach = f"\n附件：{names}（正文实质内容可能在附件中，无法读取时请如实说明）"
    prompt = SUM_TEMPLATE.format(
        title=item["title"], source=item["source_name"],
        cat=item["cat"], extra=extra, attach=attach, body=body,
    )
    try:
        raw = chat(SUM_SYSTEM, prompt, temperature=0.25, max_tokens=900)
        obj = _loads_json_array(raw)
        obj = obj[0] if obj and isinstance(obj[0], dict) else {}
    except Exception as exc:  # noqa: BLE001
        print(f"    [warn] 摘要失败：{str(exc)[:90]}")
        obj = {}
    return {
        "lead": str(obj.get("lead") or "")[:120],
        "points": [str(p)[:120] for p in (obj.get("points") or [])][:4],
        "facts": [str(p)[:160] for p in (obj.get("facts") or [])][:3],
        "entities": [str(p)[:40] for p in (obj.get("entities") or [])][:4],
        "gap": str(obj.get("gap") or "")[:60],
    }


# --------------------------------------------------------------------------
CMP_SYSTEM = """你是一名媒体比较研究者。任务：指出同一事件下，不同来源报道的差异所在。
只做客观比较，不评判谁对谁错，不添加原文没有的信息。"""

CMP_TEMPLATE = """同一事件下，多家媒体的报道如下：

{blocks}

请输出 JSON：
{{"diff": [{{"source": "媒体名", "focus": "这家侧重什么，25字以内"}}],
  "gap": "各家报道之间最值得注意的差异或信息互补之处，40字以内"}}

只输出 JSON。"""


def compare(members: list[dict[str, Any]]) -> dict[str, Any]:
    blocks = []
    for m in members[:4]:
        blocks.append(f"【{m['source']}】{m['title']}\n{m.get('summary', '')[:260]}")
    try:
        raw = chat(CMP_SYSTEM, CMP_TEMPLATE.format(blocks="\n\n".join(blocks)),
                   temperature=0.3, max_tokens=700)
        obj = _loads_json_array(raw)
        obj = obj[0] if obj and isinstance(obj[0], dict) else {}
    except Exception as exc:  # noqa: BLE001
        print(f"    [warn] 对比失败：{str(exc)[:90]}")
        obj = {}
    return {
        "diff": [{"source": str(d.get("source", ""))[:30], "focus": str(d.get("focus", ""))[:80]}
                 for d in (obj.get("diff") or []) if isinstance(d, dict)][:4],
        "gap": str(obj.get("gap") or "")[:120],
    }


# --------------------------------------------------------------------------
BRIEF_SYSTEM = """你是一名《信息摘报》主编，为领导干部写每日导语。
语言要克制、准确、有判断力。不写"今日要闻回顾"这类废话。"""

BRIEF_TEMPLATE = """今天（{today}）共筛选出 {n} 条值得关注的资讯，标题如下：

{titles}

请输出 JSON：
{{"headline": "今日一句话总览，30字以内，概括最主要的一条主线",
  "themes": ["今天浮现的2-3个主题词"],
  "watch": "值得继续跟踪的一件事，35字以内"}}

只输出 JSON。"""


def daily_brief(titles: list[str], today: str) -> dict[str, Any]:
    try:
        raw = chat(BRIEF_SYSTEM, BRIEF_TEMPLATE.format(
            today=today, n=len(titles),
            titles="\n".join(f"- {t}" for t in titles[:20])), temperature=0.4, max_tokens=600)
        obj = _loads_json_array(raw)
        obj = obj[0] if obj and isinstance(obj[0], dict) else {}
    except Exception as exc:  # noqa: BLE001
        print(f"    [warn] 导语失败：{str(exc)[:90]}")
        obj = {}
    return {
        "headline": str(obj.get("headline") or "")[:80],
        "themes": [str(t)[:16] for t in (obj.get("themes") or [])][:3],
        "watch": str(obj.get("watch") or "")[:100],
    }
