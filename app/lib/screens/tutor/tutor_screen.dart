import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../api/models.dart';
import '../../course/course_state.dart';
import '../../shell/app_shell.dart';
import '../../shell/mode.dart';
import '../../shell/shell_info.dart';
import '../../theme/lea_colors.dart';
import '../../theme/lea_type.dart';
import '../../tutor/tutor_controller.dart';
import '../../util/time_format.dart';
import '../../widgets/composer.dart';
import '../../widgets/ghost_button.dart';
import '../../widgets/message_bubble.dart';
import '../../widgets/skeleton.dart';
import '../../widgets/week_complete_banner.dart';
import 'tutor_header.dart';

/// Tutor (DESIGN.md, "Tutor"; `tutor-*.png`): a start panel for the selected week, then a
/// guided conversation through its objectives with a header band showing where you are.
class TutorScreen extends ConsumerStatefulWidget {
  const TutorScreen({super.key});

  @override
  ConsumerState<TutorScreen> createState() => _TutorScreenState();
}

class _TutorScreenState extends ConsumerState<TutorScreen> {
  final _input = TextEditingController();
  String? _pending;

  static const hint = "Your replies count towards mastery. The first reply is a warm-up and doesn't count.";

  @override
  void dispose() {
    _input.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    final text = _input.text.trim();
    if (text.isEmpty) return;
    _pending = text;
    _input.clear();
    await ref.read(tutorProvider.notifier).reply(text);
  }

  void _onChange(TutorState? before, TutorState after) {
    // A failed reply goes back in the box, in the same update that ends it.
    if (before?.busy == true && !after.busy && after.pendingReply == null) {
      final text = _pending;
      _pending = null;
      if (after.actionError != null && text != null && _input.text.isEmpty) {
        _input.value = TextEditingValue(
          text: text,
          selection: TextSelection.collapsed(offset: text.length),
        );
      }
    }
    if (after.summary != null && before?.summary == null) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) _showSummary(after.summary!);
      });
    }
    if (after.achievements.isNotEmpty && before?.achievements != after.achievements) {
      final messenger = ScaffoldMessenger.maybeOf(context);
      for (final a in after.achievements) {
        messenger?.showSnackBar(SnackBar(content: Text(a)));
      }
      ref.read(tutorProvider.notifier).clearAchievements();
    }
  }

  Future<void> _showSummary(TutorSummary summary) async {
    final info = ref.read(shellInfoProvider).value;
    await showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      isScrollControlled: true,
      builder: (context) => _SummarySheet(summary: summary, info: info),
    );
    if (mounted) ref.read(tutorProvider.notifier).clearSummary();
  }

  void _goToWeek(int week) {
    // Progress has been refreshed; the new week is selectable once it reloads.
    ref.read(selectionProvider.notifier).selectWeek(week);
  }

  @override
  Widget build(BuildContext context) {
    ref.listen(tutorProvider, _onChange);
    final info = ref.watch(shellInfoProvider).value;
    final tutor = ref.watch(tutorProvider);
    final metrics = ShellMetrics.of(context);

    if (info == null || (tutor.loading && tutor.session == null)) return const _TutorSkeleton();
    if (tutor.loadError != null && tutor.session == null) {
      return _Message(
        text: tutor.loadError!.message,
        action: 'Try again',
        onAction: () => ref.read(tutorProvider.notifier).load(),
      );
    }

    final session = tutor.session;
    final week = info.selectedWeek;
    final onThisWeek = session != null && session.course == info.course.code && session.week == week;
    if (!onThisWeek) {
      return _StartPanel(
        info: info,
        otherSession: session != null && !session.completed ? session : null,
        busy: tutor.busy,
        error: tutor.actionError?.message,
        onStart: () => ref.read(tutorProvider.notifier).start(info.course.code, week),
        onBackToSession: session == null ? null : () => _goToWeek(session.week),
      );
    }

    final mastery = ref.watch(weekMasteryProvider((course: session.course, week: session.week))).value;
    final items = <Widget>[
      for (final e in tutor.entries)
        e.fromStudent
            ? StudentBubble(
                text: e.text,
                time: e.time == null ? '' : clockTime(e.time!),
                tag: switch (e.tag) {
                  ReplyTag.warmUp => const ReplyTagChip.warmUp(),
                  ReplyTag.countedCorrect => const ReplyTagChip.counted(correct: true),
                  ReplyTag.countedNotYet => const ReplyTagChip.counted(correct: false),
                  ReplyTag.notCounted => const ReplyTagChip.notCounted(),
                  null => null,
                },
              )
            : LeaBubble(text: e.text, streaming: e.streaming),
    ];

    return ColoredBox(
      color: context.lea.bg,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          TutorHeader(
            session: session,
            mastery: mastery,
            wide: metrics.wide,
            busy: tutor.busy,
            onEnd: () => ref.read(tutorProvider.notifier).end(),
          ),
          Expanded(
            child: SelectionArea(
              child: ListView.separated(
                reverse: true,
                padding: EdgeInsets.symmetric(horizontal: metrics.sidePadding, vertical: 18),
                itemCount: items.length,
                separatorBuilder: (_, _) => const SizedBox(height: 14),
                itemBuilder: (_, i) => items[items.length - 1 - i],
              ),
            ),
          ),
          if (session.completed)
            _CompletionPanel(
              session: session,
              info: info,
              busy: tutor.busy,
              error: tutor.actionError?.message,
              onSummary: () => ref.read(tutorProvider.notifier).end(),
              onNextWeek: session.advancedToWeek == null ? null : () => _goToWeek(session.advancedToWeek!),
              onQuiz: () => context.go(Mode.quiz.path),
            )
          else
            Composer(
              controller: _input,
              placeholder: 'Share your thoughts, ask a question, or work through the problem…',
              onSend: _send,
              wide: metrics.wide,
              busy: tutor.busy,
              hint: hint,
              error: tutor.actionError?.message,
            ),
        ],
      ),
    );
  }
}

