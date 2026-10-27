# 静水 · 个人资讯静读器

把几十个信息源，每天收敛成 18 条带 AI 摘要的精选。

当前阶段：**P0（云端大脑）已跑通**。每天自动抓取 → 去重 → 判断多源报道 → 打分 → 精选 → 写摘要 → 出一份简报。
下一步：P1 做手机上那个 App（Flutter，适配 Z Fold 7 双栏）。

---

## 现在有什么

| 文件 | 作用 |
|---|---|
| `output/briefing.html` | 每日简报网页，手机打开即读，长这样就是最终 App 的阅读页样式 |
| `output/today.json` | 结构化的当日数据，App 直接消费这个 |
| `engine/sources.json` | **你自己的信息源清单，改这个文件就能增删来源** |
| `engine/` | 抓取、去重、打分、摘要的四个模块 |
| `run.py` | 跑一次，出一期 |

---

## 每天自动跑：三步

### 第一步：把这个文件夹变成 GitHub 仓库

1. 打开 github.com 注册/登录
2. 右上角 `+` → `New repository`，名字填 `jingshui`，选 **Private**，点 Create
3. 在电脑上打开终端，进入这个文件夹，依次执行（把 `你的用户名` 换成你的）：

```bash
git init
git add .
git commit -m "init"
git branch -M main
git remote add origin https://github.com/你的用户名/jingshui.git
git push -u origin main
```

> 如果提示要登录，GitHub 现在不收密码，要用 Personal Access Token：
> 头像 → Settings → Developer settings → Personal access tokens → Tokens(classic) → Generate new token，勾选 `repo`，生成后复制那串字符当密码用。

### 第二步：把密钥放进 Secrets（不要写进代码）

仓库页面 → `Settings` → 左侧 `Secrets and variables` → `Actions` → `New repository secret`
- Name 填 `ZP_KEY`
- Secret 填你的智谱 API Key
- 点 Add secret

### 第三步：手动触发一次，确认能跑

仓库页面 → `Actions` → 左侧 `静水 · 每日简报` → 右侧 `Run workflow` → 绿色按钮

跑完约 4 分钟。之后它会在**北京时间 06:30 / 12:30 / 20:30** 自动运行，结果自动提交回仓库的 `output/` 目录。

以后想看今天的简报，直接打开：
```
https://github.com/你的用户名/jingshui/blob/main/output/briefing.html
```
手机上用 `raw.githack.com` 或 `jsDelivr` 打开更好读（后续 App 会自动走 CDN）。

---

## 怎么加自己的信息源

编辑 `engine/sources.json`，加一条就行：

```json
{
  "id": "my-blog",
  "name": "我关注的博客",
  "kind": "rss",
  "cat": "tech",
  "weight": 60,
  "url": "https://example.com/feed.xml"
}
```

字段说明：
- `kind`：`rss`（有 RSS 地址）、`gov_api`（政府文件库接口）、`html_list`（政府网站列表页）
- `cat`：`policy` / `fin` / `tech` / `life`，只影响初始归类，AI 会再校正
- `weight`：0–100，越高越优先入选，也越容易成为"重点"
- `hours`：只取最近多少小时的内容（政策类可以设 240，因为文件稀疏）
- `cap`：这个源最多贡献几条，防止资讯站刷屏

**找 RSS 地址的土办法**：很多网站首页源码里搜 `rss`，或在网址后加 `/feed`、`/rss`、`/rss.xml` 试。

---

## 命令

```bash
# 正常跑一期
python run.py

# 不调模型，只检查抓取和去重（不花 token）
python run.py --no-ai

# 今天只要 12 条
python run.py --total 12

# 提高门槛，宁缺毋滥
python run.py --min-score 55
```

Windows 上第一次跑要先装依赖：
```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python run.py
```

---

## 几个已经踩过的坑（省得你再踩）

1. **人民网、新华网的 RSS 已停更**（最后更新 2025 年 6 月），别用。
2. **gov.cn 附件地址带 `/./`**，直接请求会 403，必须先把 `/./` 去掉。
3. **中新网必须用 https**，http 会被拒。
4. **政策文件的实质内容在 PDF 附件里**，正文页只有一段抬头。已自动解析 PDF。
5. **事件归并不能用字符串相似度**：不同标题说同一件事（相似度 0.2），同模板标题说不同事（相似度 0.8）。已改为模型判断 + "同源不归并"硬规则。
6. **配额不足时不要凑数**，否则会拿低分的健康科普填空。已设分数线。

---

## 成本

| 项 | 费用 |
|---|---|
| 智谱 GLM-4-Flash | 免费档，每期约 3 万 tokens |
| GitHub Actions | 私有仓库每月 2000 分钟，每期约 5 分钟 |
| 存储 | 仓库本身免费 |
| **合计** | **0 元/月** |
