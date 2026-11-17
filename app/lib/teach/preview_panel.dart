import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../api/api_error.dart';
import '../chat/chat_controller.dart';
import '../course/course_state.dart';
import '../quiz/quiz_controller.dart';
import '../theme/lea_colors.dart';
import '../theme/lea_type.dart';
import '../tutor/tutor_controller.dart';
import '../widgets/ghost_button.dart';
import 'preview_state.dart';
import 'teach_models.dart';
import 'teach_state.dart';

/// The persistent preview banner (it can't be dismissed): "Preview: your answers aren't
/// recorded as student data", with Reset preview and Back to teaching (`preview-*.png`).
class PreviewBar extends ConsumerWidget {
  const PreviewBar({super.key, required this.session});

  final PreviewSession session;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.lea;
    final wide = MediaQuery.sizeOf(context).width >= 720;
    final text = Text.rich(
      TextSpan(
        children: [
          TextSpan(
            text: 'Preview: ',
            style: LeaType.ui(13, weight: FontWeight.w600),
          ),
          const TextSpan(text: "your answers aren't recorded as student data"),
          if (wide) TextSpan(text: ' · ${session.course} · published version ${session.version}'),
        ],
      ),
      style: LeaType.ui(13).copyWith(color: c.ink),
    );
    Future<void> reset() async {
      try {
        await ref.read(previewProvider.notifier).reset();
      } on ApiError catch (e) {
        if (context.mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
      }
    }

    void back() {
      ref.read(previewProvider.notifier).exit();
      context.go(TeachSection.objectives.path(session.course));
    }

    final buttons = [
      GhostButton(label: 'Reset preview', onPressed: reset),
      FilledButton(onPressed: back, child: const Text('Back to teaching')),
    ];
    return Semantics(
      container: true,
      liveRegion: true,
      child: Container(
        padding: EdgeInsets.symmetric(horizontal: wide ? 18 : 12, vertical: 8),
        decoration: BoxDecoration(
          color: c.accentSoft,
          border: Border(bottom: BorderSide(color: c.accent)),
        ),
        child: wide
            ? Row(
                children: [
                  ExcludeSemantics(child: Icon(Icons.visibility_outlined, size: 18, color: c.ink)),
                  const SizedBox(width: 10),
                  Expanded(child: text),
                  ...buttons.expand((b) => [const SizedBox(width: 8), b]),
                ],
              )
            : Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  text,
                  const SizedBox(height: 6),
                  Wrap(spacing: 8, children: buttons),
                ],
              ),
      ),
    );
  }
}

/// "Why the tutor did this" (teachers only): the latest preview turn, the content it
/// used, and things to try. Refreshes after every tutor, quiz or chat turn.
class ExplainPanel extends ConsumerStatefulWidget {
  const ExplainPanel({super.key, required this.session});

  static const width = 340.0;

  final PreviewSession session;

  @override
  ConsumerState<ExplainPanel> createState() => _ExplainPanelState();
}

class _ExplainPanelState extends ConsumerState<ExplainPanel> {
  final _tried = <String>{};

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final course = widget.session.course;
    void refresh() => ref.invalidate(previewExplainProvider);
    ref.listen(tutorProvider.select((s) => s.session?.messages.length), (_, _) => refresh());
    ref.listen(quizProvider.select((s) => s.quiz?.results.length), (_, _) => refresh());
    ref.listen(chatProvider(course).select((s) => s.entries.length), (_, _) => refresh());
    final week = ref.watch(selectionProvider).week;
    final turns = ref.watch(previewExplainProvider);
    final probes = ref.watch(previewProbesProvider((course: course, week: week)));

