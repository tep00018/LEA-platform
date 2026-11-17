import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:lea_app/screens/teach/objectives_screen.dart';
import 'package:lea_app/teach/download_stub.dart' show savedFiles;

import 'helpers.dart';

const wide = Size(1300, 1000);

FakeApi kcApi({List<Map<String, dynamic>>? courses}) => FakeApi()
  ..role = 'teacher'
  ..teach = FakeTeach(courses: courses);

Future<FakeApi> openObjectives(
  WidgetTester tester, {
  FakeApi? api,
  Size size = wide,
  String path = '/teach/courses/AIML101/objectives',
  List<int>? importBytes,
}) async {
  final fake = api ?? kcApi();
  await pumpLea(
    tester,
    api: fake,
    size: size,
    overrides: [
      spreadsheetPickerProvider.overrideWithValue(
        () async => importBytes == null ? null : (name: 'kc.xlsx', bytes: importBytes),
      ),
    ],
  );
  GoRouter.of(tester.element(find.byType(Navigator).first)).go(path);
  await tester.pumpAndSettle();
  return fake;
}

String location(WidgetTester tester) =>
    GoRouter.of(tester.element(find.byType(Navigator).first)).routeInformationProvider.value.uri.toString();

Future<void> startDraft(WidgetTester tester) async {
  await tester.tap(find.widgetWithText(FilledButton, 'Edit the live objectives'));
  await tester.pumpAndSettle();
}