/// Before a session: what the week covers and a Start button.
class _StartPanel extends StatelessWidget {
  const _StartPanel({
    required this.info,
    required this.otherSession,
    required this.busy,
    required this.error,
    required this.onStart,
    required this.onBackToSession,
  });

  final ShellInfo info;

  /// An unfinished session on another week, which starting this one replaces.
  final TutorView? otherSession;
  final bool busy;
  final String? error;
  final VoidCallback onStart;
  final VoidCallback? onBackToSession;

  @override
  Widget build(BuildContext context) {
    return Consumer(
      builder: (context, ref, _) {
        final c = context.lea;
        final metrics = ShellMetrics.of(context);
        final outline = ref.watch(outlineProvider(info.course.code)).value;
        final week = outline?.week(info.selectedWeek);
        final los = week?.learningObjectives ?? const <LearningObjectiveInfo>[];
        final count = los.fold<int>(0, (n, lo) => n + lo.conceptCount);
        // How much of each learning objective is already mastered; absent while loading or if it fails,
        // in which case the list reads as before.
        final mastery = ref.watch(weekMasteryProvider((course: info.course.code, week: info.selectedWeek))).value;
        final byLo = {for (final lo in mastery?.learningObjectives ?? const <LearningObjectiveMastery>[]) lo.loId: lo};
        final masteredTotal = byLo.values.fold<int>(0, (n, lo) => n + lo.objectives.where((o) => o.mastered).length);

        return SingleChildScrollView(
          padding: EdgeInsets.symmetric(horizontal: metrics.sidePadding, vertical: 20),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 760),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text('TUTOR', style: LeaType.label(11.5).copyWith(color: c.muted)),
                const SizedBox(height: 8),
                Semantics(
                  header: true,
                  child: Text(
                    'Ready to learn: ${info.selected.label}',
                    style: LeaType.screenTitle(wide: metrics.wide).copyWith(color: c.ink),
                  ),
                ),
                const SizedBox(height: 6),
                Text(
                  count == 0
                      ? 'LEA will guide you through the week one objective at a time.'
                      : masteredTotal == 0
                      ? '$count objectives. LEA will guide you through them one at a time and adjust to how '
                            "you're doing."
                      : masteredTotal >= count
                      ? "$count objectives, and you've mastered all of them. There's no need to repeat the "
                            'tutorial. You can take the quiz for a refresher.'
                      : '$count objectives, $masteredTotal already mastered. LEA will go through the other '
                            '${count - masteredTotal} with you and skip what you know.',
                  style: LeaType.bodyText().copyWith(color: c.muted),
                ),
                if (los.isNotEmpty) ...[
                  const SizedBox(height: 18),
                  Text("WHAT WE'LL COVER", style: LeaType.label(11).copyWith(color: c.muted)),
                  const SizedBox(height: 8),
                  Container(
                    decoration: BoxDecoration(
                      color: c.surface,
                      border: Border.all(color: c.line),
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: Column(
                      children: [
                        for (final (i, lo) in los.indexed)
                          Semantics(
                            label: '${i + 1}. ${lo.title}, ${_coverage(lo, byLo[lo.id]).label}',
                            excludeSemantics: true,
                            child: Container(
                              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 11),
                              decoration: BoxDecoration(
                                border: i == 0 ? null : Border(top: BorderSide(color: c.line)),
                              ),
                              child: Row(
                                children: [
                                  SizedBox(
                                    width: 28,
                                    child: Text(
                                      '${i + 1}',
                                      style: LeaType.small().copyWith(color: c.muted, fontFeatures: LeaType.tabular),
                                    ),
                                  ),
                                  Expanded(
                                    child: Text(lo.title, style: LeaType.small().copyWith(color: c.ink)),
                                  ),
                                  _CoverageTag(coverage: _coverage(lo, byLo[lo.id])),
                                ],
                              ),
                            ),
                          ),
                      ],
                    ),
                  ),
                ],
                if (otherSession != null) ...[
                  const SizedBox(height: 16),
                  Text(
                    'You have a Week ${otherSession!.week} session in progress. Starting Week ${info.selectedWeek} '
                    'ends it.',
                    style: LeaType.small().copyWith(color: c.ink),
                  ),
                ],
                const SizedBox(height: 18),
                Wrap(
                  spacing: 10,
                  runSpacing: 10,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: [
                    FilledButton(
                      onPressed: busy ? null : onStart,
                      child: Text(busy ? 'Starting…' : 'Start Week ${info.selectedWeek}'),
                    ),
                    if (otherSession != null && onBackToSession != null)
                      GhostButton(label: 'Back to Week ${otherSession!.week}', onPressed: onBackToSession!),
                  ],
                ),
                if (error != null) ...[
                  const SizedBox(height: 12),
                  Semantics(
                    liveRegion: true,
                    child: Text(error!, style: LeaType.small().copyWith(color: c.danger)),
                  ),
                ],
              ],
            ),
          ),
        );
      },
    );
  }
}

