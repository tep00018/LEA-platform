import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/api_error.dart';
import '../api/models.dart';
import '../api/sse.dart';
import '../course/course_state.dart';
import '../providers.dart';

/// The tag under a student's reply.
enum ReplyTag {
  /// The first reply answers "what do you already know?" and is never graded.
  warmUp,
  countedCorrect,
  countedNotYet,

  /// Not the warm-up, but still not graded (research, 2026-09-27): the tutor's question
  /// couldn't be checked -- e.g. it wasn't about the current objective, or nothing checkable
  /// was found in its message at all.
  notCounted,
}

/// One bubble in the tutor thread.
class TutorEntry {
  const TutorEntry({required this.fromStudent, required this.text, this.time, this.tag, this.streaming = false});

  final bool fromStudent;
  final String text;
  final DateTime? time;
  final ReplyTag? tag;
  final bool streaming;
}

class TutorState {
  const TutorState({
    this.loading = true,
    this.loadError,
    this.session,
    this.tags = const {},
    this.pendingReply,
    this.streamedText,
    this.busy = false,
    this.actionError,
    this.summary,
    this.achievements = const [],
  });

  final bool loading;
  final ApiError? loadError;

  /// The running (or just completed) session; null when there is none.
  final TutorView? session;

  /// Tags for student replies made in this app session, by index in `session.messages`.
  /// The API doesn't keep them, so replies from before a reload have none.
  final Map<int, ReplyTag> tags;

  /// The reply being sent, shown straight away.
  final String? pendingReply;

  /// The tutor's answer so far while it streams.
  final String? streamedText;

  /// Starting, replying or ending.
  final bool busy;

  /// Why the last start, reply or end failed.
  final ApiError? actionError;

  /// Set after ending a session, for the summary sheet.
  final TutorSummary? summary;

  /// Achievements from the last reply, to announce once.
  final List<String> achievements;

  List<TutorEntry> get entries {
    final messages = session?.messages ?? const <TutorMessage>[];
    return [
      for (final (i, m) in messages.indexed)
        TutorEntry(fromStudent: m.fromStudent, text: m.content, time: m.time, tag: tags[i]),
      if (pendingReply != null) TutorEntry(fromStudent: true, text: pendingReply!, time: DateTime.now()),
      if (streamedText != null) TutorEntry(fromStudent: false, text: streamedText!, streaming: true),
    ];
  }

  TutorState copyWith({
    bool? loading,
    ApiError? Function()? loadError,
    TutorView? Function()? session,
    Map<int, ReplyTag>? tags,
    String? Function()? pendingReply,
    String? Function()? streamedText,
    bool? busy,
    ApiError? Function()? actionError,
    TutorSummary? Function()? summary,
    List<String>? achievements,
  }) {
    return TutorState(
      loading: loading ?? this.loading,
      loadError: loadError == null ? this.loadError : loadError(),
      session: session == null ? this.session : session(),
      tags: tags ?? this.tags,
      pendingReply: pendingReply == null ? this.pendingReply : pendingReply(),
      streamedText: streamedText == null ? this.streamedText : streamedText(),
      busy: busy ?? this.busy,
      actionError: actionError == null ? this.actionError : actionError(),
      summary: summary == null ? this.summary : summary(),
      achievements: achievements ?? this.achievements,
    );
  }
}

/// The student's tutor session: `GET /tutor` on entry, `POST /tutor` to start,
/// `POST /tutor/replies/stream` to reply and `POST /tutor/end` to finish.
class TutorController extends Notifier<TutorState> {
  @override
  TutorState build() {
    // Nothing to load for nobody (just after logging out).
    if (ref.watch(sessionProvider) != null) Future.microtask(load);
    return const TutorState();
  }

  Future<void> load() async {
    state = state.copyWith(loading: true, loadError: () => null);
    try {
      final json = await ref.read(apiClientProvider).getObject('/tutor');
      if (!ref.mounted) return;
      state = state.copyWith(loading: false, session: () => TutorView.fromJson(json), tags: const {});
    } on ApiError catch (e) {
      if (!ref.mounted) return;
      if (e.status == 404) {
        state = state.copyWith(loading: false, session: () => null, tags: const {});
      } else {
        state = state.copyWith(loading: false, loadError: () => e);
      }
    }
  }

