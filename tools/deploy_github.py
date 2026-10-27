"""把「静水」部署到 GitHub，并开通网页访问。

设计前提：本机访问 github.com 会超时，但 api.github.com 通。
所以全程走 REST API 上传（Git Data API，一次性生成一个 commit），
不依赖 git push。

用法：
    set GH_TOKEN=xxx          （Windows cmd）
    export GH_TOKEN=xxx       （bash）
    python tools/deploy_github.py --repo jingshui --public
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.github.com"
ROOT = Path(__file__).resolve().parent.parent

# 不进仓库的东西（和 .gitignore 保持一致，这里再兜一层，防止误传密钥）
EXCLUDE_DIRS = {".git", ".venv", "venv", "build", "prototype", "__pycache__", ".workbuddy"}
EXCLUDE_FILES = {"静水-产品方案-v0.1.md", ".env"}
EXCLUDE_SUFFIX = {".pyc", ".pyo", ".tmp", ".log"}


def log(msg: str) -> None:
    print(msg, flush=True)


def api(
    path: str,
    token: str,
    method: str = "GET",
    data: dict | None = None,
    *,
    ok: tuple[int, ...] = (200, 201),
):
    """调 GitHub REST API。返回 (状态码, 解析后的结果或原始文本)。"""
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(
        API + path,
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "jingshui-deploy",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "ignore")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = raw
        return exc.code, parsed


def collect_files() -> list[tuple[str, bytes]]:
    """收集要上传的文件，返回 [(仓库内相对路径, 内容)]。

    注意：本机文件是 CRLF 换行，直接上传会让 Linux runner 上的 shell 脚本报错，
    所以文本文件一律转成 LF。
    """
    out: list[tuple[str, bytes]] = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        parts = set(rel.parts[:-1])
        if parts & EXCLUDE_DIRS:
            continue
        if rel.name in EXCLUDE_FILES or path.suffix in EXCLUDE_SUFFIX:
            continue
        content = path.read_bytes()
        if b"\r\n" in content and b"\x00" not in content:
            content = content.replace(b"\r\n", b"\n")
        out.append((rel.as_posix(), content))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--token", default=os.environ.get("GH_TOKEN", ""))
    ap.add_argument("--repo", default="jingshui")
    ap.add_argument("--public", action="store_true", help="建公开仓库（免费版只有公开仓库能开网页）")
    ap.add_argument("--key", default=os.environ.get("ZP_KEY", ""), help="智谱 API Key，写进 Actions Secrets")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    files = collect_files()
    log(f"待上传 {len(files)} 个文件，共 {sum(len(c) for _, c in files) // 1024} KB")
    for rel, content in files:
        log(f"   {len(content):>7}  {rel}")

    if args.dry_run:
        return 0

    token = args.token.strip()
    if not token:
        log("\n缺少 token。请设置 GH_TOKEN 环境变量或传 --token。")
        return 2

    # ---------- 1. 确认身份 ----------
    log("\n[1/6] 验证 token")
    code, me = api("/user", token)
    if code != 200:
        log(f"  ✗ token 无效（HTTP {code}）：{me}")
        return 1
    owner = me["login"]
    log(f"  ✓ 登录为 {owner}")

    # ---------- 2. 建仓库 ----------
    log(f"\n[2/6] 创建仓库 {owner}/{args.repo}（{'公开' if args.public else '私有'}）")
    code, repo = api(
        "/user/repos",
        token,
        method="POST",
        data={
            "name": args.repo,
            "description": "静水 · 个人资讯静读器：多源抓取 →  AI 精选 → 每日简报",
            "private": not args.public,
            "has_issues": False,
            "has_wiki": False,
            "auto_init": False,
        },
    )
    if code == 201:
        log("  ✓ 已创建")
    elif code == 422:
        log("  · 仓库已存在，改为更新内容")
        code2, repo = api(f"/repos/{owner}/{args.repo}", token)
        if code2 != 200:
            log(f"  ✗ 读取仓库失败：{repo}")
            return 1
    else:
        log(f"  ✗ 创建失败（HTTP {code}）：{repo}")
        return 1

    branch = repo.get("default_branch") or "main"
    log(f"  · 默认分支 {branch}")

    # ---------- 3. 一次性提交所有文件 ----------
    log(f"\n[3/6] 上传文件（{len(files)} 个）")

    # Git Data API 在完全空的仓库上会返回 409「Git Repository is empty」，
    # 所以先用 Contents API 落下第一个文件，把分支建出来。
    code, ref = api(f"/repos/{owner}/{args.repo}/git/ref/heads/{branch}", token, ok=(200, 404, 409))
    if code != 200:
        log("  · 空仓库，先建初始提交")
        code, seed = api(
            f"/repos/{owner}/{args.repo}/contents/.bootstrap",
            token,
            method="PUT",
            data={"message": "init", "content": base64.b64encode(b"jingshui\n").decode()},
        )
        if code not in (200, 201):
            log(f"  ✗ 初始化失败：{seed}")
            return 1
        code, ref = api(f"/repos/{owner}/{args.repo}/git/ref/heads/{branch}", token, ok=(200, 404, 409))

    tree = []
    for rel, content in files:
        code, blob = api(
            f"/repos/{owner}/{args.repo}/git/blobs",
            token,
            method="POST",
            data={"content": base64.b64encode(content).decode(), "encoding": "base64"},
        )
        if code != 201:
            log(f"  ✗ {rel} 上传失败：{blob}")
            return 1
        tree.append({"path": rel, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        log(f"  · {rel}")

    code, new_tree = api(
        f"/repos/{owner}/{args.repo}/git/trees",
        token,
        method="POST",
        data={"tree": tree},
    )
    if code != 201:
        log(f"  ✗ 目录树创建失败：{new_tree}")
        return 1

    # 已有内容时接在最新提交后面，否则作为首个提交
    parents: list[str] = []
    code, ref = api(f"/repos/{owner}/{args.repo}/git/ref/heads/{branch}", token, ok=(200, 404, 409))
    if code == 200 and ref:
        parents = [ref["object"]["sha"]]

    code, commit = api(
        f"/repos/{owner}/{args.repo}/git/commits",
        token,
        method="POST",
        data={
            "message": "init: 静水云端大脑（抓取 / 归并 / 打分 / 摘要 / 简报网页）",
            "tree": new_tree["sha"],
            "parents": parents,
        },
    )
    if code != 201:
        log(f"  ✗ 提交失败：{commit}")
        return 1

    if not parents:
        code, _ = api(
            f"/repos/{owner}/{args.repo}/git/refs",
            token,
            method="POST",
            data={"ref": f"refs/heads/{branch}", "sha": commit["sha"]},
        )
    else:
        code, _ = api(
            f"/repos/{owner}/{args.repo}/git/refs/heads/{branch}",
            token,
            method="PATCH",
            data={"sha": commit["sha"], "force": True},
        )
    if code not in (200, 201):
        log(f"  ✗ 分支写入失败（HTTP {code}）")
        return 1
    log(f"  ✓ 提交完成 {commit['sha'][:8]}")

    # ---------- 4. 写密钥 ----------
    log("\n[4/6] 写入 API 密钥到 Actions Secrets")
    secret_ok = False
    if not args.key:
        log("  · 未提供 --key，跳过（稍后也可在网页里手动加）")
    else:
        code, pk = api(f"/repos/{owner}/{args.repo}/actions/secrets/public-key", token)
        if code != 200:
            log(f"  ✗ 取公钥失败：{pk}")
        else:
            try:
                from nacl import encoding, public  # type: ignore

                pub = public.PublicKey(pk["key"].encode(), encoding.Base64Encoder())
                sealed = public.SealedBox(pub).encrypt(args.key.encode())
                enc = base64.b64encode(sealed).decode()
            except ImportError:
                log("  ! 缺 pynacl，无法自动加密。执行：.venv\\Scripts\\pip install pynacl")
                enc = ""
            if enc:
                code, res = api(
                    f"/repos/{owner}/{args.repo}/actions/secrets/ZP_KEY",
                    token,
                    method="PUT",
                    data={"encrypted_value": enc, "key_id": pk["key_id"]},
                )
                if code in (201, 204):
                    log("  ✓ ZP_KEY 已写入")
                    secret_ok = True
                else:
                    log(f"  ✗ 写入失败（HTTP {code}）：{res}")

    # ---------- 5. 开网页 ----------
    log("\n[5/6] 开启 GitHub Pages")
    payload = {"source": {"branch": branch, "path": "/"}}
    code, res = api(f"/repos/{owner}/{args.repo}/pages", token, method="POST", data=payload)
    if code == 201:
        log("  ✓ 已开启")
    elif code == 409:
        code2, res2 = api(
            f"/repos/{owner}/{args.repo}/pages", token, method="PUT", data=payload
        )
        log("  ✓ 已存在，已更新配置" if code2 in (200, 204) else f"  ✗ 更新失败：{res2}")
    else:
        log(f"  ! 开启失败（HTTP {code}）：{res}")
        log("    公开仓库才支持免费 Pages；若为私有仓库需 Pro 版。")

    # ---------- 6. 触发首次运行 ----------
    log("\n[6/6] 触发首次运行")
    if not secret_ok:
        log("  · 跳过（没有密钥，跑了也会失败）。加好 ZP_KEY 后在网页点 Run workflow 即可。")
    else:
        for attempt in range(4):
            code, res = api(
                f"/repos/{owner}/{args.repo}/actions/workflows/daily.yml/dispatches",
                token,
                method="POST",
                data={"ref": branch},
            )
            if code in (204, 200):
                log("  ✓ 已触发，约 5 分钟出结果")
                break
            log(f"  · 第 {attempt + 1} 次触发失败（HTTP {code}）：{res}")
            time.sleep(5)

    site = f"https://{owner}.github.io/{args.repo}/"
    log("\n" + "=" * 56)
    log(f"仓库   https://github.com/{owner}/{args.repo}")
    log(f"网页   {site}")
    log(f"数据   {site}output/today.json")
    log(f"运行记录 https://github.com/{owner}/{args.repo}/actions")
    log("=" * 56)
    return 0


if __name__ == "__main__":
    sys.exit(main())
