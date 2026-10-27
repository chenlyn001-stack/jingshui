import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:url_launcher/url_launcher.dart';

/// 简报数据地址（GitHub Pages，国内可直连）
const String kDataUrl =
    'https://chenlyn001-stack.github.io/jingshui/output/today.json';

void main() => runApp(const JingshuiApp());

class JingshuiApp extends StatelessWidget {
  const JingshuiApp({super.key});

  @override
  Widget build(BuildContext context) {
    const seed = Color(0xFF8C6E4A); // 纸墨棕
    return MaterialApp(
      title: '静水',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: seed),
        scaffoldBackgroundColor: const Color(0xFFFAF7F0),
      ),
      darkTheme: ThemeData(
        brightness: Brightness.dark,
        colorScheme:
            ColorScheme.fromSeed(seedColor: seed, brightness: Brightness.dark),
        scaffoldBackgroundColor: const Color(0xFF15171C),
      ),
      themeMode: ThemeMode.system,
      home: const HomePage(),
    );
  }
}

// ---------------------------------------------------------------------------
// 数据模型（字段全部防御式解析，线上 JSON 少一个字段也不崩）
// ---------------------------------------------------------------------------

List<String> _strs(dynamic v) =>
    ((v as List?) ?? const []).map((e) => e.toString()).toList();

class Briefing {
  Briefing({
    required this.date,
    required this.headline,
    required this.themes,
    required this.watch,
    required this.generatedAt,
    required this.rawCount,
    required this.uniqCount,
    required this.sourceCount,
    required this.items,
  });

  final String date, headline, generatedAt;
  final List<String> themes, watch;
  final int rawCount, uniqCount, sourceCount;
  final List<NewsItem> items;

  static Briefing fromMap(Map<String, dynamic> m) {
    final b = (m['brief'] as Map?) ?? const {};
    final s = (m['stats'] as Map?) ?? const {};
    return Briefing(
      date: (m['date'] ?? '').toString(),
      headline: (b['headline'] ?? '').toString(),
      themes: _strs(b['themes']),
      watch: _strs(b['watch']),
      generatedAt: (m['generated_at'] ?? '').toString(),
      rawCount: (s['raw_count'] as num?)?.toInt() ?? 0,
      uniqCount: (s['uniq_count'] as num?)?.toInt() ?? 0,
      sourceCount: ((s['source_names'] as List?) ?? const []).length,
      items: ((m['items'] as List?) ?? const [])
          .map((e) => NewsItem.fromMap(Map<String, dynamic>.from(e as Map)))
          .toList(),
    );
  }

  String get genTimeText {
    final t = DateTime.tryParse(generatedAt)?.toLocal();
    if (t == null) return '';
    final h = t.hour.toString().padLeft(2, '0');
    final mi = t.minute.toString().padLeft(2, '0');
    return '${t.month}月${t.day}日 $h:$mi';
  }
}

class NewsItem {
  NewsItem({
    required this.id,
    required this.title,
    required this.lead,
    required this.source,
    required this.catLabel,
    required this.score,
    required this.url,
    required this.points,
    required this.facts,
    required this.entities,
    required this.tags,
    required this.gap,
    required this.docNo,
    required this.org,
    required this.published,
    required this.members,
    required this.compare,
    required this.attachments,
  });

  final int id;
  final String title, lead, source, catLabel, url, gap, docNo, org, published;
  final double score;
  final List<String> points, facts, entities, tags;
  final List<Member> members;
  final CompareBlock? compare;
  final List<Member> attachments;

