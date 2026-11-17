import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/api_error.dart';
import '../../api/models.dart';
import '../../course/course_state.dart';
import '../../shell/app_shell.dart';
import '../../shell/shell_info.dart';
import '../../theme/lea_colors.dart';
import '../../theme/lea_type.dart';
import '../../widgets/ghost_button.dart';
import '../../widgets/meter.dart';
import '../../widgets/pressable.dart';
import '../../widgets/skeleton.dart';

/// Progress (DESIGN.md, "Progress"; `progress-*.png`): week cards, then every objective of
/// the selected week with its mastery against its own threshold.
class ProgressScreen extends ConsumerWidget {
  const ProgressScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.lea;
    final metrics = ShellMetrics.of(context);
    final info = ref.watch(shellInfoProvider).value;
    if (info == null) return const _ProgressSkeleton();

    final masteryAsync = ref.watch(weekMasteryProvider((course: info.course.code, week: info.selectedWeek)));
    final mastery = masteryAsync.value;

    return ColoredBox(
      color: c.bg,
      child: SingleChildScrollView(
        padding: EdgeInsets.symmetric(horizontal: metrics.sidePadding, vertical: 20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Semantics(header: true, label: 'Your progress', child: const SizedBox.shrink()),
            _WeekCards(info: info),
            const SizedBox(height: 18),
            const _Legend(),
            const SizedBox(height: 18),
            if (mastery != null)
              for (final (i, lo) in mastery.learningObjectives.indexed) ...[
                if (i > 0) const SizedBox(height: 18),
                _LoBlock(lo: lo, wide: metrics.wide),
              ]
            else if (masteryAsync.hasError)
              _Error(
                error: masteryAsync.error!,
                onRetry: () => ref.invalidate(weekMasteryProvider((course: info.course.code, week: info.selectedWeek))),
              )
            else
              const _ObjectivesSkeleton(),
            if (mastery != null && mastery.learningObjectives.isEmpty)
              Text('No objectives for this week yet.', style: LeaType.bodyText().copyWith(color: c.muted)),
          ],
        ),
      ),
    );
  }
}

/// One card per week: the selected week outlined in `primary`; locked weeks say when they
/// open. Cards share a row while each can be at least 200 px wide (the mockup's auto-fit grid).
class _WeekCards extends ConsumerWidget {
  const _WeekCards({required this.info});

  final ShellInfo info;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return LayoutBuilder(
      builder: (context, constraints) {
        const gap = 10.0;
        final n = info.weeks.length;
        final fit = ((constraints.maxWidth + gap) / (200 + gap)).floor().clamp(1, n);
        final rows = <List<WeekSummary>>[for (var i = 0; i < n; i += fit) info.weeks.sublist(i, (i + fit).clamp(0, n))];
        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            for (final (r, row) in rows.indexed) ...[
              if (r > 0) const SizedBox(height: gap),
              IntrinsicHeight(
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    for (var i = 0; i < fit; i++) ...[
                      if (i > 0) const SizedBox(width: gap),
                      Expanded(
                        child: i < row.length ? _WeekCard(week: row[i], info: info) : const SizedBox(),
                      ),
                    ],
                  ],
                ),
              ),
            ],
          ],
        );
      },
    );
  }
}

class _WeekCard extends ConsumerWidget {
  const _WeekCard({required this.week, required this.info});

  final WeekSummary week;
  final ShellInfo info;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.lea;
    final selected = week.number == info.selectedWeek;
    final current = week.number == info.currentWeek;
    final status = week.locked ? 'Locked' : (current ? 'Current' : 'Completed');
    final lockText = week.number == info.currentWeek + 1
        ? 'Opens at $weekUnlockPercent% of Week ${info.currentWeek}'
        : 'Opens after Week ${week.number - 1}';
    final mastery = week.locked
        ? null
        : ref.watch(weekMasteryProvider((course: info.course.code, week: week.number))).value;
    final muted = LeaType.ui(13).copyWith(color: c.muted);