/// How much of a learning objective the student has already mastered.
class _Coverage {
  const _Coverage(this.mastered, this.total);

  final int mastered;
  final int total;

  bool get all => total > 0 && mastered >= total;

  String get label => all
      ? 'mastered'
      : mastered > 0
      ? '$mastered of $total mastered'
      : '$total objective${total == 1 ? '' : 's'}';
}

_Coverage _coverage(LearningObjectiveInfo lo, LearningObjectiveMastery? mastery) {
  if (mastery == null || mastery.objectives.isEmpty) return _Coverage(0, lo.conceptCount);
  return _Coverage(mastery.objectives.where((o) => o.mastered).length, mastery.objectives.length);
}

/// "4 objectives", "2 of 4 mastered", or a check and "Mastered". The words carry the meaning; the
/// check and colour only reinforce it.
class _CoverageTag extends StatelessWidget {
  const _CoverageTag({required this.coverage});

  final _Coverage coverage;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    if (coverage.all) {
      return Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.check_circle, size: 16, color: c.success),
          const SizedBox(width: 4),
          Text(
            'Mastered',
            style: LeaType.ui(12).copyWith(color: c.success, fontWeight: FontWeight.w600),
          ),
        ],
      );
    }
    return Text(coverage.label, style: LeaType.ui(12).copyWith(color: coverage.mastered > 0 ? c.success : c.muted));
  }
}

/// Replaces the composer once every objective is covered.
class _CompletionPanel extends StatelessWidget {
  const _CompletionPanel({
    required this.session,
    required this.info,
    required this.busy,
    required this.error,
    required this.onSummary,
    required this.onNextWeek,
    required this.onQuiz,
  });

  final TutorView session;
  final ShellInfo info;
  final bool busy;
  final String? error;
  final VoidCallback onSummary;
  final VoidCallback? onNextWeek;
  final VoidCallback onQuiz;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final metrics = ShellMetrics.of(context);
    final next = session.advancedToWeek;
    final nextTopic = next == null ? null : info.weeks.where((w) => w.number == next).firstOrNull?.topic;

