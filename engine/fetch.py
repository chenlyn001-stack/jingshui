#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""采集层：把 sources.json 里定义的源，统一抓成标准条目。

只依赖 Python 标准库，不需要 pip install。
支持三种源类型：
  rss       —— 标准 RSS 2.0 / Atom
  gov_api   —— 中国政府网政策文件库 JSON 接口
  html_list —— 政府网站列表页（按链接规则解析）
"""
from __future__ import annotations

import gzip
import html as html_mod
import io
import json
import re
import time
import urllib.error
import urllib.request
import zlib
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from xml.etree import ElementTree as ET

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "close",
}

CST = timezone(timedelta(hours=8))


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
def _decode(raw: bytes, charset: str | None) -> str:
    for enc in filter(None, [charset, "utf-8", "gb18030", "big5"]):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "ignore")


def http_get(url: str, timeout: int = 25, retries: int = 2, referer: str | None = None) -> str:
    """带重试、自动解压、自动识别编码的 GET。部分站点需要 Referer 才放行。"""
    last_err: Exception | None = None
    headers = dict(HEADERS)
    if referer:
        headers["Referer"] = referer
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                enc = (resp.headers.get("Content-Encoding") or "").lower()
                if "gzip" in enc:
                    raw = gzip.decompress(raw)
                elif "deflate" in enc:
                    try:
                        raw = zlib.decompress(raw)
                    except zlib.error:
                        raw = zlib.decompress(raw, -zlib.MAX_WBITS)
                return _decode(raw, resp.headers.get_content_charset())
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            if attempt < retries:
                time.sleep(1.2 * (attempt + 1))
    raise last_err  # type: ignore[misc]


# --------------------------------------------------------------------------
# 文本清洗
# --------------------------------------------------------------------------
_TAG_RE = re.compile(r"(?s)<[^>]+>")
_SCRIPT_RE = re.compile(r"(?is)<(script|style|noscript|iframe)[^>]*>.*?</\1>")
_WS_RE = re.compile(r"[ \t\u3000]+")
_NOISE_RE = re.compile(
    r"(阅读全文|查看全文|点击查看|原文链接|责任编辑[:：].*$|【打印】|【关闭】|扫一扫.*$)"
)
# 微博、客户端、APP 之类的水印尾巴
_TAIL_RE = re.compile(r"(?:【|\[)?(?:编辑|来源|原标题)[:：].*$", re.S)


def clean_text(s: str, limit: int = 4000) -> str:
    if not s:
        return ""
    s = _SCRIPT_RE.sub(" ", s)
    s = _TAG_RE.sub(" ", s)
    s = html_mod.unescape(s)
    s = s.replace("\u200b", "").replace("\xa0", " ")
    s = _WS_RE.sub(" ", s)
    s = "\n".join(line.strip() for line in s.splitlines())
    s = re.sub(r"\n{2,}", "\n", s)
    s = _NOISE_RE.sub("", s)
    s = s.strip()
    return s[:limit]


def parse_time(value: str | int | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value / 1000 if value > 1e11 else value, CST)
        except (ValueError, OSError):
            return None
    v = str(value).strip()
    if not v:
        return None
    # 2026-10-27 09:30 / 2026-10-27 09:30:00 / 2026.10.26
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(v[: len(fmt) + 2].strip(), fmt).replace(tzinfo=CST)
        except ValueError:
            continue
    try:
        dt = parsedate_to_datetime(v)
        return dt.astimezone(CST) if dt.tzinfo else dt.replace(tzinfo=CST)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# RSS / Atom
# --------------------------------------------------------------------------
def _strip_ns(root: ET.Element) -> ET.Element:
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
        for k in list(el.attrib):
            if "}" in k:
                el.attrib[k.split("}", 1)[1]] = el.attrib.pop(k)
    return root


def _first_text(node: ET.Element, *names: str) -> str:
    for name in names:
        child = node.find(name)
        if child is not None:
            if child.text and child.text.strip():
                return child.text
            # Atom: <link href="..."/>
            href = child.get("href")
            if href:
                return href
    return ""


def parse_feed(xml_text: str) -> list[dict[str, Any]]:
    """解析 RSS 2.0 或 Atom，返回原始条目列表。"""
    try:
        root = _strip_ns(ET.fromstring(xml_text))
    except ET.ParseError:
        return []

    items: list[dict[str, Any]] = []
    for node in list(root.iter("item")) + list(root.iter("entry")):
        title = clean_text(_first_text(node, "title"), 300)
        if not title:
            continue

        link = ""
        for ln in node.findall("link"):
            href = ln.get("href")
            if href:
                link = href
                break
            if ln.text and ln.text.strip():
                link = ln.text.strip()
                break
        if not link:
            link = _first_text(node, "guid", "id")

        summary = clean_text(
            _first_text(node, "description", "summary", "content", "encoded"), 1500
        )
        published = parse_time(_first_text(node, "pubDate", "published", "updated", "date"))

        items.append({"title": title, "url": link.strip(), "summary": summary, "published": published})
    return items


# --------------------------------------------------------------------------
# 中国政府网政策文件库
# --------------------------------------------------------------------------
def fetch_gov_api(src: dict[str, Any]) -> list[dict[str, Any]]:
    data = json.loads(http_get(src["url"]))
    rows = (((data or {}).get("searchVO") or {}).get("listVO")) or []
    out = []
    for row in rows:
        title = clean_text(row.get("title") or "", 300)
        url = (row.get("url") or "").strip()
        if not title or not url:
            continue
        summary = clean_text(row.get("summary") or "", 1500)
        # 文号（如「国办发〔2026〕12号」）与发文机关是最有价值的元数据
        doc_no = (row.get("pcode") or "").strip()
        org = (row.get("puborg") or "").strip()
        if doc_no:
            summary = f"{summary}（{org}，{doc_no}）" if summary else f"{org}，{doc_no}"
        elif org and summary:
            summary = f"{summary}（{org}）"
        out.append(
            {
                "title": title,
                "url": url,
                "summary": summary,
                "published": parse_time(row.get("pubtimeStr") or row.get("pubtime")),
                "doc_no": doc_no,
                "org": org,
            }
        )
    return out


# --------------------------------------------------------------------------
# 政府网站列表页
# --------------------------------------------------------------------------
_ANCHOR_RE = re.compile(r'(?is)<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>')


def fetch_html_list(src: dict[str, Any]) -> list[dict[str, Any]]:
    page = http_get(src["url"])
    base = src.get("base") or src["url"]
    pattern = re.compile(src.get("link_pattern", r"\./(\d{6})/t(\d{8})_\d+\.html"))

    out, seen = [], set()
    for href, inner in _ANCHOR_RE.findall(page):
        m = pattern.search(href)
        if not m:
            continue
        title = clean_text(inner, 300)
        if len(title) < 6:
            continue
        if href.startswith("./"):
            url = base + href[2:]
        elif href.startswith("/"):
            url = re.match(r"(https?://[^/]+)", base).group(1) + href  # type: ignore[union-attr]
        elif href.startswith("http"):
            url = href
        else:
            url = base + href
        if url in seen:
            continue
        seen.add(url)
        try:
            published = datetime.strptime(m.group(2), "%Y%m%d").replace(hour=9, tzinfo=CST)
        except ValueError:
            published = None
        out.append({"title": title, "url": url, "summary": "", "published": published})
    return out


# --------------------------------------------------------------------------
# 正文抽取
# --------------------------------------------------------------------------
_P_RE = re.compile(r"(?is)<p[^>]*>(.*?)</p>")
_ATTACH_RE = re.compile(
    r'(?is)<a[^>]+href="([^"]+\.(?:pdf|docx?|wps|ofd|xlsx?))"[^>]*>(.*?)</a>'
)
_COPYRIGHT_RE = re.compile(
    r"(版权所有|Copyright|京ICP|沪ICP|粤ICP|All Rights Reserved|未经授权|转载请注明)"
)


def _body_from_html(page: str, limit: int) -> str:
    page = _SCRIPT_RE.sub(" ", page)
    paras = [clean_text(p, 1200) for p in _P_RE.findall(page)]
    paras = [p for p in paras if len(p) >= 18 and not _COPYRIGHT_RE.search(p)]
    deduped, seen = [], set()
    for p in paras:
        key = p[:40]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(p)
    body = "\n".join(deduped)
    if len(body) < 220:
        body = clean_text(page, limit)
        body = "\n".join(
            ln for ln in body.splitlines() if ln.strip() and not _COPYRIGHT_RE.search(ln)
        )
    return body[:limit]


def http_bytes(url: str, timeout: int = 60, retries: int = 1) -> bytes:
    """下载二进制文件（PDF 等）。"""
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            if attempt < retries:
                time.sleep(1.5)
    raise last_err  # type: ignore[misc]


def _norm_attach_url(u: str) -> str:
    # gov.cn 的附件地址形如 /202610/./P0202...pdf，直接请求会 403
    return re.sub(r"/\./", "/", (u or "").strip())


_CJK_SPACE_RE = re.compile(r"(?<=[\u4e00-\u9fa5])\s+(?=[\u4e00-\u9fa5])")


def pdf_text(url: str, limit: int = 7000) -> str:
    """抽取 PDF 文本。pypdf 未安装时静默返回空串。"""
    try:
        from pypdf import PdfReader  # 可选依赖
    except ImportError:
        return ""
    try:
        raw = http_bytes(_norm_attach_url(url))
    except Exception:  # noqa: BLE001
        return ""
    try:
        reader = PdfReader(io.BytesIO(raw))
        parts: list[str] = []
        total = 0
        for page in reader.pages[:15]:
            t = page.extract_text() or ""
            parts.append(t)
            total += len(t)
            if total > limit:
                break
        text = "\n".join(parts)
    except Exception:  # noqa: BLE001
        return ""
    # 中文 PDF 常在字间插入空格，去掉汉字之间的空白
    text = _CJK_SPACE_RE.sub("", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{2,}", "\n", text).strip()
    return text[:limit]


def extract_article_full(url: str, limit: int = 5000) -> dict[str, Any]:
    """抓正文，同时找出附件链接。

    很多部委文件的实质内容在 PDF/DOC 附件里，正文页只有一段抬头通知。
    抓到附件链接后交给模型"如实说明"，比让它编造要好。
    """
    try:
        page = http_get(url, timeout=20, retries=1)
    except Exception:  # noqa: BLE001
        return {"body": "", "attachments": []}

    m = re.match(r"(https?://[^/]+)", url)
    base = m.group(1) if m else ""
    attachments, seen = [], set()
    for href, name in _ATTACH_RE.findall(page)[:6]:
        if href.startswith("//"):
            href = "https:" + href
        elif href.startswith("/"):
            href = base + href
        elif not href.startswith("http"):
            href = url.rsplit("/", 1)[0] + "/" + href
        if href in seen:
            continue
        seen.add(href)
        nm = clean_text(name, 80) or href.rsplit("/", 1)[-1]
        attachments.append({"name": nm, "url": _norm_attach_url(href)})

    return {"body": _body_from_html(page, limit), "attachments": attachments}


def extract_article(url: str, limit: int = 5000) -> str:
    """兼容旧调用：只要正文。"""
    return extract_article_full(url, limit)["body"]


# --------------------------------------------------------------------------
# 统一入口
# --------------------------------------------------------------------------
def fetch_source(src: dict[str, Any], max_items: int = 40) -> list[dict[str, Any]]:
    kind = src.get("kind", "rss")
    if kind == "gov_api":
        rows = fetch_gov_api(src)
    elif kind == "html_list":
        rows = fetch_html_list(src)
    else:
        rows = parse_feed(http_get(src["url"], referer=src.get("referer")))

    out = []
    for row in rows[:max_items]:
        if not row.get("url", "").startswith("http"):
            continue
        out.append(
            {
                "title": row["title"],
                "url": row["url"],
                "summary": row.get("summary", ""),
                "published": row.get("published") or datetime.now(CST),
                "source_id": src["id"],
                "source_name": src["name"],
                "source_weight": src.get("weight", 50),
                "cat": src.get("cat", "life"),
                "doc_no": row.get("doc_no", ""),
                "org": row.get("org", ""),
            }
        )
    return out


def fetch_all(
    sources: list[dict[str, Any]], hours: int = 36, max_items: int = 40
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """并发抓取所有源。返回 (条目, 失败记录)。

    每个源可单独设置 `hours`（回溯时长）和 `max_items`（本源条数上限），
    因为政策文件一周才几篇，而资讯站一天就有几十条，不能一刀切。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    now = datetime.now(CST)
    items: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs = {
            pool.submit(fetch_source, s, s.get("max_items", max_items)): s for s in sources
        }
        for fut in as_completed(jobs):
            src = jobs[fut]
            try:
                rows = fut.result()
                cutoff = now - timedelta(hours=src.get("hours", hours))
                fresh = [r for r in rows if r["published"] >= cutoff]
                cap = src.get("cap", 25)
                fresh.sort(key=lambda r: -r["published"].timestamp())
                fresh = fresh[:cap]
                items.extend(fresh)
                print(f"  [ok] {src['name']:<14} 抓到 {len(rows):>3} 条，入选 {len(fresh):>3} 条")
            except Exception as exc:  # noqa: BLE001
                errors.append({"id": src["id"], "name": src["name"], "error": str(exc)[:120]})
                print(f"  [fail] {src['name']:<14} {str(exc)[:70]}")
    return items, errors