  static NewsItem fromMap(Map<String, dynamic> m) => NewsItem(
        id: (m['id'] as num?)?.toInt() ?? 0,
        title: (m['title'] ?? '').toString(),
        lead: (m['lead'] ?? '').toString(),
        source: (m['source'] ?? '').toString(),
        catLabel: (m['cat_label'] ?? '').toString(),
        score: (m['score'] as num?)?.toDouble() ?? 0,
        url: (m['url'] ?? '').toString(),
        points: _strs(m['points']),
        facts: _strs(m['facts']),
        entities: _strs(m['entities']),
        tags: _strs(m['tags']),
        gap: (m['gap'] ?? '').toString(),
        docNo: (m['doc_no'] ?? '').toString(),
        org: (m['org'] ?? '').toString(),
        published: (m['published'] ?? '').toString(),
        members: ((m['members'] as List?) ?? const [])
            .map((e) => Member.fromMap(Map<String, dynamic>.from(e as Map)))
            .toList(),
        compare: CompareBlock.tryFrom(m['compare']),
        attachments: ((m['attachments'] as List?) ?? const [])
            .map((e) => Member.fromMap(Map<String, dynamic>.from(e as Map)))
            .toList(),
      );

  String get timeText {
    final t = DateTime.tryParse(published)?.toLocal();
    if (t == null) return '';
    return '${t.month}月${t.day}日';
  }
}

class Member {
  Member({required this.source, required this.title, required this.url});

  final String source, title, url;

  static Member fromMap(Map<String, dynamic> m) => Member(
        source: (m['source'] ?? m['name'] ?? '').toString(),
        title: (m['title'] ?? '').toString(),
        url: (m['url'] ?? '').toString(),
      );
}

class CompareBlock {
  CompareBlock({required this.lines, required this.gap});

  final List<String> lines;
  final String gap;

  static CompareBlock? tryFrom(dynamic raw) {
    if (raw is! Map) return null;
    final lines = <String>[];
    for (final e in ((raw['diff'] as List?) ?? const [])) {
      if (e is! Map) continue;
      final src = (e['source'] ?? '').toString();
      String txt = '';
      for (final k in const ['angle', 'summary', 'point', 'note', 'title']) {
        final v = e[k];
        if (v is String && v.isNotEmpty) {
          txt = v;
          break;
        }
      }
      lines.add(txt.isEmpty ? src : '$src｜$txt');
    }
    return CompareBlock(lines: lines, gap: (raw['gap'] ?? '').toString());
  }
}

Future<Briefing> loadBriefing() async {
  final res =
      await http.get(Uri.parse(kDataUrl)).timeout(const Duration(seconds: 30));
  if (res.statusCode != 200) {
    throw Exception('服务器返回 ${res.statusCode}');
  }
  final decoded = jsonDecode(utf8.decode(res.bodyBytes));
  if (decoded is! Map) throw Exception('数据格式不对');
  return Briefing.fromMap(Map<String, dynamic>.from(decoded));
}

Future<void> openUrl(BuildContext context, String url) async {
  final uri = Uri.tryParse(url.trim());
  if (uri == null || !uri.hasScheme) return;
  try {
    await launchUrl(uri, mode: LaunchMode.externalApplication);
  } catch (_) {
    if (context.mounted) {
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('打不开这个链接')));
    }
  }
}

Color scoreColor(double s, bool dark) {
  if (s >= 75) return dark ? const Color(0xFFE57373) : const Color(0xFFB3402A);
  if (s >= 60) return dark ? const Color(0xFFFFB74D) : const Color(0xFFB0722A);
  return dark ? const Color(0xFF9E9E9E) : const Color(0xFF8A8A8A);
}

// ---------------------------------------------------------------------------
// 首页：窄屏单列，宽屏（≥640dp，Z Fold 7 内屏）左右分栏
// ---------------------------------------------------------------------------

class HomePage extends StatefulWidget {
  const HomePage({super.key});

  @override
  State<HomePage> createState() => _HomeState();
}

