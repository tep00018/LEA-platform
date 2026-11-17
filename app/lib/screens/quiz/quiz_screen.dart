import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../api/models.dart';
import '../../course/course_state.dart';
import '../../quiz/quiz_controller.dart';
import '../../shell/app_shell.dart';
import '../../shell/mode.dart';
import '../../shell/shell_info.dart';
import '../../theme/lea_colors.dart';
import '../../theme/lea_type.dart';
import '../../tutor/tutor_controller.dart';
import '../../widgets/ghost_button.dart';
import '../../widgets/skeleton.dart';
import '../../widgets/week_complete_banner.dart';
import 'question_panel.dart';
import 'results_view.dart';

/// Where the results live, so the tabs show no mode as active there (as in results-*.png).
const quizResultsPath = '/quiz/results';

/// Quiz (DESIGN.md, "Quiz question", "Quiz feedback", "Quiz results").
class QuizScreen extends ConsumerWidget {
  const QuizScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final info = ref.watch(shellInfoProvider).value;
    final state = ref.watch(quizProvider);
    final location = GoRouterState.of(context).uri.path;

    if (info == null || (state.loading && state.quiz == null)) return const _QuizSkeleton();
    if (state.loadError != null && state.quiz == null) {
      return _Message(text: state.loadError!.message, onRetry: () => ref.read(quizProvider.notifier).load());
    }

    final quiz = state.quiz;
    final onThisWeek = quiz != null && quiz.course == info.course.code && quiz.week == info.selectedWeek;

    // Keep the address in step: results at /quiz/results, everything else at /quiz.
    final wantResults = onThisWeek && quiz.completed;
    if (wantResults != (location == quizResultsPath)) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (context.mounted) context.go(wantResults ? quizResultsPath : Mode.quiz.path);
      });
    }

    if (!onThisWeek) {
      return _StartPanel(
        info: info,
        otherQuiz: quiz != null && !quiz.completed ? quiz : null,
        busy: state.busy,
        error: state.actionError?.message,
      );
    }
    if (quiz.completed) return _Results(quiz: quiz, info: info, busy: state.busy, error: state.actionError?.message);
    return _QuestionScreen(key: ValueKey('${quiz.quizId}-${quiz.position}'), state: state, info: info);
  }
}

/// Looks up objective and learning-objective names in the week's mastery data.
class _Names {
  _Names(this.mastery);

  final WeekMastery? mastery;

  String? loForSkill(String skill) {
    for (final lo in mastery?.learningObjectives ?? const <LearningObjectiveMastery>[]) {
      if (lo.objectives.any((o) => o.skillName == skill)) return lo.title;
    }
    return null;
  }

  ({String name, String? lo})? forGo(String? goId) {
    for (final lo in mastery?.learningObjectives ?? const <LearningObjectiveMastery>[]) {
      for (final o in lo.objectives) {
        if (o.goId == goId) return (name: o.skillName, lo: lo.title);
      }
    }
    return null;
  }
}

class _QuestionScreen extends ConsumerStatefulWidget {
  const _QuestionScreen({super.key, required this.state, required this.info});

  final QuizState state;
  final ShellInfo info;

  @override
  ConsumerState<_QuestionScreen> createState() => _QuestionScreenState();
}

class _QuestionScreenState extends ConsumerState<_QuestionScreen> {
  final _text = TextEditingController();
  String? _choice;

  @override
  void dispose() {
    _text.dispose();
    super.dispose();
  }

  String? _answer(QuizQuestion q) => switch (q.type) {
    'multiple_choice' || 'true_false' => _choice,
    'open_ended' => _text.text.trim().length >= openAnswerMin ? _text.text.trim() : null,
    _ => _text.text.trim().isEmpty ? null : _text.text.trim(),
  };

  void _submit(QuizQuestion q) {
    final answer = _answer(q);
    if (answer != null) ref.read(quizProvider.notifier).answer(answer);
  }

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final metrics = ShellMetrics.of(context);
    final state = widget.state;
    final quiz = state.quiz!;
    final question = state.question;
    final feedback = quiz.feedback;
    final mastery = ref.watch(weekMasteryProvider((course: quiz.course, week: quiz.week))).value;
    final names = _Names(mastery);
    final loTitle = question == null ? names.forGo(feedback?.goId)?.lo : names.loForSkill(question.skillName);
    final notifier = ref.read(quizProvider.notifier);
    final last = quiz.position >= quiz.total;

