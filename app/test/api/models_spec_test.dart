import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:lea_app/api/models.dart';
import 'package:lea_app/teach/analytics_models.dart';
import 'package:lea_app/teach/teach_models.dart';
import 'package:lea_app/teach/video_models.dart';

/// Keeps the hand-written models in step with the API spec (`docs/api/openapi.json`).
void main() {
  final spec = jsonDecode(File('../docs/api/openapi.json').readAsStringSync()) as Map<String, dynamic>;
  final schemas = (spec['components'] as Map<String, dynamic>)['schemas'] as Map<String, dynamic>;

  Set<String> properties(String schema) =>
      ((schemas[schema] as Map<String, dynamic>)['properties'] as Map<String, dynamic>).keys.toSet();

  final models = <String, List<String>>{
    'UserProfile': UserProfile.fields,
    'LoginOut': LoginResult.fields,
    'CourseOut': CourseInfo.fields,
    'CourseOutline': CourseOutline.fields,
    'WeekOutline': WeekOutline.fields,
    'LearningObjectiveInfo': LearningObjectiveInfo.fields,
    'ProgressSummary': ProgressSummary.fields,
    'WeekMastery': WeekMastery.fields,
    'LearningObjectiveMastery': LearningObjectiveMastery.fields,
    'ObjectiveMastery': ObjectiveMastery.fields,
    'RegisterIn': RegisterRequest.fields,
    'ChatMessage': ChatMessage.fields,
    'ChatIn': ChatRequest.fields,
    'ChatReply': ChatReply.fields,
    'ObjectiveView': ObjectiveView.fields,
    'TutorMessageView': TutorMessage.fields,
    'TutorView': TutorView.fields,
    'TutorReplyOut': TutorReplyResult.fields,
    'TutorSummaryOut': TutorSummary.fields,
    'StartIn': ['course', 'week'],
    'TutorIn': ['text', 'timing'],
    'QuestionView': QuizQuestion.fields,
    'FeedbackView': QuizFeedback.fields,
    'QuizView': QuizView.fields,
    'AnswerIn': ['answer', 'timing'],
    'TeachCourseOut': TeachCourse.fields,
    'CourseCreateIn': CourseCreateRequest.fields,
    'WeekPlanOut': WeekPlan.fields,
    'WeekPlanIn': WeekPlan.fields,
    'UploadOut': CourseUpload.fields,
    'MaterialsSourceOut': MaterialsSource.fields,
    'MaterialsSourceIn': MaterialsSource.fields,
    'MaterialsFolderOut': MaterialsFolder.fields,
    'SyncPreviewEntryOut': SyncPreviewEntry.fields,
    'SyncPreviewOut': SyncPreview.fields,
    'CostEstimateOut': CostEstimate.fields,
    'JobOut': Job.fields,
    'KCRow': KCRow.fields,
    'KCIssue': KCIssue.fields,
    'DraftOut': KCDraft.fields,
    'KCOverviewOut': KCOverview.fields,
    'KCDiffOut': KCDiff.fields,
    'PreviewSessionOut': PreviewSession.fields,
    'PreviewTurnOut': PreviewTurn.fields,
    'ProbeOut': Probe.fields,
    'AuditFindingOut': AuditFinding.fields,
    'AuditRunOut': AuditRun.fields,
    'AdminUserOut': AdminUser.fields,
    'CurvePointOut': CurvePoint.fields,
    'AttentionOut': Attention.fields,
    'ObjectiveStatsOut': ObjectiveStats.fields,
    'UsageOut': Usage.fields,
    'AnalyticsOverviewOut': AnalyticsOverview.fields,
    'WrongAnswerOut': WrongAnswer.fields,
    'WrongAnswersOut': WrongAnswers.fields,
    'StruggleOut': Struggle.fields,
    'ChatTopicOut': ChatTopic.fields,
    'ObjectiveDetailOut': ObjectiveDetail.fields,
    'ChatTopicsResultOut': ChatTopicsResult.fields,
    'ChatTopicsOut': ChatTopicsStatus.fields,
    'ExplainerOut': Explainer.fields,
    'VideoOut': CuratedVideo.fields,
    'ObjectiveVideosOut': ObjectiveVideos.fields,
    'VideoSearchOut': VideoSearch.fields,
    'VideosOverviewOut': VideosOverview.fields,
  };

  for (final MapEntry(key: schema, value: fields) in models.entries) {
    test('$schema matches the spec', () {
      expect(fields.toSet(), properties(schema));
    });
  }

  test('models parse the spec-shaped JSON', () {
    final login = LoginResult.fromJson({
      'token': 't',
      'token_type': 'bearer',
      'expires_in': 43200,
      'user': {
        'username': 'alex.m',
        'full_name': 'Alex M.',
        'enrolled_courses': ['DEMO101'],
      },
    });
    expect(login.user.displayName, 'Alex M.');
    expect(login.user.initial, 'A');
    expect(login.user.enrolledCourses, ['DEMO101']);
    expect(UserProfile.fromJson({'username': 'sam'}).displayName, 'sam');
  });

  test('course and week titles drop the prefixes the API adds', () {
    const course = CourseInfo(code: 'DEMO101', name: 'DEMO101: Introduction to AI/ML');
    expect(course.title, 'Introduction to AI/ML');
    expect(course.label, 'DEMO101 · Introduction to AI/ML');
    expect(const CourseInfo(code: 'BIO2', name: 'Cell Biology').label, 'BIO2 · Cell Biology');

    const week = WeekOutline(number: 1, title: 'Week 1: Introduction to AI', learningObjectives: [], conceptCount: 0);
    expect(week.topic, 'Introduction to AI');
    expect(week.label, 'Week 1 · Introduction to AI');
    expect(
      const WeekOutline(number: 2, title: 'Loops', learningObjectives: [], conceptCount: 0).label,
      'Week 2 · Loops',
    );
  });

  test('mastery is null until graded', () {
    final m = ObjectiveMastery.fromJson({
      'go_id': 'GO1',
      'skill_name': 'Defining AI',
      'mastery': null,
      'threshold': 0.6,
      'mastered': false,
    });
    expect(m.mastery, isNull);
    expect(m.threshold, 0.6);
  });
}
