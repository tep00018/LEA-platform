import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import 'helpers.dart';

const wide = Size(1300, 1000);

FakeApi staffApi(String role) => FakeApi()
  ..role = role
  ..teach = FakeTeach();

Future<FakeApi> open(WidgetTester tester, String path, {String role = 'teacher', Size size = wide}) async {
  final api = staffApi(role);
  await pumpLea(tester, api: api, size: size);
  GoRouter.of(tester.element(find.byType(Navigator).first)).go(path);
  await tester.pumpAndSettle();
  return api;
}

String location(WidgetTester tester) =>
    GoRouter.of(tester.element(find.byType(Navigator).first)).routeInformationProvider.value.uri.path;

void main() {
  group('content audit', () {
    testWidgets('first run shows ranked findings with their evidence tier', (tester) async {
      final api = await open(tester, '/teach/courses/AIML101/audit');
      expect(find.textContaining('No audit yet'), findsOneWidget);
      await tester.tap(find.widgetWithText(FilledButton, 'Run the audit · ≈ \$0.002'));
      await tester.pumpAndSettle();
      expect(find.text('3 findings'), findsOneWidget);
      expect(find.text('12 picture(s) in Week04-LectureB.pptx have no text alternative'), findsOneWidget);
      expect(find.text('Well supported'), findsOneWidget);
      expect(find.text('Experimental'), findsOneWidget);
      expect(find.text('Evidence for k1'), findsOneWidget);
      expect(api.teach!.auditRuns, 1);
    });

    testWidgets('accept, dismiss with a note, reopen; decisions carry into the next run', (tester) async {
      final api = await open(tester, '/teach/courses/AIML101/audit');
      await tester.tap(find.widgetWithText(FilledButton, 'Run the audit · ≈ \$0.002'));
      await tester.pumpAndSettle();

      await tester.tap(find.widgetWithText(FilledButton, 'Accept').first);
      await tester.pumpAndSettle();
      expect(find.text('Accepted'), findsOneWidget);
      await tester.tap(find.widgetWithText(OutlinedButton, 'Dismiss…').first);
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('dismiss-note')), 'intended');
      await tester.tap(find.widgetWithText(FilledButton, 'Dismiss'));
      await tester.pumpAndSettle();
      expect(find.text('Dismissed · “intended”'), findsOneWidget);
      expect(api.teach!.decisions['k2'], {'status': 'dismissed', 'note': 'intended'});
      expect(find.textContaining('2 reviewed'), findsOneWidget);

      api.teach!.nextFindings = [
        api.teach!.nextFindings.first,
        FakeTeach.finding('k9', 'questions', 'medium', 'Question 7: negative', 'well_supported'),
      ];
      await tester.tap(find.widgetWithText(FilledButton, 'Run audit again · ≈ \$0.002'));
      await tester.pumpAndSettle();
      expect(find.text('Accepted'), findsOneWidget); // k1's decision carried over
      expect(find.text('New'), findsOneWidget); // k9
      expect(find.text('Resolved since the last run (2)'), findsOneWidget);

      await tester.tap(find.widgetWithText(TextButton, 'Reopen'));
      await tester.pumpAndSettle();
      expect(api.teach!.decisions.containsKey('k1'), isFalse);
    });

    testWidgets('filters by check', (tester) async {
      await open(tester, '/teach/courses/AIML101/audit');
      await tester.tap(find.widgetWithText(FilledButton, 'Run the audit · ≈ \$0.002'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Coverage 1'));
      await tester.pumpAndSettle();
      expect(find.text('“Implement gradient descent” has weak support in the materials'), findsOneWidget);
      expect(find.textContaining('no text alternative'), findsNothing);
    });

    testWidgets('the rail links to the audit', (tester) async {
      await open(tester, '/teach/courses/AIML101/setup');
      await tester.tap(find.text('Content audit'));
      await tester.pumpAndSettle();
      expect(location(tester), '/teach/courses/AIML101/audit');
    });
  });

  group('users and owners', () {
    testWidgets('only admins see it; teachers are sent to their courses', (tester) async {
      await open(tester, '/admin/users');
      expect(location(tester), '/teach');
      expect(find.text('Users and owners'), findsNothing);
    });

    testWidgets('admins see every account with role and status, and filter them', (tester) async {
      await open(tester, '/teach', role: 'admin');
      await tester.tap(find.text('Users and owners'));
      await tester.pumpAndSettle();
      expect(location(tester), '/admin/users');
      expect(find.text('4 accounts · 1 teacher · 1 admin'), findsOneWidget);
      expect(find.text('Dr Okafor'), findsOneWidget);
      expect(find.text('Test'), findsOneWidget);
      await tester.tap(find.widgetWithText(ChoiceChip, 'Staff'));
      await tester.pumpAndSettle();
      expect(find.text('Sam Lee'), findsNothing);
      await tester.enterText(find.byKey(const Key('user-search')), 'oka');
      await tester.pumpAndSettle();
      expect(find.text('alex.m (preview)'), findsNothing);
      expect(find.text('Dr Okafor'), findsOneWidget);
    });

    testWidgets('edit a role, deactivate, mark a test account', (tester) async {
      final api = await open(tester, '/admin/users', role: 'admin');
      await tester.tap(find.bySemanticsLabel('Edit slee'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Student').last);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Teacher').last);
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(SwitchListTile, 'Test account'));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, 'Save'));
      await tester.pumpAndSettle();
      expect(api.teach!.bodies['/admin/users/slee']!.last, {'role': 'teacher', 'session_kind': 'test'});
      final slee = api.teach!.users.firstWhere((u) => u['username'] == 'slee');
      expect(slee['role'], 'teacher');
      expect(slee['session_kind'], 'test');
    });

    testWidgets('create a teacher account', (tester) async {
      final api = await open(tester, '/admin/users', role: 'admin');
      await tester.enterText(find.byKey(const Key('new-name')), 'Dr Amara Okafor');
      await tester.enterText(find.byKey(const Key('new-username')), 'aokafor');
      await tester.enterText(find.byKey(const Key('new-password')), 'short');
      await tester.ensureVisible(find.widgetWithText(FilledButton, 'Create account'));
      await tester.tap(find.widgetWithText(FilledButton, 'Create account'));
      await tester.pumpAndSettle();
      expect(find.text('Temporary passwords must be at least 8 characters.'), findsOneWidget);
      await tester.enterText(find.byKey(const Key('new-password')), 'long-enough-1');
      await tester.tap(find.widgetWithText(FilledButton, 'Create account'));
      await tester.pumpAndSettle();
      expect(api.teach!.bodies['/admin/users']!.whereType<Map>().last, {
        'username': 'aokafor',
        'full_name': 'Dr Amara Okafor',
        'password': 'long-enough-1',
        'role': 'teacher',
      });
      expect(find.textContaining('Created aokafor'), findsOneWidget);
    });

    testWidgets('enrolled courses: add and remove, from the edit dialog', (tester) async {
      final api = await open(tester, '/admin/users', role: 'admin');
      await tester.tap(find.bySemanticsLabel('Edit slee'));
      await tester.pumpAndSettle();
      expect(find.text('Not enrolled in any course.'), findsOneWidget);

      await tester.tap(find.byKey(const Key('add-enrollment')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('DEMO101').last);
      await tester.pumpAndSettle();
      await tester.tap(find.descendant(of: find.byType(AlertDialog), matching: find.widgetWithText(FilledButton, 'Add')));
      await tester.pumpAndSettle();

      expect(find.text('Not enrolled in any course.'), findsNothing);
      expect(find.descendant(of: find.byType(InputChip), matching: find.text('DEMO101')), findsOneWidget);
      final slee = api.teach!.users.firstWhere((u) => u['username'] == 'slee');
      expect(slee['enrolled_courses'], ['DEMO101']);

      await tester.tap(find.descendant(of: find.byKey(const Key('enrolled-DEMO101')), matching: find.byType(Icon)));
      await tester.pumpAndSettle();
      expect(find.text('Not enrolled in any course.'), findsOneWidget);
      expect(slee['enrolled_courses'], <String>[]);
    });

    testWidgets('course owners: remove and add', (tester) async {
      final api = await open(tester, '/admin/users', role: 'admin');
      expect(find.text('okafor'), findsWidgets);
      await tester.tap(find.bySemanticsLabel('Remove okafor'));
      await tester.pumpAndSettle();
      expect(api.teach!.owners['AIML101'], ['alex.m']);
      await tester.tap(find.byKey(const Key('owners-add')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Dr Okafor').last);
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, 'Add'));
      await tester.pumpAndSettle();
      expect(api.teach!.owners['AIML101'], ['alex.m', 'okafor']);
    });
  });
}