    return Container(
      padding: EdgeInsets.fromLTRB(metrics.sidePadding, 14, metrics.sidePadding, 16),
      decoration: BoxDecoration(
        color: c.bg,
        border: Border(top: BorderSide(color: c.line)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        mainAxisSize: MainAxisSize.min,
        children: [
          if (next != null)
            WeekCompleteBanner(week: session.week, nextWeek: next, nextTopic: nextTopic)
          else
            Semantics(
              liveRegion: true,
              child: Text(
                "You've worked through every objective this week. Take the quiz to check yourself, or look at "
                'your summary.',
                style: LeaType.small().copyWith(color: c.ink),
              ),
            ),
          const SizedBox(height: 12),
          Wrap(
            spacing: 10,
            runSpacing: 10,
            children: [
              if (onNextWeek != null)
                FilledButton(onPressed: onNextWeek, child: Text('Go to Week $next'))
              else
                FilledButton(onPressed: onQuiz, child: Text('Take the Week ${session.week} quiz')),
              GhostButton(label: busy ? 'Ending…' : 'See summary', onPressed: busy ? null : onSummary),
            ],
          ),
          if (error != null) ...[
            const SizedBox(height: 8),
            Text(error!, style: LeaType.small().copyWith(color: c.danger)),
          ],
        ],
      ),
    );
  }
}

class _SummarySheet extends StatelessWidget {
  const _SummarySheet({required this.summary, required this.info});

  final TutorSummary summary;
  final ShellInfo? info;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final next = summary.advancedToWeek;
    final nextTopic = next == null ? null : info?.weeks.where((w) => w.number == next).firstOrNull?.topic;
    Widget stat(String value, String label) => Expanded(
      child: Semantics(
        label: '$label: $value',
        excludeSemantics: true,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              value,
              style: LeaType.heading(
                26,
                weight: const FontWeight(750),
              ).copyWith(color: c.ink, fontFeatures: LeaType.tabular),
            ),
            Text(label, style: LeaType.ui(12).copyWith(color: c.muted)),
          ],
        ),
      ),
    );

    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(22, 0, 22, 22),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Semantics(
              header: true,
              child: Text(
                'Session summary',
                style: LeaType.heading(22, weight: const FontWeight(750)).copyWith(color: c.ink),
              ),
            ),
            const SizedBox(height: 16),
            Row(
              children: [
                stat('${summary.gosCompleted} / ${summary.totalGos}', 'Objectives covered'),
                stat('${summary.gosMastered}', 'Mastered'),
                stat('${summary.accuracyPercent}%', 'Replies correct'),
              ],
            ),
            const SizedBox(height: 12),
            Text(
              '${summary.interactionCount} repl${summary.interactionCount == 1 ? 'y' : 'ies'} in this session.',
              style: LeaType.small().copyWith(color: c.muted),
            ),
            if (next != null) ...[
              const SizedBox(height: 14),
              WeekCompleteBanner(week: next - 1, nextWeek: next, nextTopic: nextTopic),
            ],
            const SizedBox(height: 18),
            FilledButton(onPressed: () => Navigator.of(context).pop(), child: const Text('Done')),
          ],
        ),
      ),
    );
  }
}

class _TutorSkeleton extends StatelessWidget {
  const _TutorSkeleton();

  @override
  Widget build(BuildContext context) {
    final pad = ShellMetrics.of(context).sidePadding;
    return Semantics(
      label: 'Loading the tutor',
      child: Padding(
        padding: EdgeInsets.symmetric(horizontal: pad, vertical: 18),
        child: const Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SkeletonBox(width: 150, height: 12),
            SizedBox(height: 12),
            SkeletonBox(width: 260, height: 26),
            SizedBox(height: 12),
            SkeletonBox(width: 300, height: 10, radius: 99),
            SizedBox(height: 28),
            SkeletonBox(height: 90, radius: 14),
          ],
        ),
      ),
    );
  }
}

class _Message extends StatelessWidget {
  const _Message({required this.text, required this.action, required this.onAction});

  final String text;
  final String action;
  final VoidCallback onAction;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final pad = ShellMetrics.of(context).sidePadding;
    return Padding(
      padding: EdgeInsets.symmetric(horizontal: pad, vertical: 20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Semantics(
            liveRegion: true,
            child: Text(text, style: LeaType.bodyText().copyWith(color: c.ink)),
          ),
          const SizedBox(height: 10),
          GhostButton(label: action, onPressed: onAction),
        ],
      ),
    );
  }
}