class _HomeState extends State<HomePage> {
  Briefing? _data;
  String? _error;
  bool _loading = true;
  int _selected = 0;

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  Future<void> _refresh() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final d = await loadBriefing();
      if (!mounted) return;
      setState(() {
        _data = d;
        _loading = false;
        if (_selected >= d.items.length) _selected = 0;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString();
        _loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final dark = Theme.of(context).brightness == Brightness.dark;
    return Scaffold(
      appBar: AppBar(
        title: const Text('静水',
            style: TextStyle(fontWeight: FontWeight.w700, letterSpacing: 3)),
        actions: [
          IconButton(
            onPressed: _loading ? null : _refresh,
            icon: const Icon(Icons.refresh),
            tooltip: '刷新',
          ),
        ],
      ),
      body: _buildBody(dark),
    );
  }

  Widget _buildBody(bool dark) {
    if (_loading) {
      return const Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            CircularProgressIndicator(),
            SizedBox(height: 14),
            Text('正在取今日简报…'),
          ],
        ),
      );
    }
    if (_error != null || _data == null) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.cloud_off, size: 44),
            const SizedBox(height: 12),
            const Text('取不到简报，检查一下网络'),
            const SizedBox(height: 6),
            Text(_error ?? '', style: const TextStyle(fontSize: 11)),
            const SizedBox(height: 14),
            FilledButton.tonal(onPressed: _refresh, child: const Text('重试')),
          ],
        ),
      );
    }
    final d = _data!;
    return RefreshIndicator(
      onRefresh: _refresh,
      child: LayoutBuilder(
        builder: (context, box) {
          final wide = box.maxWidth >= 640;
          if (!wide) {
            return ListView(
              physics: const AlwaysScrollableScrollPhysics(),
              padding: const EdgeInsets.fromLTRB(12, 8, 12, 24),
              children: [
                BriefHeader(d: d, dark: dark),
                const SizedBox(height: 6),
                for (final it in d.items)
                  ItemTile(
                    item: it,
                    dark: dark,
                    selected: false,
                    onTap: () => Navigator.push(
                      context,
                      MaterialPageRoute(
                        builder: (_) => DetailPage(item: it),
                      ),
                    ),
                  ),
              ],
            );
          }
          if (d.items.isEmpty) {
            return ListView(children: [
              BriefHeader(d: d, dark: dark),
              const Padding(padding: EdgeInsets.all(40), child: Text('今天没有精选内容')),
            ]);
          }
          final sel = d.items[_selected.clamp(0, d.items.length - 1)];
          return Row(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              SizedBox(
                width: 400,
                child: ListView(
                  physics: const AlwaysScrollableScrollPhysics(),
                  padding: const EdgeInsets.fromLTRB(12, 8, 8, 24),
                  children: [
                    BriefHeader(d: d, dark: dark),
                    const SizedBox(height: 6),
                    for (var i = 0; i < d.items.length; i++)
                      ItemTile(
                        item: d.items[i],
                        dark: dark,
                        selected: i == _selected,
                        onTap: () => setState(() => _selected = i),
                      ),
                  ],
                ),
              ),
              const VerticalDivider(width: 1),
              Expanded(
                child: DetailView(
                  item: sel,
                  dark: dark,
                  onOpen: (u) => openUrl(context, u),
                ),
              ),
            ],
          );
        },
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// 头部简报卡
// ---------------------------------------------------------------------------

class BriefHeader extends StatelessWidget {
  const BriefHeader({super.key, required this.d, required this.dark});

  final Briefing d;
  final bool dark;

  @override
  Widget build(BuildContext context) {
    final bg = dark ? const Color(0xFF1E2128) : Colors.white;
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: Theme.of(context).dividerColor, width: .6),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Text(d.date,
                  style: const TextStyle(
                      fontSize: 15, fontWeight: FontWeight.w700)),
              const Spacer(),
              Text('生成于 ${d.genTimeText}',
                  style: TextStyle(
                      fontSize: 11,
                      color: Theme.of(context).hintColor)),
            ],
          ),
          const SizedBox(height: 10),
          Text(d.headline,
              style: const TextStyle(
                  fontSize: 17, height: 1.45, fontWeight: FontWeight.w600)),
          if (d.themes.isNotEmpty) ...[
            const SizedBox(height: 10),
            Wrap(
              spacing: 6,
              runSpacing: 6,
              children: [
                for (final t in d.themes) _chip(t, dark, accent: true),
              ],
            ),
          ],
          if (d.watch.isNotEmpty) ...[
            const SizedBox(height: 10),
            Text('重点跟踪：${d.watch.join('、')}',
                style: TextStyle(
                    fontSize: 12.5, color: Theme.of(context).hintColor)),
          ],
          const SizedBox(height: 8),
          Text(
            '抓取 ${d.rawCount} · 去重 ${d.uniqCount} · 精选 ${d.items.length} · ${d.sourceCount} 个源',
            style: TextStyle(
                fontSize: 11.5, color: Theme.of(context).hintColor),
          ),
        ],
      ),
    );
  }
}

