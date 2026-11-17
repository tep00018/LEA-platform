import 'package:flutter/material.dart';

import '../../api/models.dart';
import '../../theme/lea_colors.dart';
import '../../theme/lea_type.dart';
import '../../widgets/pressable.dart';

/// "Step-by-step · medium support": how the tutor is scaffolding, in student words.
String supportLabel(String strategy, String level) {
  const strategies = {
    'procedural': 'Step-by-step',
    'conceptual': 'Big ideas first',
    'strategic': 'Problem-solving',
    'metacognitive': 'Thinking it through',
  };
  const levels = {
    'very_high': 'lots of support',
    'high': 'high support',
    'medium': 'medium support',
    'low': 'light support',
    'minimal': 'minimal support',
  };
  final parts = [?strategies[strategy], ?levels[level]];
  if (parts.isEmpty) return 'Guided practice';
  final text = parts.join(' · ');
  return text[0].toUpperCase() + text.substring(1);
}

/// The header band over a tutor session: kicker ("Objective 3 of 11 · AI Basics"), the
/// objective as the title, the step indicator and the support pill.
class TutorHeader extends StatelessWidget {
  const TutorHeader({
    super.key,
    required this.session,
    required this.mastery,
    required this.wide,
    required this.onEnd,
    required this.busy,
  });

  final TutorView session;

  /// The week's objectives grouped by learning objective, with what's mastered.
  /// Null while loading; the steps then show position only.
  final WeekMastery? mastery;
  final bool wide;
  final VoidCallback onEnd;
  final bool busy;

  String? get _loTitle {
    final go = session.currentObjective?.goId;
    for (final lo in mastery?.learningObjectives ?? const <LearningObjectiveMastery>[]) {
      if (lo.objectives.any((o) => o.goId == go)) return lo.title;
    }
    return null;
  }

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final number = (session.objectiveIndex + 1).clamp(1, session.objectivesTotal);
    final kicker = LeaType.label(11.5).copyWith(color: c.muted, letterSpacing: 0.07 * 11.5);
    final title = session.completed
        ? 'Every objective covered'
        : (session.currentObjective?.skillName ?? 'Objective $number');

    return Container(
      padding: EdgeInsets.symmetric(horizontal: wide ? 22 : 16, vertical: 14),
      decoration: BoxDecoration(
        color: c.bg,
        border: Border(bottom: BorderSide(color: c.line)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Wrap(
                  spacing: 12,
                  runSpacing: 4,
                  children: [
                    Text(
                      session.completed
                          ? 'WEEK ${session.week} · ${session.objectivesTotal} OBJECTIVES'
                          : 'OBJECTIVE $number OF ${session.objectivesTotal}',
                      style: kicker,
                    ),
                    if (!session.completed && _loTitle != null) Text(_loTitle!.toUpperCase(), style: kicker),
                  ],
                ),
              ),
              if (!session.completed)
                // A Pressable like the rail's "Log out": the Semantics + InkWell version was
                // measured at the wrong screen position by the contrast check on Linux CI.
                Pressable(
                  onTap: busy ? null : onEnd,
                  borderRadius: 4,
                  semanticLabel: 'End session',
                  excludeChildSemantics: true,
                  child: Text(
                    'End session',
                    style: LeaType.ui(13)
                        .copyWith(color: c.muted, decoration: TextDecoration.underline, decorationColor: c.muted),
                  ),
                ),
            ],
          ),
          const SizedBox(height: 10),
          Semantics(
            header: true,
            child: Text(
              title,
              style: LeaType.screenTitle(wide: wide).copyWith(color: c.ink),
            ),
          ),
          const SizedBox(height: 10),
          Wrap(
            spacing: 10,
            runSpacing: 8,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              StepIndicator(session: session, mastery: mastery),
              _SupportPill(label: supportLabel(session.scaffoldingStrategy, session.scaffoldingLevel)),
              if (!session.completed) _DebugMetricsPill(session: session),
            ],
          ),
        ],
      ),
    );
  }
}

/// One 22×7 pill per objective, grouped by learning objective with 10 px gaps:
/// mastered `primary`, current `accent`, the rest `line`.
class StepIndicator extends StatelessWidget {
  const StepIndicator({super.key, required this.session, required this.mastery});

  final TutorView session;
  final WeekMastery? mastery;

