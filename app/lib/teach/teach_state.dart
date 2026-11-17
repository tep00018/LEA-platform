import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../providers.dart';
import 'teach_models.dart';

/// The Teacher area's sections and their paths.
enum TeachSection {
  courses('Courses'),
  setup('Setup and materials'),
  objectives('Objectives'),
  videos('Videos'),
  audit('Content audit'),
  analytics('Analytics'),
  admin('Users and owners');

  const TeachSection(this.label);

  final String label;

  String path([String? course]) => switch (this) {
    TeachSection.courses => '/teach',
    TeachSection.setup => '/teach/courses/$course/setup',
    TeachSection.objectives => '/teach/courses/$course/objectives',
    TeachSection.videos => '/teach/courses/$course/videos',
    TeachSection.audit => '/teach/courses/$course/audit',
    TeachSection.analytics => '/teach/courses/$course/analytics',
    TeachSection.admin => '/admin/users',
  };

  /// Sections that belong to one course.
  bool get perCourse => this == setup || this == objectives || this == videos || this == audit || this == analytics;

  /// The section and course for a location such as `/teach/courses/AIML101/objectives/review`.
  static (TeachSection, String?) fromLocation(String location) {
    if (location.startsWith('/admin')) return (TeachSection.admin, null);
    final m = RegExp(r'^/teach/courses/([^/]+)/(setup|objectives|videos|audit|analytics)').firstMatch(location);
    if (m == null) return (TeachSection.courses, null);
    final section = {
      'setup': TeachSection.setup,
      'objectives': TeachSection.objectives,
      'videos': TeachSection.videos,
      'audit': TeachSection.audit,
      'analytics': TeachSection.analytics,
    };
    return (section[m.group(2)]!, m.group(1));
  }
}

/// The courses the teacher owns (an admin: every course).
final teachCoursesProvider = FutureProvider.autoDispose<List<TeachCourse>>((ref) async {
  if (ref.watch(authProvider.select((s) => s.token)) == null) return const [];
  final json = await ref.watch(apiClientProvider).get('/teach/courses');
  return [for (final c in json as List) TeachCourse.fromJson(c as Map<String, dynamic>)];
});

/// One course's summary.
final teachCourseProvider = FutureProvider.autoDispose.family<TeachCourse, String>((ref, code) async {
  return TeachCourse.fromJson(await ref.watch(apiClientProvider).getObject('/teach/courses/$code'));
});

/// Sets up a course; returns its code. Throws [ApiError] for the form to show.
Future<String> createCourse(WidgetRef ref, CourseCreateRequest request) async {
  final json = await ref.read(apiClientProvider).postObject('/teach/courses', request.toJson());
  ref.invalidate(teachCoursesProvider);
  return json['code'] as String;
}
