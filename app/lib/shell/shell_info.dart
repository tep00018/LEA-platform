import '../api/models.dart';

/// Share of a week's objectives to master before the next week opens. The backend's
/// `ProgressIntegration.WEEK_COMPLETION_THRESHOLD` (0.75); the API doesn't expose it.
const weekUnlockPercent = 75;

/// What the shell shows about the course: the student's courses, the selected course,
/// its weeks, and the selected week's mastery count.
class ShellInfo {
  const ShellInfo({
    required this.courses,
    required this.course,
    required this.weeks,
    required this.currentWeek,
    required this.selectedWeek,
    required this.masteredCount,
    required this.total,
  });

  factory ShellInfo.from({
    required List<CourseInfo> courses,
    required CourseInfo course,
    required CourseOutline outline,
    required int currentWeek,
    required int selectedWeek,
    required int masteredCount,
    required int total,
  }) {
    return ShellInfo(
      courses: courses,
      course: course,
      currentWeek: currentWeek,
      selectedWeek: selectedWeek,
      masteredCount: masteredCount,
      total: total,
      weeks: [
        for (final w in outline.weeks)
          WeekSummary(
            number: w.number,
            topic: w.topic,
            locked: w.number > currentWeek,
            lockNote: w.number == currentWeek + 1
                ? 'Opens when $weekUnlockPercent% of Week $currentWeek is mastered'
                : null,
          ),
      ],
    );
  }

  final List<CourseInfo> courses;
  final CourseInfo course;
  final List<WeekSummary> weeks;

  /// The furthest week the student has reached; later weeks are locked.
  final int currentWeek;

  /// The week the modes work on.
  final int selectedWeek;
  final int masteredCount;
  final int total;

  WeekSummary get selected => weeks.firstWhere((w) => w.number == selectedWeek, orElse: () => weeks.first);

  /// "DEMO101 · Week 1 · Introduction to AI", under the mode title on narrow screens.
  String get subtitle => '${course.code} · Week ${selected.number} · ${selected.topic}';

  /// "2 / 11".
  String get count => '$masteredCount / $total';

  double get fraction => total == 0 ? 0 : masteredCount / total;
}

class WeekSummary {
  const WeekSummary({required this.number, required this.topic, this.locked = false, this.lockNote});

  final int number;
  final String topic;
  final bool locked;

  /// The unlock rule, shown under the week that opens next.
  final String? lockNote;

  String get label => 'Week $number · $topic';
}