  /// Starts a session on [week] of [course] (or resumes the one running for it). With
  /// [reviewQuiz], a fresh session that knows the student's just-finished quiz on that week.
  Future<void> start(String course, int week, {bool reviewQuiz = false}) async {
    if (state.busy) return;
    state = state.copyWith(busy: true, actionError: () => null, summary: () => null);
    try {
      final json = await ref.read(apiClientProvider).postObject('/tutor', {
        'course': course,
        'week': week,
        if (reviewQuiz) 'review_quiz': true,
      });
      if (!ref.mounted) return;
      state = state.copyWith(busy: false, session: () => TutorView.fromJson(json), tags: const {});
      // Replacing an unfinished session on another week can move the student on.
      _refreshProgress(course);
    } on ApiError catch (e) {
      if (!ref.mounted) return;
      state = state.copyWith(busy: false, actionError: () => e);
    }
  }

  /// Sends [text] and streams the tutor's answer. Returns false if it failed.
  Future<bool> reply(String text) async {
    final session = state.session;
    final answer = text.trim();
    if (session == null || answer.isEmpty || state.busy) return false;

    final warmUp = !session.messages.any((m) => m.fromStudent);
    state = state.copyWith(
      busy: true,
      pendingReply: () => answer,
      streamedText: () => '',
      actionError: () => null,
      achievements: const [],
    );

    await for (final event in ref.read(apiClientProvider).postStream('/tutor/replies/stream', {'text': answer})) {
      if (!ref.mounted) return false;
      switch (event) {
        case ReplyToken(:final text):
          state = state.copyWith(streamedText: () => (state.streamedText ?? '') + text);
        case ReplyDone(:final body):
          final result = TutorReplyResult.fromJson(body);
          final updated = result.session;
          final index = updated.messages.lastIndexWhere((m) => m.fromStudent);
          final tag = warmUp
              ? ReplyTag.warmUp
              : result.graded
              ? (result.correct == true ? ReplyTag.countedCorrect : ReplyTag.countedNotYet)
              : ReplyTag.notCounted;
          state = state.copyWith(
            busy: false,
            session: () => updated,
            tags: {...state.tags, if (index >= 0) index: tag},
            pendingReply: () => null,
            streamedText: () => null,
            achievements: result.achievements,
          );
          if (updated.completed && updated.advancedToWeek != null) {
            // Moving on changes the course's current week, which an unpinned selection
            // follows. Pin this week so the completion stays on screen until the student
            // chooses to go on.
            ref.read(selectionProvider.notifier).selectWeek(updated.week);
          }
          if (result.graded || updated.completed) _refreshProgress(updated.course);
          return true;
        case ReplyFailed(:final error):
          state = state.copyWith(
            busy: false,
            pendingReply: () => null,
            streamedText: () => null,
            actionError: () => error,
          );
          // The session ended elsewhere (another device, or it expired).
          if (error.status == 404) await load();
          return false;
      }
    }
    return false;
  }

  /// Ends the session; the summary shows in [TutorState.summary].
  Future<void> end() async {
    final session = state.session;
    if (session == null || state.busy) return;
    state = state.copyWith(busy: true, actionError: () => null);
    try {
      final json = await ref.read(apiClientProvider).postObject('/tutor/end');
      if (!ref.mounted) return;
      state = state.copyWith(
        busy: false,
        session: () => null,
        tags: const {},
        summary: () => TutorSummary.fromJson(json),
      );
      _refreshProgress(session.course);
    } on ApiError catch (e) {
      if (!ref.mounted) return;
      if (e.status == 404) {
        state = state.copyWith(busy: false, session: () => null, tags: const {});
      } else {
        state = state.copyWith(busy: false, actionError: () => e);
      }
    }
  }

  void clearSummary() => state = state.copyWith(summary: () => null);

  void clearAchievements() => state = state.copyWith(achievements: const []);

  /// Mastery and the current week may have moved: reload what the rail and header show.
  void _refreshProgress(String course) {
    ref.invalidate(progressProvider(course));
    ref.invalidate(weekMasteryProvider);
  }
}

final tutorProvider = NotifierProvider<TutorController, TutorState>(TutorController.new);
