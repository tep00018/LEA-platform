import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../api/api_error.dart';
import '../../teach/analytics_models.dart';
import '../../teach/analytics_state.dart';
import '../../teach/download.dart';
import '../../teach/teach_state.dart';
import '../../teach/teach_widgets.dart';
import '../../theme/lea_colors.dart';
import '../../theme/lea_type.dart';
import '../../widgets/ghost_button.dart';
import '../../widgets/skeleton.dart';

const _ranges = [(null, 'All time'), (7, 'Last 7 days'), (30, 'Last 30 days'), (90, 'Last 90 days')];

/// Analytics (`analytics-*.png`): each objective's band, students, first-try accuracy,
/// attempts to master and "needs attention", most in need first; usage last. Real
/// students only unless "Simulated" is chosen; nothing from fewer than 5 students.
class AnalyticsScreen extends ConsumerStatefulWidget {
  const AnalyticsScreen({super.key, required this.code});

  final String code;

  @override
  ConsumerState<AnalyticsScreen> createState() => _AnalyticsScreenState();
}

class _AnalyticsScreenState extends ConsumerState<AnalyticsScreen> {
  bool _exporting = false;

  Future<void> _export() async {
    setState(() => _exporting = true);
    try {
      final bytes = await curvesCsv(ref, widget.code);
      await saveBytes('${widget.code}_learning_curves.csv', bytes, 'text/csv');
    } on ApiError catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    } finally {
      if (mounted) setState(() => _exporting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final wide = MediaQuery.sizeOf(context).width >= 720;
    final code = widget.code;
    final overview = ref.watch(analyticsOverviewProvider(code));
    final kind = ref.watch(analyticsKindProvider);
    final week = ref.watch(analyticsWeekProvider);
    final days = ref.watch(analyticsDaysProvider);
    final weeks = ref.watch(teachCourseProvider(code)).value?.weeks ?? 0;
    final o = overview.value;
    final who = kind == 'simulated' ? 'simulated students only' : 'real sessions only';
    final subtitle = o == null
        ? null
        : o.students == null
        ? 'Analytics start at ${o.minStudents} students · $who'
        : '${o.students} students · $who · version ${o.kcVersion}';
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        TeachHeader(
          kicker: '$code · Analytics',
          title: week == null ? 'Objectives' : 'Objectives in week $week',
          subtitle: subtitle,
          actions: [
            TeachFilter<int?>(
              label: 'Week',
              value: week,
              options: [(null, 'All weeks'), for (var w = 1; w <= weeks; w++) (w, 'Week $w')],
              onChanged: ref.read(analyticsWeekProvider.notifier).set,
            ),
            TeachFilter<int?>(
              label: 'Date range',
              value: days,
              options: _ranges,
              onChanged: ref.read(analyticsDaysProvider.notifier).set,
            ),
            TeachFilter<String>(
              label: 'Students',
              value: kind,
              options: const [('real', 'Real students'), ('simulated', 'Simulated students')],
              onChanged: (k) => ref.read(analyticsKindProvider.notifier).set(k),
            ),
            if (wide)
              GhostButton(
                label: _exporting ? 'Exporting…' : 'Export curves (CSV)',
                onPressed: _exporting || o == null || o.suppressed ? null : _export,
              ),
          ],
        ),
        Expanded(
          child: switch (overview) {
            AsyncError(:final error) => Padding(
              padding: const EdgeInsets.all(24),
              child: TeachError(error: error, onRetry: () => ref.invalidate(analyticsOverviewProvider(code))),
            ),
            AsyncData(value: final o) => ListView(
              padding: EdgeInsets.fromLTRB(wide ? 24 : 16, 18, wide ? 24 : 16, 24),
              children: [
                if (!wide) ...[const DesktopOnlyNote(), const SizedBox(height: 12)],
                if (kind == 'simulated')
                  const Padding(
                    padding: EdgeInsets.only(bottom: 12),
                    child: TeachBanner(
                      tone: BannerTone.soft,
                      child: Text('Simulated students: seeded data for trying these screens, not real learners.'),
                    ),
                  ),
                if (o.students == null)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: TeachBanner(
                      child: Text(
                        'Not enough students yet: analytics start at ${o.minStudents}. '
                        'Nothing is shown about fewer than ${o.minStudents} students.',
                      ),
                    ),
                  ),
                _BandSummary(overview: o, wide: wide),
                const SizedBox(height: 14),
                if (o.objectives.isEmpty)
                  const TeachBanner(tone: BannerTone.soft, child: Text('No published objectives for this filter.'))
                else
                  TeachCard(
                    padding: EdgeInsets.zero,
                    child: Column(
                      children: [
                        if (wide) const _TableHeader(),
                        for (final (i, s) in o.objectives.indexed)
                          _ObjectiveRow(
                            stats: s,
                            wide: wide,
                            first: i == 0 && !wide,
                            onTap: () => context.go('/teach/courses/$code/analytics/${s.goId}'),
                          ),
                      ],
                    ),
                  ),
                const SizedBox(height: 14),
                _UsageCard(usage: o.usage, range: _ranges.firstWhere((r) => r.$1 == days).$2),
                const SizedBox(height: 8),
                Text(
                  'Test accounts and "Try as a student" sessions are never included.',
                  style: LeaType.ui(12).copyWith(color: c.muted),
                ),
              ],
            ),
            _ => const Padding(padding: EdgeInsets.all(24), child: SkeletonBox(height: 240)),
          },
        ),
      ],
    );
  }
}

class _BandSummary extends StatelessWidget {
  const _BandSummary({required this.overview, required this.wide});