    final card = Container(
      padding: EdgeInsets.symmetric(horizontal: selected ? 13 : 14, vertical: selected ? 11 : 12),
      decoration: BoxDecoration(
        color: c.surface,
        border: Border.all(color: selected ? c.primary : c.line, width: selected ? 2.5 : 1),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Expanded(child: Text('Week ${week.number}', style: muted)),
              Text(status, style: muted),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            week.topic,
            style: LeaType.ui(15, weight: FontWeight.w600, height: 1.35).copyWith(color: c.ink),
          ),
          const SizedBox(height: 8),
          if (week.locked)
            Text(lockText, style: LeaType.ui(12.5, height: 1.45).copyWith(color: c.muted))
          else if (mastery == null)
            const SkeletonBox(height: 40)
          else ...[
            Row(
              crossAxisAlignment: CrossAxisAlignment.center,
              children: [
                Text(
                  '${(mastery.completion * 100).round()}%',
                  style: LeaType.heading(
                    26,
                    weight: const FontWeight(750),
                    height: 1.2,
                  ).copyWith(color: c.ink, fontFeatures: LeaType.tabular),
                ),
                const Spacer(),
                Flexible(
                  child: Text(
                    '${mastery.masteredCount} of ${mastery.total} mastered',
                    textAlign: TextAlign.right,
                    style: LeaType.ui(12.5).copyWith(color: c.muted, fontFeatures: LeaType.tabular),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),
            Meter(value: mastery.completion),
          ],
        ],
      ),
    );

    final semantics = [
      'Week ${week.number} · ${week.topic}',
      status,
      if (week.locked) lockText,
      if (mastery != null)
        '${(mastery.completion * 100).round()}%, ${mastery.masteredCount} of ${mastery.total} mastered',
      if (selected) 'shown below',
    ].join(', ');

    if (week.locked) return Semantics(label: semantics, excludeSemantics: true, child: card);
    return Pressable(
      onTap: selected ? null : () => ref.read(selectionProvider.notifier).selectWeek(week.number),
      selected: selected,
      borderRadius: 12,
      semanticLabel: semantics,
      excludeChildSemantics: true,
      child: card,
    );
  }
}

/// Mastered / In progress / Threshold.
class _Legend extends StatelessWidget {
  const _Legend();

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final text = LeaType.ui(12).copyWith(color: c.muted);
    Widget swatch(Color color) => Container(
      width: 14,
      height: 8,
      decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(99)),
    );
    Widget item(Widget mark, String label) => Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        mark,
        const SizedBox(width: 6),
        Text(label, style: text),
      ],
    );
    return ExcludeSemantics(
      child: Wrap(
        spacing: 14,
        runSpacing: 6,
        children: [
          item(swatch(c.primary), 'Mastered'),
          item(swatch(c.accent), 'In progress'),
          item(Container(width: 2, height: 12, color: c.ink), 'Threshold'),
        ],
      ),
    );
  }
}

/// A learning objective and its objectives, each with a gauge and "0.74 / 0.65".
class _LoBlock extends StatelessWidget {
  const _LoBlock({required this.lo, required this.wide});

  final LearningObjectiveMastery lo;
  final bool wide;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Semantics(
          header: true,
          child: Text(
            lo.title,
            style: LeaType.heading(16, weight: FontWeight.w700).copyWith(color: c.ink),
          ),
        ),
        const SizedBox(height: 8),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
          decoration: BoxDecoration(
            color: c.surface,
            border: Border.all(color: c.line),
            borderRadius: BorderRadius.circular(12),
          ),
          child: Column(
            children: [
              for (final (i, o) in lo.objectives.indexed)
                Container(
                  decoration: BoxDecoration(
                    border: i == 0 ? null : Border(top: BorderSide(color: c.line)),
                  ),
                  child: ObjectiveRow(objective: o, wide: wide),
                ),
            ],
          ),
        ),
      ],
    );
  }
}

/// One objective: name, gauge (10 px, `surface-2` track, fill `primary` if mastered else
/// `accent`, a 2 px `ink` tick at the threshold) and "0.74 / 0.65" on one line.
/// Wide: the three side by side; narrow: name and value, gauge underneath.
class ObjectiveRow extends StatelessWidget {
  const ObjectiveRow({super.key, required this.objective, required this.wide});

  final ObjectiveMastery objective;
  final bool wide;