  @override
  Widget build(BuildContext context) {
    final current = session.completed ? null : session.currentObjective?.goId;

    // Groups of (mastered, current) flags.
    final List<List<(bool, bool)>> groups;
    final los = mastery?.learningObjectives ?? const <LearningObjectiveMastery>[];
    if (los.isNotEmpty) {
      groups = [
        for (final lo in los) [for (final o in lo.objectives) (o.mastered, o.goId == current)],
      ];
    } else {
      groups = [
        [for (var i = 0; i < session.objectivesTotal; i++) (false, !session.completed && i == session.objectiveIndex)],
      ];
    }
    final total = groups.fold<int>(0, (n, g) => n + g.length);
    final mastered = groups.fold<int>(0, (n, g) => n + g.where((s) => s.$1).length);
    final number = (session.objectiveIndex + 1).clamp(1, session.objectivesTotal);

    return Semantics(
      label: session.completed
          ? '$total objectives, $mastered mastered'
          : 'Objective $number of $total, $mastered mastered',
      excludeSemantics: true,
      child: Wrap(
        spacing: 10,
        runSpacing: 6,
        children: [
          for (final group in groups)
            Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                for (final (i, (isMastered, isCurrent)) in group.indexed) ...[
                  if (i > 0) const SizedBox(width: 4),
                  StepPill(
                    kind: isMastered
                        ? StepKind.mastered
                        : isCurrent
                        ? StepKind.current
                        : StepKind.upcoming,
                  ),
                ],
              ],
            ),
        ],
      ),
    );
  }
}

enum StepKind { mastered, current, upcoming }

/// One 22×7 step: mastered `primary`, current `accent`, the rest `line`.
class StepPill extends StatelessWidget {
  const StepPill({super.key, required this.kind});

  final StepKind kind;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    return Container(
      width: 22,
      height: 7,
      decoration: BoxDecoration(
        color: switch (kind) {
          StepKind.mastered => c.primary,
          StepKind.current => c.accent,
          StepKind.upcoming => c.line,
        },
        borderRadius: BorderRadius.circular(99),
      ),
    );
  }
}

class _SupportPill extends StatelessWidget {
  const _SupportPill({required this.label});

  final String label;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 3),
      decoration: BoxDecoration(color: c.surface2, borderRadius: BorderRadius.circular(99)),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 7,
            height: 7,
            decoration: BoxDecoration(color: c.accent, shape: BoxShape.circle),
          ),
          const SizedBox(width: 6),
          Flexible(
            child: Text(label, style: LeaType.ui(12, height: 1.5).copyWith(color: c.ink)),
          ),
        ],
      ),
    );
  }
}

/// Mastery/cognitive-load/ZPD for the current objective, for testing by hand -- temporary,
/// remove once manual testing of the tester configuration (2026-09-27) is done. Shows
/// nothing when the session doesn't have any of these yet (an old server, or before the
/// first turn).
class _DebugMetricsPill extends StatelessWidget {
  const _DebugMetricsPill({required this.session});

  final TutorView session;

  String? _fmt(String label, double? value, {bool percent = false}) {
    if (value == null) return null;
    return percent ? '$label ${(value * 100).round()}%' : '$label ${value.toStringAsFixed(2)}';
  }

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final parts = [
      _fmt('Mastery', session.currentObjectiveMastery, percent: true),
      _fmt('Load', session.cognitiveLoad),
      _fmt('ZPD', session.zpdScore),
    ].whereType<String>().toList();
    if (parts.isEmpty) return const SizedBox.shrink();

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 3),
      decoration: BoxDecoration(
        border: Border.all(color: c.line, strokeAlign: BorderSide.strokeAlignInside),
        borderRadius: BorderRadius.circular(99),
      ),
      child: Semantics(
        label: 'Debug: ${parts.join(', ')}',
        child: ExcludeSemantics(
          child: Text('DEBUG · ${parts.join(' · ')}', style: LeaType.ui(11, height: 1.5).copyWith(color: c.muted)),
        ),
      ),
    );
  }
}

/// "Counted · correct" (success outline), "Counted · not yet", "Warm-up · not counted" or
/// "Not counted" (muted), under a student's reply.
class ReplyTagChip extends StatelessWidget {
  const ReplyTagChip.counted({super.key, required bool correct})
    : text = correct ? 'Counted · correct' : 'Counted · not yet',
      success = correct;

  const ReplyTagChip.warmUp({super.key}) : text = 'Warm-up · not counted', success = false;

  /// Not the warm-up, but the tutor's question wasn't one that could be checked -- distinct
  /// from `.warmUp` so a student doesn't read "warm-up" onto a reply partway through a session.
  const ReplyTagChip.notCounted({super.key}) : text = 'Not counted', success = false;

  final String text;
  final bool success;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final color = success ? c.success : c.muted;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 1),
      decoration: BoxDecoration(
        border: Border.all(color: color),
        borderRadius: BorderRadius.circular(99),
      ),
      child: Text(text, style: LeaType.ui(11, height: 1.5).copyWith(color: color)),
    );
  }
}