    return ColoredBox(
      color: c.bg,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          QuizBar(quiz: quiz, loTitle: loTitle, wide: metrics.wide),
          Expanded(
            child: SingleChildScrollView(
              padding: EdgeInsets.symmetric(horizontal: metrics.sidePadding, vertical: 20),
              child: Align(
                alignment: Alignment.topLeft,
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 716),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      if (question != null) ...[
                        QuestionText(question: question, wide: metrics.wide),
                        const SizedBox(height: 16),
                        ListenableBuilder(
                          listenable: _text,
                          builder: (context, _) => AnswerArea(
                            question: question,
                            value: _choice,
                            controller: _text,
                            feedback: feedback,
                            onChanged: (v) => setState(() {
                              if (question.type == 'multiple_choice' || question.type == 'true_false') _choice = v;
                            }),
                            onSubmit: () => _submit(question),
                          ),
                        ),
                        const SizedBox(height: 16),
                      ] else if (feedback != null && feedback.yourAnswer.isNotEmpty) ...[
                        // Reopened mid-feedback: the API no longer sends the question.
                        Text('Your answer: ${feedback.yourAnswer}', style: LeaType.bodyText().copyWith(color: c.ink)),
                        const SizedBox(height: 16),
                      ],
                      if (feedback != null) ...[FeedbackBox(feedback: feedback), const SizedBox(height: 16)],
                      if (state.actionError != null) ...[
                        Semantics(
                          liveRegion: true,
                          child: Text(state.actionError!.message, style: LeaType.small().copyWith(color: c.danger)),
                        ),
                        const SizedBox(height: 12),
                      ],
                      // Wraps "End quiz" under the button when there isn't room (large text).
                      Wrap(
                        alignment: WrapAlignment.spaceBetween,
                        crossAxisAlignment: WrapCrossAlignment.center,
                        spacing: 16,
                        runSpacing: 12,
                        children: [
                          if (feedback == null)
                            ListenableBuilder(
                              listenable: _text,
                              builder: (context, _) => FilledButton(
                                onPressed: state.busy || question == null || _answer(question) == null
                                    ? null
                                    : () => _submit(question),
                                child: Text(state.busy ? 'Checking…' : 'Submit answer'),
                              ),
                            )
                          else
                            FilledButton(
                              onPressed: state.busy ? null : notifier.next,
                              child: Text(last ? 'See results' : 'Next question'),
                            ),
                          Semantics(
                            button: true,
                            label: 'End quiz',
                            child: InkWell(
                              onTap: state.busy ? null : notifier.end,
                              borderRadius: BorderRadius.circular(4),
                              child: ExcludeSemantics(
                                child: Text(
                                  'End quiz',
                                  style: LeaType.small().copyWith(
                                    color: c.muted,
                                    decoration: TextDecoration.underline,
                                    decorationColor: c.muted,
                                  ),
                                ),
                              ),
                            ),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _Results extends ConsumerWidget {
  const _Results({required this.quiz, required this.info, required this.busy, required this.error});

  final QuizView quiz;
  final ShellInfo info;
  final bool busy;
  final String? error;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.lea;
    final metrics = ShellMetrics.of(context);
    final mastery = ref.watch(weekMasteryProvider((course: quiz.course, week: quiz.week))).value;
    final names = _Names(mastery);
    final next = quiz.advancedToWeek;
    final nextTopic = next == null ? null : info.weeks.where((w) => w.number == next).firstOrNull?.topic;
    final notifier = ref.read(quizProvider.notifier);

    return ColoredBox(
      color: c.bg,
      child: SingleChildScrollView(
        padding: EdgeInsets.symmetric(horizontal: metrics.sidePadding, vertical: 20),
        child: Align(
          alignment: Alignment.topLeft,
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 776),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                if (next != null) ...[
                  WeekCompleteBanner(week: quiz.week, nextWeek: next, nextTopic: nextTopic),
                  const SizedBox(height: 18),
                ],
                Semantics(header: true, label: 'Quiz results', child: const SizedBox.shrink()),
                ScoreBlock(quiz: quiz, wide: metrics.wide),
                if (quiz.results.isNotEmpty) ...[
                  const SizedBox(height: 18),
                  ResultsList(results: quiz.results, objective: names.forGo),
                ],
                const SizedBox(height: 18),
                Wrap(
                  spacing: 10,
                  runSpacing: 10,
                  children: [
                    FilledButton(
                      onPressed: busy
                          ? null
                          : () {
                              if (next != null) {
                                ref.read(selectionProvider.notifier).selectWeek(next);
                                notifier.startNew(quiz.course, next);
                              } else {
                                notifier.startNew(quiz.course, quiz.week);
                              }
                            },
                      child: Text(next != null ? 'Start Week $next quiz' : 'Start a new quiz'),
                    ),
                    GhostButton(
                      label: 'Review with the tutor',
                      onPressed: () {
                        // The tutor starts from these results and teaches only the objectives that were missed.
                        ref.read(tutorProvider.notifier).start(quiz.course, quiz.week, reviewQuiz: true);
                        context.go(Mode.tutor.path);
                      },
                    ),
                  ],
                ),
                if (error != null) ...[
                  const SizedBox(height: 10),
                  Text(error!, style: LeaType.small().copyWith(color: c.danger)),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _StartPanel extends ConsumerWidget {
  const _StartPanel({required this.info, required this.otherQuiz, required this.busy, required this.error});

  final ShellInfo info;

  /// An unfinished quiz on another week, which starting this one ends.
  final QuizView? otherQuiz;
  final bool busy;
  final String? error;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.lea;
    final metrics = ShellMetrics.of(context);
    final outline = ref.watch(outlineProvider(info.course.code)).value;
    final count =
        outline?.week(info.selectedWeek)?.learningObjectives.fold<int>(0, (n, lo) => n + lo.conceptCount) ?? 0;
    final other = otherQuiz;

    return SingleChildScrollView(
      padding: EdgeInsets.symmetric(horizontal: metrics.sidePadding, vertical: 20),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 760),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text('QUIZ', style: LeaType.label(11.5).copyWith(color: c.muted)),
            const SizedBox(height: 8),
            Semantics(
              header: true,
              child: Text(
                'Check yourself: ${info.selected.label}',
                style: LeaType.screenTitle(wide: metrics.wide).copyWith(color: c.ink),
              ),
            ),
            const SizedBox(height: 6),
            Text(
              '${count == 0 ? 'One question' : '$count questions, one'} for each objective this week. Graded answers '
              "count towards mastery; you'll see how you did after each one.",
              style: LeaType.bodyText().copyWith(color: c.muted),
            ),
            if (other != null) ...[
              const SizedBox(height: 16),
              Text(
                'You have a Week ${other.week} quiz in progress (question ${other.position} of ${other.total}). '
                'Starting Week ${info.selectedWeek} ends it; your answers so far still count.',
                style: LeaType.small().copyWith(color: c.ink),
              ),
            ],
            const SizedBox(height: 18),
            Wrap(
              spacing: 10,
              runSpacing: 10,
              children: [
                FilledButton(
                  onPressed: busy
                      ? null
                      : () => ref.read(quizProvider.notifier).start(info.course.code, info.selectedWeek),
                  child: Text(busy ? 'Preparing your quiz…' : 'Start Week ${info.selectedWeek} quiz'),
                ),
                if (other != null)
                  GhostButton(
                    label: 'Back to Week ${other.week}',
                    onPressed: () => ref.read(selectionProvider.notifier).selectWeek(other.week),
                  ),
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
  }
}

class _QuizSkeleton extends StatelessWidget {
  const _QuizSkeleton();

  @override
  Widget build(BuildContext context) {
    final pad = ShellMetrics.of(context).sidePadding;
    return Semantics(
      label: 'Loading the quiz',
      child: Padding(
        padding: EdgeInsets.symmetric(horizontal: pad, vertical: 18),
        child: const Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SkeletonBox(height: 10, radius: 99),
            SizedBox(height: 26),
            SkeletonBox(width: 200, height: 12),
            SizedBox(height: 14),
            SkeletonBox(width: 480, height: 26),
            SizedBox(height: 16),
            SkeletonBox(height: 52, radius: 12),
            SizedBox(height: 8),
            SkeletonBox(height: 52, radius: 12),
            SizedBox(height: 8),
            SkeletonBox(height: 52, radius: 12),
          ],
        ),
      ),
    );
  }
}

class _Message extends StatelessWidget {
  const _Message({required this.text, required this.onRetry});

  final String text;
  final VoidCallback onRetry;

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
          GhostButton(label: 'Try again', onPressed: onRetry),
        ],
      ),
    );
  }
}