  final AnalyticsOverview overview;
  final bool wide;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final stats = Wrap(
      spacing: 32,
      runSpacing: 12,
      children: [
        for (final (key, label) in analyticsBands) TeachStat(value: '${overview.bands[key] ?? 0}', label: label),
      ],
    );
    final note = Text(
      '“Needs attention” is LEA’s heuristic: low first-attempt accuracy, a flat learning curve, '
      'tutor struggles and chat questions on the topic.',
      style: LeaType.ui(12.5).copyWith(color: c.muted),
    );
    return TeachCard(
      child: wide
          ? Row(
              children: [
                stats,
                const SizedBox(width: 32),
                Expanded(child: note),
              ],
            )
          : Column(crossAxisAlignment: CrossAxisAlignment.start, children: [stats, const SizedBox(height: 10), note]),
    );
  }
}

const _flex = [5, 3, 2, 2, 2, 4];

class _TableHeader extends StatelessWidget {
  const _TableHeader();

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    Widget h(String t, int i, {bool end = false}) => Expanded(
      flex: _flex[i],
      child: Text(
        t.toUpperCase(),
        textAlign: end ? TextAlign.end : TextAlign.start,
        style: LeaType.label(11).copyWith(color: c.muted),
      ),
    );
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 10),
      child: Row(
        children: [
          h('Objective', 0),
          h('Band', 1),
          h('Students', 2, end: true),
          h('First-try accuracy', 3, end: true),
          h('Attempts to master', 4, end: true),
          const SizedBox(width: 20),
          h('Needs attention', 5),
        ],
      ),
    );
  }
}

class BandPill extends StatelessWidget {
  const BandPill(this.band, {super.key});

  final String band;

  @override
  Widget build(BuildContext context) => TeachPill(
    bandLabel(band),
    tone: switch (band) {
      'mastered' => PillTone.ok,
      'developing' => PillTone.warn,
      'struggling' => PillTone.bad,
      _ => PillTone.dashed,
    },
  );
}

/// "● High: a flat learning curve", "Low", or "Not enough students yet".
class AttentionText extends StatelessWidget {
  const AttentionText(this.stats, {super.key});

  final ObjectiveStats stats;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final a = stats.attention;
    final label = stats.suppressed ? 'Not enough students yet' : (a.label ?? '—');
    final high = a.level == 'high' && !stats.suppressed;
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (high)
          Padding(
            padding: const EdgeInsets.only(top: 5, right: 6),
            child: Container(
              width: 8,
              height: 8,
              decoration: BoxDecoration(color: c.danger, shape: BoxShape.circle),
            ),
          ),
        Flexible(
          child: Text(label, style: LeaType.ui(13).copyWith(color: high ? c.ink : c.muted)),
        ),
      ],
    );
  }
}

class _ObjectiveRow extends StatelessWidget {
  const _ObjectiveRow({required this.stats, required this.wide, required this.first, required this.onTap});

  final ObjectiveStats stats;
  final bool wide;
  final bool first;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final s = stats;
    final figure = LeaType.ui(13).copyWith(color: c.ink, fontFeatures: const [FontFeature.tabularFigures()]);
    final name = Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          s.skillName,
          style: LeaType.ui(13.5, weight: FontWeight.w600).copyWith(color: c.ink),
        ),
        const SizedBox(height: 2),
        IdText(s.goId),
      ],
    );
    return InkWell(
      key: Key('objective-${s.goId}'),
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        decoration: BoxDecoration(
          border: first ? null : Border(top: BorderSide(color: c.line)),
        ),
        child: wide
            ? Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(flex: _flex[0], child: name),
                  Expanded(
                    flex: _flex[1],
                    child: Align(alignment: Alignment.centerLeft, child: BandPill(s.band)),
                  ),
                  Expanded(
                    flex: _flex[2],
                    child: Text(studentCount(s.students), textAlign: TextAlign.end, style: figure),
                  ),
                  Expanded(
                    flex: _flex[3],
                    child: Text(ratio(s.firstAttemptAccuracy), textAlign: TextAlign.end, style: figure),
                  ),
                  Expanded(
                    flex: _flex[4],
                    child: Text(s.attemptsToMaster?.toStringAsFixed(1) ?? '—', textAlign: TextAlign.end, style: figure),
                  ),
                  const SizedBox(width: 20),
                  Expanded(flex: _flex[5], child: AttentionText(s)),
                ],
              )
            : Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  name,
                  const SizedBox(height: 6),
                  Wrap(
                    spacing: 8,
                    runSpacing: 4,
                    crossAxisAlignment: WrapCrossAlignment.center,
                    children: [
                      BandPill(s.band),
                      Text(
                        '${studentCount(s.students)} students · first try ${ratio(s.firstAttemptAccuracy)}',
                        style: LeaType.ui(12.5).copyWith(color: c.muted),
                      ),
                    ],
                  ),
                  const SizedBox(height: 4),
                  AttentionText(s),
                ],
              ),
      ),
    );
  }
}

class _UsageCard extends StatelessWidget {
  const _UsageCard({required this.usage, required this.range});

  final Usage usage;
  final String range;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final u = usage;
    return TeachCard(
      child: Wrap(
        spacing: 32,
        runSpacing: 12,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          Text('Usage · ${range.toLowerCase()}', style: LeaType.ui(13).copyWith(color: c.muted)),
          if (u.suppressed)
            Text('Not enough students yet', style: LeaType.ui(13).copyWith(color: c.muted))
          else ...[
            TeachStat(value: '${u.activeStudents}', label: 'active students'),
            TeachStat(value: '${u.sessions}', label: 'sessions'),
            TeachStat(value: '${(u.hours ?? 0).round()} h', label: 'time on task'),
            TeachStat(value: '${u.chatQuestions}', label: 'chat questions'),
          ],
        ],
      ),
    );
  }
}
