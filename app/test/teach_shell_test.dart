import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:lea_app/screens/chat/chat_screen.dart';
import 'package:lea_app/screens/login/login_screen.dart';
import 'package:lea_app/screens/teach/courses_screen.dart';
import 'package:lea_app/teach/preview_panel.dart';

import 'helpers.dart';

FakeApi teacherApi({FakeTeach? teach}) => FakeApi()
  ..role = 'teacher'
  ..teach = teach ?? FakeTeach();

void go(WidgetTester tester, String location) => GoRouter.of(tester.element(find.byType(Navigator).first)).go(location);

String? location(WidgetTester tester) =>
    GoRouter.of(tester.element(find.byType(Navigator).first)).routeInformationProvider.value.uri.path;

void main() {
  testWidgets('students see no Teaching link and are sent back from /teach', (tester) async {
    await pumpLea(tester);
    expect(find.text('Teaching'), findsNothing);
    go(tester, '/teach');
    await tester.pumpAndSettle();
    expect(location(tester), '/chat');
    expect(find.byType(TeachCoursesScreen), findsNothing);
  });

  testWidgets('teachers reach their courses from the rail, and come back to learning', (tester) async {
    await pumpLea(tester, api: teacherApi());
    await tester.tap(find.text('Teaching'));
    await tester.pumpAndSettle();
    expect(location(tester), '/teach');
    expect(find.text('Your courses'), findsOneWidget);
    expect(find.text('AIML101'), findsWidgets);
    expect(find.text('Live'), findsOneWidget);
    await tester.tap(find.text('Back to learning'));
    await tester.pumpAndSettle();
    expect(find.byType(ChatScreen), findsOneWidget);
  });

  testWidgets('New course creates it and opens its setup', (tester) async {
    final api = teacherApi();
    await pumpLea(tester, api: api);
    go(tester, '/teach');
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'New course'));
    await tester.pumpAndSettle();

    await tester.tap(find.widgetWithText(FilledButton, 'Create course'));
    await tester.pumpAndSettle();
    expect(find.text('Course codes are 2-4 letters and 3 digits, like AIML101.'), findsOneWidget);

    await tester.enterText(find.byKey(const Key('course-code')), 'AIML101');
    await tester.enterText(find.byKey(const Key('course-name')), 'Cell Biology');
    await tester.tap(find.widgetWithText(FilledButton, 'Create course'));
    await tester.pumpAndSettle();
    expect(find.text('AIML101 already exists. Choose another code.'), findsOneWidget); // the API's message

    await tester.enterText(find.byKey(const Key('course-code')), 'bio210');
    await tester.tap(find.widgetWithText(FilledButton, 'Create course'));
    await tester.pumpAndSettle();
    expect(api.teach!.bodies['/teach/courses']!.whereType<Map>().last, {
      'code': 'BIO210',
      'name': 'Cell Biology',
      'discipline': 'computing',
      'allows_code': false,
      'code_language': null,
      'weeks': 6,
    });
    expect(location(tester), '/teach/courses/BIO210/setup');
  });

  testWidgets('a course in setup says students can\'t see it yet', (tester) async {
    final teach = FakeTeach(courses: [FakeTeach.course('BIO210', 'Cell Biology', managed: true)]);
    await pumpLea(tester, api: teacherApi(teach: teach));
    go(tester, '/teach');
    await tester.pumpAndSettle();
    expect(find.text('Setting up'), findsOneWidget);
    expect(find.textContaining("Students can't see this course"), findsOneWidget);
    expect(find.widgetWithText(FilledButton, 'Continue setup'), findsOneWidget);
  });

  group('try as a student', () {
    Future<FakeApi> startPreview(WidgetTester tester) async {
      final api = teacherApi();
      await pumpLea(tester, api: api, size: const Size(1400, 900));
      go(tester, '/teach');
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(OutlinedButton, 'Try as a student'));
      await tester.pumpAndSettle();
      return api;
    }

    testWidgets('the banner stays, student requests use the sandbox, /teach keeps the teacher', (tester) async {
      final api = await startPreview(tester);
      expect(find.byType(PreviewBar), findsOneWidget);
      expect(find.textContaining("your answers aren't recorded as student data"), findsOneWidget);
      expect(location(tester), '/tutor');
      final student = api.requests.where((r) => r.url.path == '/me/courses').last;
      expect(student.headers['Authorization'], 'Bearer preview-token-AIML101');
      expect(find.byType(ExplainPanel), findsOneWidget);
      expect(find.textContaining('the explanation appears here'), findsOneWidget);
      final explain = api.teach!.requests.where((r) => r.url.path.endsWith('/preview/explain')).last;
      expect(explain.headers['Authorization'], 'Bearer $validToken');
      expect(find.text('Teaching'), findsNothing); // the sandbox is a student
    });

    testWidgets('the explain panel shows the latest turn', (tester) async {
      final api = await startPreview(tester);
      api.teach!.explanations.add({
        'at': 'now',
        'course': 'AIML101',
        'mode': 'tutor',
        'go_id': 'GO_01_01_001',
        'objective': 'Define AI',
        'threshold': 0.7,
        'mastery_before': 0.42,
        'mastery_after': 0.31,
        'graded': true,
        'correct': false,
        'score': 0.2,
        'diagnostic': false,
        'advanced': false,
        'learner': {
          'zpd': 0.58,
          'cognitive_load': 0.47,
          'motivation': 'maintained_high',
          'scaffolding': 'procedural',
          'intensity': 'medium',
        },
        'sources': [
          {'source': 'Week01-LectureA-Notes.md', 'excerpt': 'AI is...'},
        ],
      });
      await tester.tap(find.byTooltip('Refresh'));
      await tester.pumpAndSettle();
      expect(find.text('Define AI (GO_01_01_001)'), findsOneWidget);
      expect(find.text('0.42 → 0.31 (threshold 0.70)'), findsOneWidget);
      expect(find.text('Incorrect · score 0.20'), findsOneWidget);
      expect(find.text('procedural · medium'), findsOneWidget);
      expect(find.text('Week01-LectureA-Notes.md'), findsOneWidget);
    });

    testWidgets('Back to teaching ends the preview', (tester) async {
      final api = await startPreview(tester);
      await tester.tap(find.widgetWithText(FilledButton, 'Back to teaching'));
      await tester.pumpAndSettle();
      expect(find.byType(PreviewBar), findsNothing);
      expect(location(tester), '/teach/courses/AIML101/objectives');
      go(tester, '/chat');
      await tester.pumpAndSettle();
      final student = api.requests.where((r) => r.url.path == '/me/courses').last;
      expect(student.headers['Authorization'], 'Bearer $validToken');
    });

    testWidgets('an expired sandbox ends the preview, not the teacher\'s login', (tester) async {
      final api = await startPreview(tester);
      api.previewExpired = true;
      await tester.tap(find.widgetWithText(FilledButton, 'Start Week 1'));
      await tester.pumpAndSettle();
      expect(find.byType(PreviewBar), findsNothing);
      expect(find.byType(LoginScreen), findsNothing);
      expect(api.requests.last.headers['Authorization'], 'Bearer $validToken'); // back to the teacher's own
    });
  });
}
