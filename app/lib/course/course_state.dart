import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/models.dart';
import '../providers.dart';
import '../shell/shell_info.dart';

/// The session (login, or a teacher's preview), so API-backed providers reload when a
/// different student logs in or a preview starts or ends.
final _session = Provider<String?>((ref) => ref.watch(sessionProvider));

/// Thrown instead of calling the API when nobody is logged in (e.g. just after logging out,
/// while the screens that watched these providers are closing).
class SignedOut implements Exception {
  const SignedOut();
}

/// Watches the session; throws [SignedOut] when there is none.
void _requireSession(Ref ref) {
  if (ref.watch(_session) == null) throw const SignedOut();
}

/// Courses open for registration (`GET /courses`, no login needed).
final availableCoursesProvider = FutureProvider.autoDispose<List<CourseInfo>>((ref) async {
  final json = await ref.watch(apiClientProvider).get('/courses');
  return [for (final c in json as List) CourseInfo.fromJson(c as Map<String, dynamic>)];
});

/// The student's courses (`GET /me/courses`).
final myCoursesProvider = FutureProvider<List<CourseInfo>>((ref) async {
  _requireSession(ref);
  final json = await ref.watch(apiClientProvider).get('/me/courses');
  return [for (final c in json as List) CourseInfo.fromJson(c as Map<String, dynamic>)];
});

/// Enrolls yourself in one more course (`POST /me/courses`); throws [ApiError] for the
/// caller to show. Idempotent.
Future<void> addMyCourse(WidgetRef ref, String code) async {
  await ref.read(apiClientProvider).post('/me/courses', {'code': code});
  ref.invalidate(myCoursesProvider);
}

/// Un-enrols yourself from a course (`DELETE /me/courses/{code}`). Your progress in it
/// isn't deleted.
Future<void> removeMyCourse(WidgetRef ref, String code) async {
  await ref.read(apiClientProvider).delete('/me/courses/$code');
  ref.invalidate(myCoursesProvider);
}

final outlineProvider = FutureProvider.family<CourseOutline, String>((ref, code) async {
  _requireSession(ref);
  return CourseOutline.fromJson(await ref.watch(apiClientProvider).getObject('/courses/$code/outline'));
});

final progressProvider = FutureProvider.family<ProgressSummary, String>((ref, code) async {
  _requireSession(ref);
  return ProgressSummary.fromJson(await ref.watch(apiClientProvider).getObject('/courses/$code/progress'));
});

final weekMasteryProvider = FutureProvider.family<WeekMastery, ({String course, int week})>((ref, key) async {
  _requireSession(ref);
  return WeekMastery.fromJson(
    await ref.watch(apiClientProvider).getObject('/courses/${key.course}/mastery', query: {'week': '${key.week}'}),
  );
});

/// What the student picked. Null means "the default": their first course, and the
/// course's current week from `GET /courses/{code}/progress`.
class CourseSelection {
  const CourseSelection({this.course, this.week});

  final String? course;
  final int? week;
}

class SelectionController extends Notifier<CourseSelection> {
  @override
  CourseSelection build() {
    ref.watch(_session); // A new login starts from the defaults.
    return const CourseSelection();
  }

  /// A new course starts on its current week.
  void selectCourse(String code) => state = CourseSelection(course: code);

  void selectWeek(int week) => state = CourseSelection(course: state.course, week: week);
}

final selectionProvider = NotifierProvider<SelectionController, CourseSelection>(SelectionController.new);

/// The student has no courses to study.
class NoCoursesError implements Exception {
  const NoCoursesError();

  String get message => "You're not enrolled in a course yet. Ask your course tutor to add you.";
}

/// The course, weeks and counts the shell shows, for the selected course and week.
final shellInfoProvider = FutureProvider<ShellInfo>((ref) async {
  final courses = await ref.watch(myCoursesProvider.future);
  if (courses.isEmpty) throw const NoCoursesError();

  final selection = ref.watch(selectionProvider);
  final course = courses.firstWhere((c) => c.code == selection.course, orElse: () => courses.first);

  final outlineFuture = ref.watch(outlineProvider(course.code).future);
  final progressFuture = ref.watch(progressProvider(course.code).future);
  final (outline, progress) = await (outlineFuture, progressFuture).wait;
  if (outline.weeks.isEmpty) throw const NoCoursesError();

  final current = progress.currentWeek.clamp(outline.weeks.first.number, outline.weeks.last.number);
  final picked = selection.week;
  // Only the current week and earlier ones can be picked; anything else falls back.
  final selected = (picked != null && picked <= current && outline.week(picked) != null) ? picked : current;

  final mastery = await ref.watch(weekMasteryProvider((course: course.code, week: selected)).future);

  return ShellInfo.from(
    courses: courses,
    course: course,
    outline: outline,
    currentWeek: current,
    selectedWeek: selected,
    masteredCount: mastery.masteredCount,
    total: mastery.total,
  );
});

/// Reloads progress and mastery, e.g. after a quiz or tutor session moved them on.
void refreshProgress(WidgetRef ref, String course) {
  ref.invalidate(progressProvider(course));
  ref.invalidate(weekMasteryProvider);
}