Future<void> setThreshold(WidgetTester tester, String row, String value) async {
  await tester.tap(find.text(row).first);
  await tester.pumpAndSettle();
  await tester.enterText(find.byKey(const Key('row-threshold')), value);
  await tester.ensureVisible(find.widgetWithText(FilledButton, 'Apply'));
  await tester.pumpAndSettle();
  await tester.tap(find.widgetWithText(FilledButton, 'Apply'));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('a live course starts a draft; rows show IDs, Bloom, threshold and content match', (tester) async {
    final api = await openObjectives(tester);
    expect(find.text('Objectives: version 1 (live)'), findsOneWidget);
    expect(find.textContaining('Students keep version 1 until you publish'), findsOneWidget);
    await startDraft(tester);
    expect(api.teach!.bodies['/teach/courses/AIML101/kc/draft']!.whereType<Map>().last, {
      'source': 'published',
      'replace': false,
    });
    expect(find.text('Objectives: draft'), findsOneWidget);
    expect(find.text('Define AI'), findsOneWidget);
    expect(find.text('GO_01_01_001'), findsOneWidget);
    expect(find.text('0.70'), findsWidgets);
    await tester.tap(find.text('Week 2'));
    await tester.pumpAndSettle();
    expect(find.text('▲ Weak support'), findsOneWidget);
    expect(find.textContaining('An excerpt about Linear separability'), findsOneWidget);
    expect(find.textContaining('Weak support in the course content.'), findsOneWidget); // a warning in Checks
  });

  testWidgets('edits are applied, saved (or refused with the reason), reviewed and published', (tester) async {
    final api = await openObjectives(tester);
    await startDraft(tester);
    await setThreshold(tester, 'Turing test', '0.99');
    expect(find.textContaining('unsaved changes'), findsOneWidget);
    await tester.tap(find.widgetWithText(FilledButton, 'Save draft'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Mastery threshold must be 0.5 to 0.95'), findsWidgets);

    await setThreshold(tester, 'Turing test', '0.8');
    await tester.tap(find.widgetWithText(FilledButton, 'Save draft'));
    await tester.pumpAndSettle();
    expect(find.textContaining('1 save'), findsOneWidget);

    await tester.tap(find.widgetWithText(FilledButton, 'Review changes'));
    await tester.pumpAndSettle();
    expect(location(tester), '/teach/courses/AIML101/objectives/review');
    expect(find.text('Publish version 2?'), findsOneWidget);
    expect(find.text('GO_01_01_002'), findsOneWidget);
    expect(find.text('mastery threshold: 0.75 → 0.8'), findsOneWidget);
    expect(find.textContaining('Research note.'), findsOneWidget);
    await tester.enterText(find.byKey(const Key('publish-note')), 'Raise the Turing test bar');
    await tester.tap(find.widgetWithText(FilledButton, 'Publish version 2'));
    await tester.pumpAndSettle();
    expect(find.text('Version 2 is live'), findsOneWidget);
    expect(api.teach!.bodies['/teach/courses/AIML101/kc/publish']!.last, {'note': 'Raise the Turing test bar'});
  });

  testWidgets('add, split and remove objectives; LEA assigns the new IDs', (tester) async {
    final api = await openObjectives(tester);
    await startDraft(tester);
    await tester.tap(find.text('+ Add objective'));
    await tester.pumpAndSettle();
    expect(find.text('New objective'), findsWidgets); // in the table and its details
    expect(find.text('new · ID when saved'), findsOneWidget);

    await tester.tap(find.text('Define AI').first);
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.widgetWithText(OutlinedButton, 'Split in two'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(OutlinedButton, 'Split in two'));
    await tester.pumpAndSettle();
    expect(find.text('Define AI (part 1)'), findsWidgets);
    expect(find.text('Split from GO_01_01_001'), findsNWidgets(2));

    await tester.tap(find.text('Turing test').first);
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.widgetWithText(OutlinedButton, 'Remove'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(OutlinedButton, 'Remove'));
    await tester.pumpAndSettle();
    expect(find.text('Turing test'), findsNothing);

    await tester.tap(find.widgetWithText(FilledButton, 'Save draft'));
    await tester.pumpAndSettle();
    final rows = (api.teach!.bodies['/teach/courses/AIML101/kc/draft']!.whereType<Map>().last['rows'] as List)
        .cast<Map<String, dynamic>>();
    expect(rows.where((r) => r['split_from'] == 'GO_01_01_001'), hasLength(2));
    expect(rows.where((r) => r['go_id'] == null), hasLength(3)); // two parts and the new one: IDs come from LEA
    expect(find.text('new · ID when saved'), findsNothing);
  });

  testWidgets('two objectives merge into one', (tester) async {
    final api = await openObjectives(tester);
    await startDraft(tester);
    await tester.tap(find.text('Merge…'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(CheckboxListTile, 'Define AI'));
    await tester.tap(find.widgetWithText(CheckboxListTile, 'Turing test'));
    await tester.enterText(find.byKey(const Key('merge-name')), 'What AI is');
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Merge'));
    await tester.pumpAndSettle();
    expect(find.text('What AI is'), findsWidgets);
    expect(find.text('Merged from 2'), findsOneWidget);
    await tester.tap(find.widgetWithText(FilledButton, 'Save draft'));
    await tester.pumpAndSettle();
    final rows = (api.teach!.bodies['/teach/courses/AIML101/kc/draft']!.whereType<Map>().last['rows'] as List)
        .cast<Map<String, dynamic>>();
    expect(rows.firstWhere((r) => r['skill_name'] == 'What AI is')['merged_from'], ['GO_01_01_001', 'GO_01_01_002']);
  });

  testWidgets('Excel export downloads the sheet; import goes to review', (tester) async {
    savedFiles.clear();
    await openObjectives(tester, importBytes: utf8.encode('xlsx'));
    await tester.tap(find.widgetWithText(OutlinedButton, 'Export to Excel'));
    await tester.pumpAndSettle();
    expect(savedFiles.keys, ['AIML101_kc_model.xlsx']);
    await startDraft(tester);
    await tester.tap(find.widgetWithText(OutlinedButton, 'Import'));
    await tester.pumpAndSettle();
    expect(location(tester), '/teach/courses/AIML101/objectives/review');
    expect(find.text('mastery threshold: 0.7 → 0.9'), findsOneWidget);
  });

  testWidgets("after a build, the build's draft is offered", (tester) async {
    final api = await openObjectives(
      tester,
      api: kcApi(courses: [FakeTeach.course('BIO210', 'Cell Biology', managed: true)]),
      path: '/teach/courses/BIO210/objectives?from=job:job1',
    );
    expect(find.textContaining('Build the course from its materials'), findsOneWidget);
    await tester.tap(find.widgetWithText(FilledButton, "Review the build's draft"));
    await tester.pumpAndSettle();
    expect(api.teach!.bodies['/teach/courses/BIO210/kc/draft']!.whereType<Map>().last['source'], 'job:job1');
    expect(find.text('Objectives: draft'), findsOneWidget);
    expect(find.textContaining('New model'), findsOneWidget);
  });

  testWidgets('discarding asks first', (tester) async {
    await openObjectives(tester);
    await startDraft(tester);
    await tester.tap(find.widgetWithText(OutlinedButton, 'Discard draft'));
    await tester.pumpAndSettle();
    expect(find.text('Discard the draft?'), findsOneWidget);
    await tester.tap(find.widgetWithText(FilledButton, 'Discard'));
    await tester.pumpAndSettle();
    expect(find.text('Objectives: version 1 (live)'), findsOneWidget);
  });

  testWidgets('on a phone the objectives are read-only', (tester) async {
    final api = kcApi();
    api.teach!.drafts['AIML101'] = {
      'course': 'AIML101',
      'source': 'published',
      'based_on': 1,
      'created_by': 'x',
      'created_at': 'now',
      'updated_by': 'x',
      'updated_at': 'now',
      'saves': 0,
      'rows': FakeTeach.kcRows(),
      'issues': <Object>[],
    };
    await openObjectives(tester, api: api, size: phone);
    expect(find.textContaining('Open LEA on a computer to edit'), findsOneWidget);
    await tester.tap(find.text('Define AI').first);
    await tester.pumpAndSettle();
    expect(find.widgetWithText(FilledButton, 'Apply'), findsNothing);
    expect(find.text('+ Add objective'), findsNothing);
  });
}
