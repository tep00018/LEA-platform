import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../providers.dart';
import 'analytics_models.dart';

/// Which students the screens show: real (default) or simulated; never mixed.
class AnalyticsKind extends Notifier<String> {
  @override
  String build() => 'real';

  void set(String kind) => state = kind;
}

final analyticsKindProvider = NotifierProvider<AnalyticsKind, String>(AnalyticsKind.new);

/// The week filter (null: every week).
class AnalyticsWeek extends Notifier<int?> {
  @override
  int? build() => null;

  void set(int? week) => state = week;
}

final analyticsWeekProvider = NotifierProvider<AnalyticsWeek, int?>(AnalyticsWeek.new);

/// The date-range filter, in days back from today (null: all time).
class AnalyticsDays extends Notifier<int?> {
  @override
  int? build() => null;

  void set(int? days) => state = days;
}

final analyticsDaysProvider = NotifierProvider<AnalyticsDays, int?>(AnalyticsDays.new);

String _base(String code) => '/teach/courses/$code/analytics';

String _date(DateTime d) => d.toIso8601String().substring(0, 10);

final analyticsOverviewProvider = FutureProvider.autoDispose.family<AnalyticsOverview, String>((ref, code) async {
  final kind = ref.watch(analyticsKindProvider);
  final week = ref.watch(analyticsWeekProvider);
  final days = ref.watch(analyticsDaysProvider);
  final json = await ref
      .watch(apiClientProvider)
      .getObject(
        _base(code),
        query: {
          'kind': kind,
          if (week != null) 'week': '$week',
          if (days != null) 'since': _date(DateTime.now().toUtc().subtract(Duration(days: days))),
        },
      );
  return AnalyticsOverview.fromJson(json);
});

final objectiveDetailProvider = FutureProvider.autoDispose.family<ObjectiveDetail, (String, String)>((ref, key) async {
  final (code, go) = key;
  final json = await ref
      .watch(apiClientProvider)
      .getObject('${_base(code)}/objectives/$go', query: {'kind': ref.watch(analyticsKindProvider)});
  return ObjectiveDetail.fromJson(json);
});

final chatTopicsProvider = FutureProvider.autoDispose.family<ChatTopicsStatus, String>((ref, code) async {
  final json = await ref
      .watch(apiClientProvider)
      .getObject('${_base(code)}/chat-topics', query: {'kind': ref.watch(analyticsKindProvider)});
  return ChatTopicsStatus.fromJson(json);
});

/// Groups the chat questions by topic (costs a little; the screen says how much first).
/// Throws [ApiError] for the screen to show.
Future<void> runChatTopics(WidgetRef ref, String code) async {
  final kind = ref.read(analyticsKindProvider);
  await ref.read(apiClientProvider).postObject('${_base(code)}/chat-topics?kind=$kind');
  ref.invalidate(chatTopicsProvider(code));
  ref.invalidate(objectiveDetailProvider);
  ref.invalidate(analyticsOverviewProvider(code));
}

/// The aggregated learning curves as CSV bytes.
Future<List<int>> curvesCsv(WidgetRef ref, String code) =>
    ref.read(apiClientProvider).getBytes('${_base(code)}/curves.csv?kind=${ref.read(analyticsKindProvider)}');

/// A drafted explanation for the teacher to edit (never published by LEA).
Future<Explainer> draftExplainer(WidgetRef ref, String code, String go) async =>
    Explainer.fromJson(await ref.read(apiClientProvider).postObject('${_base(code)}/objectives/$go/explainer'));
