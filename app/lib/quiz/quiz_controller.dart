import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/api_error.dart';
import '../api/models.dart';
import '../course/course_state.dart';
import '../providers.dart';

class QuizState {
  const QuizState({this.loading = true, this.loadError, this.quiz, this.asked, this.busy = false, this.actionError});

  final bool loading;
  final ApiError? loadError;

  /// The quiz, or null when there is none.
  final QuizView? quiz;

  /// The question on screen before feedback came back. The API only sends the question
  /// while it's being asked, so the feedback screen draws the options from here.
  final QuizQuestion? asked;

  /// Starting, answering, moving on or ending.
  final bool busy;
  final ApiError? actionError;

  /// The question to draw now: the live one, or the one just answered.
  QuizQuestion? get question => quiz?.question ?? (quiz?.showingFeedback == true ? asked : null);

  QuizState copyWith({
    bool? loading,
    ApiError? Function()? loadError,
    QuizView? Function()? quiz,
    QuizQuestion? Function()? asked,
    bool? busy,
    ApiError? Function()? actionError,
  }) {
    return QuizState(
      loading: loading ?? this.loading,
      loadError: loadError == null ? this.loadError : loadError(),
      quiz: quiz == null ? this.quiz : quiz(),
      asked: asked == null ? this.asked : asked(),
      busy: busy ?? this.busy,
      actionError: actionError == null ? this.actionError : actionError(),
    );
  }
}

/// The student's quiz: `GET /quiz` on entry, `POST /quiz` to start, then
/// `/quiz/answer`, `/quiz/next` and `/quiz/end`. Nothing is sent until Submit.
class QuizController extends Notifier<QuizState> {
  @override
  QuizState build() {
    // Nothing to load for nobody (just after logging out).
    if (ref.watch(sessionProvider) != null) Future.microtask(load);
    return const QuizState();
  }

  Future<void> load() async {
    state = state.copyWith(loading: true, loadError: () => null);
    try {
      final json = await ref.read(apiClientProvider).getObject('/quiz');
      if (!ref.mounted) return;
      state = state.copyWith(loading: false, quiz: () => QuizView.fromJson(json));
    } on ApiError catch (e) {
      if (!ref.mounted) return;
      state = e.status == 404
          ? state.copyWith(loading: false, quiz: () => null)
          : state.copyWith(loading: false, loadError: () => e);
    }
  }

  /// Runs [call], which returns the new quiz. Returns it, or null on failure.
  Future<QuizView?> _act(Future<Map<String, dynamic>> Function() call, {QuizQuestion? asked}) async {
    if (state.busy) return null;
    state = state.copyWith(busy: true, actionError: () => null);
    try {
      final quiz = QuizView.fromJson(await call());
      if (!ref.mounted) return null;
      state = state.copyWith(busy: false, quiz: () => quiz, asked: () => asked ?? quiz.question);
      return quiz;
    } on ApiError catch (e) {
      if (!ref.mounted) return null;
      state = state.copyWith(busy: false, actionError: () => e);
      // The quiz ended elsewhere, or was already answered: show what the server has.
      if (e.status == 404 || e.status == 409) await load();
      return null;
    }
  }

  Future<void> start(String course, int week) async {
    final quiz = await _act(() => ref.read(apiClientProvider).postObject('/quiz', {'course': course, 'week': week}));
    // Replacing an unfinished quiz on another week ends it, which can move the student on.
    if (quiz != null) _refreshProgress(course);
  }

  /// A fresh quiz on [week]: `DELETE /quiz`, then `POST /quiz`.
  Future<void> startNew(String course, int week) async {
    if (state.busy) return;
    try {
      await ref.read(apiClientProvider).delete('/quiz');
    } on ApiError catch (e) {
      if (e.status != 404) {
        state = state.copyWith(actionError: () => e);
        return;
      }
    }
    if (!ref.mounted) return;
    state = state.copyWith(quiz: () => null, asked: () => null);
    await start(course, week);
  }

  Future<void> answer(String answer) async {
    final asked = state.quiz?.question;
    final quiz = await _act(
      () => ref.read(apiClientProvider).postObject('/quiz/answer', {'answer': answer}),
      asked: asked,
    );
    if (quiz != null && quiz.feedback?.graded == true) _refreshProgress(quiz.course);
  }

  Future<void> next() async {
    final quiz = await _act(() => ref.read(apiClientProvider).postObject('/quiz/next'));
    if (quiz != null && quiz.completed) _finished(quiz);
  }

  Future<void> end() async {
    final quiz = await _act(() => ref.read(apiClientProvider).postObject('/quiz/end'));
    if (quiz != null) _finished(quiz);
  }

  void _finished(QuizView quiz) {
    if (quiz.advancedToWeek != null) {
      // Moving on changes the current week, which an unpinned selection follows; pin this
      // week so the results stay on screen until the student chooses to go on.
      ref.read(selectionProvider.notifier).selectWeek(quiz.week);
    }
    _refreshProgress(quiz.course);
  }

  void _refreshProgress(String course) {
    ref.invalidate(progressProvider(course));
    ref.invalidate(weekMasteryProvider);
  }
}

final quizProvider = NotifierProvider<QuizController, QuizState>(QuizController.new);