Widget _chip(String text, bool dark, {bool accent = false}) {
  final bg = accent
      ? (dark ? const Color(0xFF3A3226) : const Color(0xFFF1E8D8))
      : (dark ? const Color(0xFF26292F) : const Color(0xFFF2F0EA));
  final fg = accent
      ? (dark ? const Color(0xFFE0C99A) : const Color(0xFF7A5B2E))
      : (dark ? const Color(0xFFB9BDC4) : const Color(0xFF55595F));
  return Container(
    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
    decoration:
        BoxDecoration(color: bg, borderRadius: BorderRadius.circular(20)),
    child: Text(text, style: TextStyle(fontSize: 11.5, color: fg)),
  );
}

// ---------------------------------------------------------------------------
// 列表条目
// ---------------------------------------------------------------------------

class ItemTile extends StatelessWidget {
  const ItemTile({
    super.key,
    required this.item,
    required this.dark,
    required this.selected,
    required this.onTap,
  });

  final NewsItem item;
  final bool dark;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final bg = selected
        ? (dark ? const Color(0xFF2A2E36) : const Color(0xFFF4EDE0))
        : (dark ? const Color(0xFF1E2128) : Colors.white);
    final border = selected
        ? Border.all(color: scoreColor(item.score, dark), width: 1.1)
        : Border.all(color: Theme.of(context).dividerColor, width: .6);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          borderRadius: BorderRadius.circular(12),
          onTap: onTap,
          child: Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: bg,
              borderRadius: BorderRadius.circular(12),
              border: border,
            ),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Container(
                  width: 40,
                  height: 40,
                  alignment: Alignment.center,
                  decoration: BoxDecoration(
                    color: scoreColor(item.score, dark).withValues(alpha: .13),
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: Text(
                    item.score.round().toString(),
                    style: TextStyle(
                      fontWeight: FontWeight.w700,
                      fontSize: 14,
                      color: scoreColor(item.score, dark),
                    ),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        item.title,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                            fontSize: 14.5, height: 1.35),
                      ),
                      const SizedBox(height: 5),
                      Text(
                        [
                          item.catLabel,
                          item.source,
                          if (item.timeText.isNotEmpty) item.timeText,
                          if (item.members.length > 1)
                            '多源 ${item.members.length}',
                        ].join(' · '),
                        style: TextStyle(
                            fontSize: 11,
                            color: Theme.of(context).hintColor),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// 详情（左右分栏的右栏 / 窄屏的独立页共用）
// ---------------------------------------------------------------------------

class DetailView extends StatelessWidget {
  const DetailView({
    super.key,
    required this.item,
    required this.dark,
    required this.onOpen,
  });

  final NewsItem item;
  final bool dark;
  final void Function(String url) onOpen;

  @override
  Widget build(BuildContext context) {
    final hint = Theme.of(context).hintColor;
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(20, 18, 20, 40),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(item.title,
              style: const TextStyle(
                  fontSize: 19, height: 1.45, fontWeight: FontWeight.w700)),
          const SizedBox(height: 10),
          Wrap(
            spacing: 6,
            runSpacing: 6,
            children: [
              _chip(item.catLabel, dark, accent: true),
              _chip(item.source, dark),
              if (item.timeText.isNotEmpty) _chip(item.timeText, dark),
              if (item.docNo.isNotEmpty) _chip(item.docNo, dark),
              if (item.org.isNotEmpty) _chip(item.org, dark),
            ],
          ),
          if (item.lead.isNotEmpty) ...[
            const SizedBox(height: 16),
            Container(
              padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
              decoration: BoxDecoration(
                border: Border(
                  left: BorderSide(
                      color: scoreColor(item.score, dark), width: 3),
                ),
              ),
              child: Text(item.lead,
                  style: const TextStyle(
                      fontSize: 15.5, height: 1.6)),
            ),
          ],
          if (item.points.isNotEmpty) ...[
            const SizedBox(height: 16),
            Text('要点',
                style: TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                    color: hint)),
            const SizedBox(height: 6),
            for (final p in item.points)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 4),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Padding(
                      padding: EdgeInsets.only(top: 8),
                      child: Text('· ',
                          style: TextStyle(fontWeight: FontWeight.w900)),
                    ),
                    Expanded(
                        child: Text(p,
                            style: const TextStyle(
                                fontSize: 14.5, height: 1.55))),
                  ],
                ),
              ),
          ],
          if (item.facts.isNotEmpty) ...[
            const SizedBox(height: 14),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: dark ? const Color(0xFF20242B) : const Color(0xFFF5F1E8),
                borderRadius: BorderRadius.circular(10),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('可引用的数字与表述',
                      style: TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.w700,
                          color: hint)),
                  const SizedBox(height: 6),
                  for (final f in item.facts)
                    Padding(
                      padding: const EdgeInsets.symmetric(vertical: 3),
                      child: Text(f,
                          style: const TextStyle(
                              fontSize: 13.5, height: 1.5)),
                    ),
                ],
              ),
            ),
          ],
          if (item.compare != null && item.compare!.lines.isNotEmpty) ...[
            const SizedBox(height: 14),
            Text('同一事件 · 多源对比',
                style: TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                    color: hint)),
            const SizedBox(height: 6),
            for (final l in item.compare!.lines)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 3),
                child: Text(l,
                    style: const TextStyle(fontSize: 13, height: 1.5)),
              ),
            if (item.compare!.gap.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Text('差异：${item.compare!.gap}',
                    style: TextStyle(
                        fontSize: 12.5, color: hint, height: 1.5)),
              ),
          ],
          if (item.members.length > 1) ...[
            const SizedBox(height: 14),
            Text(
              '同一事件另有：${item.members.skip(1).map((m) => m.source).take(4).join('、')} 报道',
              style: TextStyle(fontSize: 12, color: hint),
            ),
          ],
          if (item.attachments.isNotEmpty) ...[
            const SizedBox(height: 14),
            Text('附件',
                style: TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                    color: hint)),
            const SizedBox(height: 4),
            for (final a in item.attachments)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 2),
                child: InkWell(
                  onTap: a.url.isEmpty ? null : () => onOpen(a.url),
                  child: Text('📎 ${a.source}',
                      style: const TextStyle(
                          fontSize: 13,
                          color: Color(0xFF3B6EA5),
                          height: 1.5)),
                ),
              ),
          ],
          if (item.tags.isNotEmpty) ...[
            const SizedBox(height: 14),
            Wrap(
              spacing: 6,
              runSpacing: 6,
              children: [for (final t in item.tags) _chip('#$t', dark)],
            ),
          ],
          if (item.gap.isNotEmpty) ...[
            const SizedBox(height: 12),
            Text('说明：${item.gap}',
                style: TextStyle(fontSize: 12, color: hint, height: 1.5)),
          ],
          const SizedBox(height: 22),
          if (item.url.isNotEmpty)
            FilledButton.tonalIcon(
              onPressed: () => onOpen(item.url),
              icon: const Icon(Icons.open_in_new, size: 16),
              label: const Text('阅读原文'),
            ),
        ],
      ),
    );
  }
}

class DetailPage extends StatelessWidget {
  const DetailPage({super.key, required this.item});

  final NewsItem item;

  @override
  Widget build(BuildContext context) {
    final dark = Theme.of(context).brightness == Brightness.dark;
    return Scaffold(
      appBar: AppBar(title: Text(item.catLabel)),
      body: DetailView(
        item: item,
        dark: dark,
        onOpen: (u) => openUrl(context, u),
      ),
    );
  }
}
