import 'package:flutter/material.dart';

import '../../api/models.dart';
import '../../theme/lea_colors.dart';
import '../../theme/lea_type.dart';

/// "80% of graded answers correct. One answer couldn't be graded and isn't counted."
String scoreSummary(QuizView quiz) {
  final notCounted = quiz.results.where((r) => r.correct == null).length;
  if (quiz.gradedCount == 0) {
    return quiz.results.isEmpty
        ? 'You ended the quiz before answering any questions.'
        : "None of your answers could be graded, so this quiz doesn't count.";
  }
  final percent = (100 * quiz.correctCount / quiz.gradedCount).round();
  final notCountedText = switch (notCounted) {
    0 => '',
    1 => " One answer couldn't be graded and isn't counted.",
    _ => " $notCounted answers couldn't be graded and aren't counted.",
  };
  return '$percent% of graded answers correct.$notCountedText';
}

/// The big "8 / 10" and the line explaining it.
class ScoreBlock extends StatelessWidget {
  const ScoreBlock({super.key, required this.quiz, required this.wide});

  final QuizView quiz;
  final bool wide;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final big = LeaType.bigScore(wide: wide).copyWith(color: c.ink);
    final score = Semantics(
      label: '${quiz.correctCount} out of ${quiz.gradedCount} correct',
      excludeSemantics: true,
      child: Text.rich(
        TextSpan(
          style: big,
          children: [
            TextSpan(text: '${quiz.correctCount}'),
            TextSpan(
              text: ' / ${quiz.gradedCount}',
              style: LeaType.heading(
                22,
                weight: FontWeight.w600,
              ).copyWith(color: c.muted, fontFeatures: LeaType.tabular),
            ),
          ],
        ),
      ),
    );
    final text = ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 400),
      child: Text(scoreSummary(quiz), style: LeaType.ui(14.5, height: 1.55).copyWith(color: c.muted)),
    );
    // Side by side on wide screens, stacked on phones (as in the screenshots).
    return wide
        ? Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              score,
              const SizedBox(width: 22),
              Flexible(child: text),
            ],
          )
        : Column(crossAxisAlignment: CrossAxisAlignment.start, children: [score, const SizedBox(height: 16), text]);
  }
}

/// Every question with its objective and a mark (Correct / Incorrect / Not counted).
class ResultsList extends StatelessWidget {
  const ResultsList({super.key, required this.results, required this.objective});

  final List<QuizFeedback> results;

  /// The objective's name and its learning objective, from the go_id.
  final ({String name, String? lo})? Function(String? goId) objective;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    return Container(
      decoration: BoxDecoration(
        color: c.surface,
        border: Border.all(color: c.line),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        children: [
          for (final (i, r) in results.indexed)
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 9),
              decoration: BoxDecoration(
                border: i == 0 ? null : Border(top: BorderSide(color: c.line)),
              ),
              child: Builder(
                builder: (context) {
                  final o = objective(r.goId);
                  final name = o?.name ?? 'Question ${i + 1}';
                  final mark = switch (r.correct) {
                    true => ('Correct', c.successSoft, c.success),
                    false => ('Incorrect', c.dangerSoft, c.danger),
                    null => ('Not counted', c.surface2, c.muted),
                  };
                  return Semantics(
                    label: 'Question ${i + 1}, $name${o?.lo == null ? '' : ', ${o!.lo}'}: ${mark.$1}',
                    excludeSemantics: true,
                    child: Row(
                      children: [
                        SizedBox(
                          width: 38,
                          child: Text(
                            '${i + 1}',
                            style: LeaType.small().copyWith(color: c.muted, fontFeatures: LeaType.tabular),
                          ),
                        ),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(name, style: LeaType.small().copyWith(color: c.ink)),
                              if (o?.lo != null) Text(o!.lo!, style: LeaType.ui(12).copyWith(color: c.muted)),
                            ],
                          ),
                        ),
                        const SizedBox(width: 10),
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 2),
                          decoration: BoxDecoration(color: mark.$2, borderRadius: BorderRadius.circular(99)),
                          child: Text(
                            mark.$1,
                            style: LeaType.ui(12, weight: FontWeight.w600).copyWith(color: mark.$3),
                          ),
                        ),
                      ],
                    ),
                  );
                },
              ),
            ),
        ],
      ),
    );
  }
}
