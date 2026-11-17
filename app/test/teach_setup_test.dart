import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:lea_app/teach/setup_state.dart';
import 'package:lea_app/teach/teach_widgets.dart';

import 'helpers.dart';

const wide = Size(1300, 900);

FakeApi setupApi({bool managed = true}) => FakeApi()
  ..role = 'teacher'
  ..teach = FakeTeach(courses: [FakeTeach.course('BIO210', 'Cell Biology', managed: managed)]);

Future<FakeApi> openSetup(WidgetTester tester, {FakeApi? api, Size size = wide, List<PickedFile>? pick}) async {
  final fake = api ?? setupApi();
  await pumpLea(
    tester,
    api: fake,
    size: size,
    overrides: [filePickerProvider.overrideWithValue(() async => pick ?? const [])],
  );
  GoRouter.of(tester.element(find.byType(Navigator).first)).go('/teach/courses/BIO210/setup');
  await tester.pumpAndSettle();
  return fake;
}

PickedFile file(String name) => (name: name, bytes: utf8.encode('# $name'));

Future<void> uploadWithWeek(WidgetTester tester, int week) async {
  await tester.tap(find.widgetWithText(FilledButton, 'Upload files'));
  await tester.pumpAndSettle();
  await tester.tap(find.text('No week yet'));
  await tester.pumpAndSettle();
  await tester.tap(find.text('Week $week').last);
  await tester.pumpAndSettle();
  await tester.tap(find.widgetWithText(FilledButton, 'Upload'));
  await tester.pumpAndSettle();
}

