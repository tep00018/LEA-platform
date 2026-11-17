import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:lea_app/teach/download_stub.dart';
import 'package:lea_app/teach/teach_widgets.dart';

import 'helpers.dart';

const wide = Size(1300, 1000);

Future<FakeApi> open(WidgetTester tester, String path, {Size size = wide}) async {
  final api = FakeApi()
    ..role = 'teacher'
    ..teach = FakeTeach();
  await pumpLea(tester, api: api, size: size);
  GoRouter.of(tester.element(find.byType(Navigator).first)).go(path);
  await tester.pumpAndSettle();
  return api;
}

String location(WidgetTester tester) =>
    GoRouter.of(tester.element(find.byType(Navigator).first)).routeInformationProvider.value.uri.path;

Future<void> choose(WidgetTester tester, String current, String option) async {
  await tester.tap(find.text(current));
  await tester.pumpAndSettle();
  await tester.tap(find.text(option).last, warnIfMissed: false);
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('real students by default: fewer than 5 shows nothing but "not enough evidence"', (tester) async {
    final api = await open(tester, '/teach/courses/AIML101/analytics');
    expect(find.descendant(of: find.byType(TeachHeader), matching: find.text('Objectives')), findsOneWidget);
    expect(find.textContaining('Analytics start at 5 students · real sessions only'), findsOneWidget);
    expect(find.textContaining('Not enough students yet: analytics start at 5'), findsOneWidget);
    expect(find.text('Not enough evidence'), findsNWidgets(2));
    expect(find.text('< 5'), findsNWidgets(2));
    expect(find.text('0.38'), findsNothing);
    final asked = api.teach!.requests.where((r) => r.url.path.endsWith('/analytics'));
    expect(asked.every((r) => r.url.queryParameters['kind'] == 'real'), isTrue);
    // Nothing to export yet.
    final export = tester.widget<OutlinedButton>(find.widgetWithText(OutlinedButton, 'Export curves (CSV)'));
    expect(export.onPressed, isNull);
  });

  testWidgets('simulated students: bands, attention with its driver, usage last, CSV export', (tester) async {
    final api = await open(tester, '/teach/courses/AIML101/analytics');
    await choose(tester, 'Real students', 'Simulated students');
    expect(find.textContaining('42 students · simulated students only · version 1'), findsOneWidget);
    expect(find.textContaining('Simulated students: seeded data'), findsOneWidget);
    expect(find.text('Struggling'), findsOneWidget);
    expect(find.text('Mastered'), findsOneWidget);
    expect(find.text('High: a flat learning curve'), findsOneWidget);
    expect(find.text('0.38'), findsOneWidget);
    expect(find.text('7.2'), findsOneWidget);
    expect(find.text('Not enough students yet'), findsOneWidget); // the week 2 objective
    await tester.dragUntilVisible(find.text('214'), find.byType(ListView), const Offset(0, -200));
    expect(find.text('214'), findsOneWidget);
    expect(find.text('61 h'), findsOneWidget);
    // The most in need comes first.
    expect(
      tester.getTopLeft(find.byKey(const Key('objective-GO_01_01_001'))).dy,
      lessThan(tester.getTopLeft(find.byKey(const Key('objective-GO_01_01_002'))).dy),
    );

    await tester.drag(find.byType(ListView), const Offset(0, 600));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(OutlinedButton, 'Export curves (CSV)'));
    await tester.pumpAndSettle();
    expect(savedFiles.keys, contains('AIML101_learning_curves.csv'));
    expect(api.teach!.requests.last.url.queryParameters['kind'], 'simulated');

    await choose(tester, 'All weeks', 'Week 2');
    expect(find.text('Objectives in week 2'), findsOneWidget);
    expect(find.byKey(const Key('objective-GO_01_01_001')), findsNothing);
    expect(api.teach!.requests.last.url.queryParameters['week'], '2');
  });

  testWidgets('objective detail: curve, wrong answers, struggle, suggestion', (tester) async {
    await open(tester, '/teach/courses/AIML101/analytics');
    await choose(tester, 'Real students', 'Simulated students');
    await tester.tap(find.byKey(const Key('objective-GO_01_01_001')));
    await tester.pumpAndSettle();
    expect(location(tester), '/teach/courses/AIML101/analytics/GO_01_01_001');
    expect(find.text('Implement gradient descent'), findsOneWidget);
    expect(find.textContaining('31 students · 217 graded attempts · simulated'), findsOneWidget);
    expect(find.textContaining("Flat at about 60%: practice isn't reducing errors."), findsOneWidget);
    expect(
      find.textContaining('of wrong answers: subtract the gradient from the loss', findRichText: true),
      findsOneWidget,
    );
    expect(find.text('9 students (29%)'), findsOneWidget);
    expect(find.text('5 sessions'), findsOneWidget);
    expect(find.text('LEA suggestion'), findsOneWidget);

    await tester.tap(find.widgetWithText(OutlinedButton, 'Edit note'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('suggestion-note')), 'Add a worked example in week 2.');
    await tester.tap(find.widgetWithText(FilledButton, 'Save'));
    await tester.pumpAndSettle();
    expect(find.text('Your note'), findsOneWidget);
    expect(find.text('Add a worked example in week 2.'), findsOneWidget);
    await tester.tap(find.widgetWithText(OutlinedButton, 'Dismiss'));
    await tester.pumpAndSettle();
    expect(find.text('Suggested action'), findsNothing);
  });

  testWidgets('chat topics are grouped on request, with the cost and agreement shown', (tester) async {
    final api = await open(tester, '/teach/courses/AIML101/analytics');
    await choose(tester, 'Real students', 'Simulated students');
    await tester.tap(find.byKey(const Key('objective-GO_01_01_001')));
    await tester.pumpAndSettle();
    expect(find.textContaining('haven’t been grouped by topic yet'), findsOneWidget);
    final run = find.widgetWithText(OutlinedButton, 'Group chat questions · ≈ \$0.004');
    await tester.ensureVisible(run);
    await tester.tap(run);
    await tester.pumpAndSettle();
    expect(api.teach!.chatGrouped, isTrue);
    expect(find.textContaining('Why do we subtract the gradient?', findRichText: true), findsOneWidget);
    expect(find.textContaining('· 11 students', findRichText: true), findsOneWidget);
    expect(find.textContaining('Two independent passes agreed on 87%'), findsOneWidget);
  });

  testWidgets('draft an explainer: a draft for the teacher, never published', (tester) async {
    final api = await open(tester, '/teach/courses/AIML101/analytics/GO_01_01_001');
    await tester.tap(find.widgetWithText(FilledButton, 'Draft an explainer'));
    await tester.pumpAndSettle();
    expect(find.textContaining('never published or shown to students'), findsOneWidget);
    expect(api.teach!.explainers, 0); // nothing is spent until asked
    await tester.tap(find.widgetWithText(FilledButton, 'Draft'));
    await tester.pumpAndSettle();
    expect(api.teach!.explainers, 1);
    expect(find.text('Gradient descent moves against the slope.'), findsOneWidget);
    expect(find.widgetWithText(FilledButton, 'Copy'), findsOneWidget);
  });

  testWidgets('the rail links to Analytics and the detail is read-only on a phone', (tester) async {
    await open(tester, '/teach/courses/AIML101/audit');
    await tester.tap(find.text('Analytics'));
    await tester.pumpAndSettle();
    expect(location(tester), '/teach/courses/AIML101/analytics');
  });

  testWidgets('narrow screens: read-only, no export or explainer', (tester) async {
    await open(tester, '/teach/courses/AIML101/analytics/GO_01_01_001', size: const Size(400, 900));
    expect(find.text('Draft an explainer'), findsNothing);
    expect(find.text('All objectives'), findsOneWidget);
    expect(find.text('Not enough evidence', skipOffstage: false), findsNothing);
    expect(find.textContaining('Not enough students yet', skipOffstage: false), findsWidgets);
  });
}