  static String value(double? v) => v == null ? '–' : v.toStringAsFixed(2);

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final o = objective;
    final name = Text(o.skillName, style: LeaType.ui(13.5, height: 1.45).copyWith(color: c.ink));
    final numbers = Text.rich(
      TextSpan(
        style: LeaType.ui(12.5).copyWith(color: c.muted, fontFeatures: LeaType.tabular),
        children: [
          TextSpan(
            text: value(o.mastery),
            style: TextStyle(
              color: c.ink,
              fontWeight: FontWeight.w600,
              fontVariations: const [FontVariation.weight(600)],
            ),
          ),
          TextSpan(text: ' / ${value(o.threshold)}'),
        ],
      ),
      maxLines: 1,
      softWrap: false,
      textAlign: TextAlign.right,
    );
    final gauge = Gauge(value: o.mastery ?? 0, threshold: o.threshold, mastered: o.mastered);
    final semantics =
        '${o.skillName}: ${o.mastery == null ? 'not assessed yet' : 'mastery ${value(o.mastery)}'}, needs '
        '${value(o.threshold)}, ${o.mastered ? 'mastered' : 'in progress'}';

    return Semantics(
      label: semantics,
      excludeSemantics: true,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 7),
        child: wide
            ? Row(
                children: [
                  Expanded(flex: 10, child: name),
                  const SizedBox(width: 12),
                  Expanded(flex: 14, child: gauge),
                  const SizedBox(width: 12),
                  SizedBox(width: 92, child: numbers),
                ],
              )
            : Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Expanded(child: name),
                      const SizedBox(width: 12),
                      numbers,
                    ],
                  ),
                  const SizedBox(height: 6),
                  gauge,
                ],
              ),
      ),
    );
  }
}

/// A 10 px bar with a threshold tick. Static, so reduced motion needs nothing.
class Gauge extends StatelessWidget {
  const Gauge({super.key, required this.value, required this.threshold, required this.mastered});

  final double value;
  final double threshold;
  final bool mastered;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    return LayoutBuilder(
      builder: (context, constraints) {
        final w = constraints.maxWidth;
        return SizedBox(
          height: 18,
          child: Stack(
            clipBehavior: Clip.none,
            alignment: Alignment.centerLeft,
            children: [
              Container(
                height: 10,
                decoration: BoxDecoration(color: c.surface2, borderRadius: BorderRadius.circular(99)),
              ),
              Container(
                key: const ValueKey('gauge-fill'),
                height: 10,
                width: w * value.clamp(0.0, 1.0),
                decoration: BoxDecoration(
                  color: mastered ? c.primary : c.accent,
                  borderRadius: BorderRadius.circular(99),
                ),
              ),
              Positioned(
                key: const ValueKey('gauge-tick'),
                left: (w * threshold.clamp(0.0, 1.0) - 1).clamp(0.0, w - 2),
                top: 0,
                bottom: 0,
                child: Container(
                  width: 2,
                  decoration: BoxDecoration(color: c.ink, borderRadius: BorderRadius.circular(2)),
                ),
              ),
            ],
          ),
        );
      },
    );
  }
}

class _Error extends StatelessWidget {
  const _Error({required this.error, required this.onRetry});

  final Object error;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Semantics(
          liveRegion: true,
          child: Text(
            error is ApiError ? (error as ApiError).message : "Couldn't load your progress. Please try again.",
            style: LeaType.bodyText().copyWith(color: c.ink),
          ),
        ),
        const SizedBox(height: 10),
        GhostButton(label: 'Try again', onPressed: onRetry),
      ],
    );
  }
}

class _ObjectivesSkeleton extends StatelessWidget {
  const _ObjectivesSkeleton();

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: 'Loading your progress',
      child: const Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [SkeletonBox(width: 140, height: 16), SizedBox(height: 10), SkeletonBox(height: 180, radius: 12)],
      ),
    );
  }
}

class _ProgressSkeleton extends StatelessWidget {
  const _ProgressSkeleton();

  @override
  Widget build(BuildContext context) {
    final pad = ShellMetrics.of(context).sidePadding;
    return Padding(
      padding: EdgeInsets.symmetric(horizontal: pad, vertical: 20),
      child: const Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [SkeletonBox(height: 120, radius: 12), SizedBox(height: 18), _ObjectivesSkeleton()],
      ),
    );
  }
}