Future<void> addObjectives(WidgetTester tester, {bool emptyWeek2 = false}) async {
  await tester.tap(find.widgetWithText(TextButton, 'Add'));
  await tester.pumpAndSettle();
  await tester.enterText(find.byKey(const Key('week-1-title')), 'The cell');
  await tester.enterText(
    find.byKey(const Key('week-1-objectives')),
    'Describe the parts of a cell\nExplain what membranes do',
  );
  await tester.enterText(find.byKey(const Key('week-2-title')), 'Energy');
  if (!emptyWeek2) await tester.enterText(find.byKey(const Key('week-2-objectives')), 'Explain how cells make energy');
  await tester.tap(find.widgetWithText(FilledButton, 'Save objectives'));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('uploads go up with their week and show in the list', (tester) async {
    final api = await openSetup(tester, pick: [file('Lecture 1.md'), file('Reading.md')]);
    expect(find.textContaining('No files yet'), findsOneWidget);
    await uploadWithWeek(tester, 1);
    expect(find.text('Lecture 1.md'), findsOneWidget);
    expect(find.text('Reading.md'), findsOneWidget);
    final upload = api.teach!.requests
        .where((r) => r.url.path == '/teach/courses/BIO210/uploads' && r.method == 'POST')
        .single;
    expect(upload.headers['Authorization'], 'Bearer $validToken');
    expect(api.teach!.uploads['BIO210']!.map((u) => u['week']), [1, 1]);

    await tester.tap(find.byTooltip('Delete Reading.md'));
    await tester.pumpAndSettle();
    expect(find.text('Reading.md'), findsNothing);
  });

  testWidgets('a refused file shows why', (tester) async {
    await openSetup(tester, pick: [file('run.exe')]);
    await uploadWithWeek(tester, 1);
    expect(find.textContaining('LEA takes PDF, Word, PowerPoint'), findsOneWidget);
  });

  testWidgets('weekly objectives are entered per week, one per line', (tester) async {
    final api = await openSetup(tester);
    await addObjectives(tester, emptyWeek2: true);
    expect(find.text('Week 2 needs 1 to 12 learning objectives.'), findsOneWidget); // the API's message, in the editor
    await tester.enterText(find.byKey(const Key('week-2-objectives')), 'Explain how cells make energy');
    await tester.tap(find.widgetWithText(FilledButton, 'Save objectives'));
    await tester.pumpAndSettle();
    final body = api.teach!.bodies['/teach/courses/BIO210/objectives']!.whereType<Map>().last;
    expect(body['weeks'], [
      {
        'week': 1,
        'title': 'The cell',
        'objectives': ['Describe the parts of a cell', 'Explain what membranes do'],
      },
      {
        'week': 2,
        'title': 'Energy',
        'objectives': ['Explain how cells make energy'],
      },
    ]);
    expect(find.text('Week 1 · The cell'), findsNothing); // shown as rich text
    expect(find.textContaining('2 objectives'), findsOneWidget);
  });

  testWidgets('a build is priced first, runs only when started, and can be cancelled', (tester) async {
    final api = await openSetup(tester, pick: [file('Lecture 1.md')]);
    expect(tester.widget<FilledButton>(find.widgetWithText(FilledButton, 'Price a build')).onPressed, isNull);
    await uploadWithWeek(tester, 1);
    await addObjectives(tester);

    await tester.tap(find.widgetWithText(FilledButton, 'Price a build'));
    await tester.pumpAndSettle();
    expect(find.text('Waiting for you'), findsOneWidget);
    expect(find.text('Chunking and embedding'), findsOneWidget);
    expect(find.text('\$0.30'), findsOneWidget);
    expect(find.text('\$0.41'), findsOneWidget);
    expect(find.textContaining('transcribed on this PC'), findsOneWidget);
    expect(api.teach!.jobs['job1']!['status'], 'awaiting_confirmation'); // nothing runs yet

    await tester.tap(find.widgetWithText(FilledButton, 'Start build · \$0.41'));
    await tester.pumpAndSettle();
    expect(api.teach!.jobs['job1']!['status'], 'queued');
    expect(find.text('Waiting to start'), findsOneWidget);
    await tester.tap(find.widgetWithText(OutlinedButton, 'Cancel after this file'));
    await tester.pumpAndSettle();
    expect(api.teach!.jobs['job1']!['status'], 'cancelled');
    expect(find.text('Cancelled'), findsOneWidget);
  });

  testWidgets('a running build shows its step, progress and log; a finished one leads to review', (tester) async {
    final api = setupApi();
    api.teach!.courses.first['active_job'] = 'job9';
    api.teach!.jobs['job9'] = api.teach!.job('job9', 'BIO210', status: 'running')
      ..['step'] = 'embed'
      ..['step_label'] = 'Chunking and embedding'
      ..['percent'] = 40
      ..['log'] = ['10:44:02 Week01-LectureA-The-Cell.pptx', '10:44:19   Added 22 chunks'];
    await openSetup(tester, api: api);
    expect(find.text('Running'), findsOneWidget);
    expect(find.text('40%'), findsOneWidget);
    expect(find.textContaining('Added 22 chunks'), findsOneWidget);

    api.teach!.jobs['job9']!
      ..['status'] = 'succeeded'
      ..['percent'] = 100
      ..['result'] = {
        'verify': {
          'objectives': 12,
          'weak_support': ['GO_01_01_002'],
        },
      };
    await tester.pump(const Duration(seconds: 3)); // the card polls a running job
    await tester.pumpAndSettle();
    expect(find.textContaining('Draft ready: 12 objectives drafted, 1 with weak support'), findsOneWidget);
    await tester.tap(find.widgetWithText(FilledButton, 'Review the objectives'));
    await tester.pumpAndSettle();
    expect(
      GoRouter.of(tester.element(find.byType(Navigator).first)).routeInformationProvider.value.uri.toString(),
      '/teach/courses/BIO210/objectives?from=job:job9',
    );
  });

  testWidgets('on a phone setup is read-only', (tester) async {
    await openSetup(tester, size: phone);
    expect(find.textContaining('Open LEA on a computer to edit'), findsOneWidget);
    expect(find.widgetWithText(FilledButton, 'Upload files'), findsNothing);
    expect(find.widgetWithText(FilledButton, 'Price a build'), findsNothing);
  });

  testWidgets('a course set up by hand has no uploads here', (tester) async {
    await openSetup(tester, api: setupApi(managed: false));
    expect(find.textContaining('set up by hand'), findsOneWidget);
    expect(find.text('Materials'), findsNothing);
  });

  group('linked materials', () {
    testWidgets('linking a folder shows the sync preview, then Unlink clears it', (tester) async {
      final api = setupApi();
      api.teach!
        ..materialsFolders = ['AIML101', 'BIO210']
        ..syncPreviewEntries['BIO210'] = [
          {'relpath': 'chapter_01.md', 'name': 'chapter_01.md', 'size': 1200, 'status': 'new', 'reason': null},
          {
            'relpath': 'video.mov',
            'name': 'video.mov',
            'size': 0,
            'status': 'rejected',
            'reason': 'not a file type LEA accepts',
          },
        ]
        ..uploads['BIO210'] = [
          {
            'name': 'chapter_01.md',
            'size': 1200,
            'sha256': 'x',
            'week': null,
            'kind': null,
            'uploaded_by': 'alex.m',
            'uploaded_at': 'now',
            'linked_relpath': 'chapter_01.md',
          },
        ];
      final fake = await openSetup(tester, api: api);
      expect(find.text('Linked materials'), findsOneWidget);
      expect(find.text('Link'), findsOneWidget);

      await tester.tap(find.widgetWithText(FilledButton, 'Link'));
      await tester.pumpAndSettle();

      expect(fake.teach!.materialsSources['BIO210'], {'type': 'folder', 'path': 'BIO210'});
      expect(find.text('BIO210'), findsWidgets); // the linked path, shown in mono
      expect(find.text('1 new'), findsOneWidget);
      expect(find.text('1 rejected'), findsOneWidget);
      expect(find.text('not a file type LEA accepts'), findsOneWidget);
      expect(find.text('Linked'), findsOneWidget); // the badge on the uploaded row

      await tester.tap(find.widgetWithText(DangerButton, 'Unlink'));
      await tester.pumpAndSettle();
      expect(fake.teach!.materialsSources['BIO210'], isNull);
      expect(find.text('Link'), findsOneWidget);
    });

    testWidgets('picks the folder matching the course code by default', (tester) async {
      final api = setupApi();
      api.teach!.materialsFolders = ['AIML101', 'BIO210', 'PSYC101'];
      await openSetup(tester, api: api);
      expect(find.text('BIO210'), findsOneWidget); // the dropdown's selected value
    });
  });
}
