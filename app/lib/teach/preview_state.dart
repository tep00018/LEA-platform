import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/api_error.dart';
import '../providers.dart';
import 'teach_models.dart';

/// "Try as a student": while set, the student screens run as the teacher's sandbox account
/// (the API client sends its token on student endpoints; `/teach` keeps the teacher's).
class PreviewController extends Notifier<PreviewSession?> {
  /// Why the last preview ended by itself (shown in the Teacher area), if it did.
  String? endedMessage;

  @override
  PreviewSession? build() {
    // Logging out ends any preview.
    ref.listen(authProvider.select((s) => s.token), (_, token) {
      if (token == null) state = null;
    });
    return null;
  }

  /// Starts (or resumes) a preview of [course]; throws [ApiError] for the caller to show.
  Future<void> start(String course) async {
    final json = await ref.read(apiClientProvider).postObject('/teach/courses/$course/preview');
    endedMessage = null;
    state = PreviewSession.fromJson(json);
  }

  /// Forgets what the sandbox did in the course and starts it over.
  Future<void> reset() async {
    final session = state;
    if (session == null) return;
    await ref.read(apiClientProvider).post('/teach/courses/${session.course}/preview/reset');
    // A new token makes every student screen load again from nothing.
    await start(session.course);
  }

  void exit() => state = null;

  /// The sandbox token stopped working (expired or reset elsewhere).
  void expired() {
    if (state == null) return;
    endedMessage = 'The preview ended. Start it again from the Teacher area.';
    state = null;
  }
}

final previewProvider = NotifierProvider<PreviewController, PreviewSession?>(PreviewController.new);

/// Why LEA did what it did on the latest preview turns (newest first).
final previewExplainProvider = FutureProvider.autoDispose<List<PreviewTurn>>((ref) async {
  final session = ref.watch(previewProvider);
  if (session == null) return const [];
  final json = await ref.watch(apiClientProvider).get('/teach/courses/${session.course}/preview/explain');
  return [for (final t in json as List) PreviewTurn.fromJson(t as Map<String, dynamic>)];
});

/// Things to try in the selected week.
final previewProbesProvider = FutureProvider.autoDispose.family<List<Probe>, ({String course, int? week})>((
  ref,
  key,
) async {
  final json = await ref
      .watch(apiClientProvider)
      .get('/teach/courses/${key.course}/preview/probes', query: {if (key.week != null) 'week': '${key.week}'});
  return [for (final p in json as List) Probe.fromJson(p as Map<String, dynamic>)];
});