    return Material(
      color: c.surface,
      child: Container(
        width: ExplainPanel.width,
        decoration: BoxDecoration(
          border: Border(left: BorderSide(color: c.line)),
        ),
        child: ListView(
          padding: const EdgeInsets.fromLTRB(16, 14, 16, 20),
          children: [
            Row(
              children: [
                Expanded(
                  child: Semantics(
                    header: true,
                    child: Text('Why LEA did this', style: LeaType.heading(15).copyWith(color: c.ink)),
                  ),
                ),
                Text('Teachers only', style: LeaType.ui(11.5).copyWith(color: c.muted)),
                IconButton(
                  tooltip: 'Refresh',
                  visualDensity: VisualDensity.compact,
                  icon: Icon(Icons.refresh, size: 18, color: c.muted),
                  onPressed: refresh,
                ),
              ],
            ),
            const SizedBox(height: 10),
            switch (turns) {
              AsyncData(value: final list) when list.isEmpty => Text(
                'Reply to the tutor, answer a quiz question or ask Chat something, and the explanation appears here.',
                style: LeaType.small().copyWith(color: c.muted),
              ),
              AsyncData(value: final list) => _Turn(turn: list.first),
              AsyncError() => Text(
                "The explanation couldn't be loaded.",
                style: LeaType.small().copyWith(color: c.danger),
              ),
              _ => const SizedBox(height: 60),
            },
            const SizedBox(height: 16),
            Text('TRY THESE${week == null ? '' : ' · WEEK $week'}', style: LeaType.label(11).copyWith(color: c.muted)),
            const SizedBox(height: 6),
            for (final p in probes.value ?? const <Probe>[])
              CheckboxListTile(
                dense: true,
                contentPadding: EdgeInsets.zero,
                controlAffinity: ListTileControlAffinity.leading,
                value: _tried.contains(p.id),
                onChanged: (v) => setState(() => v == true ? _tried.add(p.id) : _tried.remove(p.id)),
                title: Text(p.text, style: LeaType.ui(12.5).copyWith(color: c.ink)),
              ),
          ],
        ),
      ),
    );
  }
}

class _Turn extends StatelessWidget {
  const _Turn({required this.turn});

  final PreviewTurn turn;

  String _n(Object? v) => v is num ? v.toStringAsFixed(2) : (v?.toString() ?? '—');

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final learner = turn.learner;
    final rows = <(String, String)>[
      ('Mode', turn.mode[0].toUpperCase() + turn.mode.substring(1)),
      if (turn.goId != null) ('Objective', '${turn.objective ?? ''} (${turn.goId})'),
      if (turn.mastery != null) ('Mastery', turn.mastery!),
      if (turn.mode != 'chat')
        (
          'Graded',
          turn.diagnostic
              ? 'Warm-up, not graded'
              : !turn.graded
              ? 'Not graded'
              : '${turn.correct == true ? 'Correct' : 'Incorrect'}${turn.score == null ? '' : ' · score ${_n(turn.score)}'}',
        ),
      ('ZPD', _n(learner['zpd'])),
      ('Cognitive load', _n(learner['cognitive_load'])),
      if (learner['motivation'] != null) ('Motivation', '${learner['motivation']}'.replaceAll('_', ' ')),
      if (learner['scaffolding'] != null)
        ('Scaffolding', [learner['scaffolding'], learner['intensity']].whereType<String>().join(' · ')),
    ];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (final (k, v) in rows)
          Padding(
            padding: const EdgeInsets.only(bottom: 4),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SizedBox(
                  width: 108,
                  child: Text(k, style: LeaType.ui(12.5).copyWith(color: c.muted)),
                ),
                Expanded(
                  child: Text(
                    v,
                    style: LeaType.ui(12.5, weight: FontWeight.w500).copyWith(color: c.ink),
                  ),
                ),
              ],
            ),
          ),
        if (turn.sources.isNotEmpty) ...[
          const SizedBox(height: 10),
          Text('COURSE CONTENT IT USED', style: LeaType.label(11).copyWith(color: c.muted)),
          const SizedBox(height: 6),
          for (final s in turn.sources)
            Container(
              width: double.infinity,
              margin: const EdgeInsets.only(bottom: 6),
              padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 7),
              decoration: BoxDecoration(
                border: Border.all(color: c.line),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    s.source,
                    style: LeaType.ui(12, weight: FontWeight.w600).copyWith(color: c.ink),
                  ),
                  Text(
                    s.excerpt,
                    style: LeaType.ui(12).copyWith(color: c.muted),
                    maxLines: 4,
                    overflow: TextOverflow.ellipsis,
                  ),
                ],
              ),
            ),
        ],
      ],
    );
  }
}

extension on PreviewTurn {
  /// "0.42 → 0.31 (threshold 0.85)".
  String? get mastery {
    if (masteryBefore == null && masteryAfter == null) return null;
    String f(double? v) => v == null ? '—' : v.toStringAsFixed(2);
    final t = threshold == null ? '' : ' (threshold ${threshold!.toStringAsFixed(2)})';
    return '${f(masteryBefore)} → ${f(masteryAfter)}$t';
  }
}
