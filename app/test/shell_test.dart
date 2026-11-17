import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lea_app/screens/chat/chat_screen.dart';
import 'package:lea_app/screens/login/login_screen.dart';
import 'package:lea_app/screens/progress/progress_screen.dart';
import 'package:lea_app/screens/quiz/quiz_screen.dart';
import 'package:lea_app/screens/tutor/tutor_screen.dart';
import 'package:lea_app/shell/bottom_nav.dart';
import 'package:lea_app/shell/course_panel.dart';
import 'package:lea_app/shell/mode_tabs.dart';
import 'package:lea_app/shell/rail.dart';
import 'package:lea_app/shell/top_bar.dart';
import 'package:lea_app/theme/lea_colors.dart';
import 'package:lea_app/widgets/skeleton.dart';

import 'helpers.dart';

Finder inRail(String text) => find.descendant(of: find.byType(Rail), matching: find.text(text));

void main() {
  for (final brightness in Brightness.values) {
    group('${brightness.name} theme', () {
      testWidgets('desktop (1224 px): rail with the course from the API, and tabs', (tester) async {
        await pumpLea(tester, size: desktop, brightness: brightness);

        expect(find.byType(Rail), findsOneWidget);
        expect(find.byType(ModeTabs), findsOneWidget);
        expect(find.byType(TopBar), findsNothing);
        expect(find.byType(BottomNav), findsNothing);
        expect(tester.getSize(find.byType(Rail)).width, 260);

        expect(find.text('Slide In. Study Up. Show Off.'), findsOneWidget);
        expect(find.text('COURSE'), findsOneWidget);
        expect(find.text('DEMO101 · Introduction to AI/ML'), findsOneWidget);
        expect(find.text('WEEKS'), findsOneWidget);
        expect(find.text('Week 1 · Introduction to AI'), findsOneWidget);
        expect(find.text('2 / 11'), findsOneWidget);
        expect(find.text('Week 2 · Machine Learning Basics'), findsOneWidget);
        expect(find.text('Opens when 75% of Week 1 is mastered'), findsOneWidget);
        expect(find.text('Week 3 · Neural Networks'), findsOneWidget);
        expect(find.text('Your progress'), findsOneWidget);
        expect(find.text('Alex M.'), findsOneWidget);
        for (final tab in ['Chat', 'Tutor', 'Quiz']) {
          expect(find.descendant(of: find.byType(ModeTabs), matching: find.text(tab)), findsOneWidget);
        }

        final c = brightness == Brightness.light ? LeaColors.light : LeaColors.dark;
        expect(Theme.of(tester.element(find.byType(Rail))).extension<LeaColors>()!.bg, c.bg);
        expect(tester.takeException(), isNull);
      });

      testWidgets('phone (390 px): top bar with the course line, and bottom nav', (tester) async {
        await pumpLea(tester, size: phone, brightness: brightness);

        expect(find.byType(Rail), findsNothing);
        expect(find.byType(ModeTabs), findsNothing);
        expect(find.byType(BottomNav), findsOneWidget);
        expect(find.descendant(of: find.byType(TopBar), matching: find.text('Chat')), findsOneWidget);
        expect(find.text('DEMO101 · Week 1 · Introduction to AI'), findsOneWidget);
        expect(find.text('2 / 11'), findsOneWidget);
        for (final item in ['Chat', 'Tutor', 'Quiz', 'Progress']) {
          expect(find.descendant(of: find.byType(BottomNav), matching: find.text(item)), findsOneWidget);
        }
        expect(tester.takeException(), isNull);
      });
    });
  }

  testWidgets('the breakpoint is 720 px of app width', (tester) async {
    await pumpLea(tester, size: const Size(720, 800));
    expect(find.byType(Rail), findsOneWidget);
    await pumpLea(tester, size: const Size(719, 800));
    expect(find.byType(Rail), findsNothing);
    expect(find.byType(BottomNav), findsOneWidget);
  });

  testWidgets('desktop tabs and the progress link change screen', (tester) async {
    await pumpLea(tester, size: desktop);
    expect(find.byType(ChatScreen), findsOneWidget);

    await tester.tap(find.descendant(of: find.byType(ModeTabs), matching: find.text('Quiz')));
    await tester.pumpAndSettle();
    expect(find.byType(QuizScreen), findsOneWidget);

    await tester.tap(find.text('Your progress'));
    await tester.pumpAndSettle();
    expect(find.byType(ProgressScreen), findsOneWidget);
  });

  testWidgets('bottom nav changes screen and the top bar title follows', (tester) async {
    await pumpLea(tester, size: phone);
    await tester.tap(find.descendant(of: find.byType(BottomNav), matching: find.text('Tutor')));
    await tester.pumpAndSettle();
    expect(find.descendant(of: find.byType(TopBar), matching: find.text('Tutor')), findsOneWidget);
    expect(find.byType(TutorScreen), findsOneWidget);
  });

  group('weeks', () {
    testWidgets('the current week comes from progress; earlier weeks can be picked, later ones are locked', (
      tester,
    ) async {
      final api = FakeApi(currentWeek: 2)..mastered[2] = 3;
      await pumpLea(tester, api: api);

      // Week 2 is current and selected.
      expect(find.text('3 / 9'), findsOneWidget);
      expect(find.text('Opens when 75% of Week 2 is mastered'), findsOneWidget);
      expect(find.text('Opens when 75% of Week 1 is mastered'), findsNothing);

      // Go back to week 1 for review.
      await tester.tap(inRail('Week 1 · Introduction to AI'));
      await tester.pumpAndSettle();
      expect(find.text('2 / 11'), findsOneWidget);
      expect(api.requests.any((r) => r.url.query == 'week=1'), isTrue);

      // Week 3 is locked: tapping it does nothing.
      await tester.tap(inRail('Week 3 · Neural Networks'));
      await tester.pumpAndSettle();
      expect(find.text('2 / 11'), findsOneWidget);
      expect(api.requests.any((r) => r.url.query == 'week=3'), isFalse);
    });

    testWidgets('on a phone, picking a week in the sheet closes it and updates the top bar', (tester) async {
      await pumpLea(tester, size: phone, api: FakeApi(currentWeek: 2));
      expect(find.text('DEMO101 · Week 2 · Machine Learning Basics'), findsOneWidget);

      await tester.tap(find.byType(TopBar));
      await tester.pumpAndSettle();
      expect(find.text('Logged in as Alex M.'), findsOneWidget);
      await tester.tap(find.text('Week 1 · Introduction to AI'));
      await tester.pumpAndSettle();

      expect(find.text('Logged in as Alex M.'), findsNothing);
      expect(find.text('DEMO101 · Week 1 · Introduction to AI'), findsOneWidget);
      expect(find.text('2 / 11'), findsOneWidget);
    });
  });

  testWidgets('the course picker switches course and starts on its current week', (tester) async {
    final api = FakeApi(
      courses: [
        {'code': 'DEMO101', 'name': 'DEMO101: Introduction to AI/ML'},
        {'code': 'DEMO102', 'name': 'DEMO102: Data Ethics'},
      ],
    );
    await pumpLea(tester, api: api);
    expect(find.text('DEMO101 · Introduction to AI/ML'), findsOneWidget);

    await tester.tap(find.byType(CourseBox));
    await tester.pumpAndSettle();
    await tester.tap(find.text('DEMO102 · Data Ethics').last);
    await tester.pumpAndSettle();

    expect(inRail('DEMO102 · Data Ethics'), findsOneWidget);
    expect(api.calls('/courses/DEMO102/outline'), 1);
    expect(api.calls('/courses/DEMO102/progress'), 1);
  });

  testWidgets('"Add a course…" enrolls you and switches to it', (tester) async {
    final api = FakeApi(
      courses: [
        {'code': 'DEMO101', 'name': 'DEMO101: Introduction to AI/ML'},
        {'code': 'DEMO102', 'name': 'DEMO102: Data Ethics'},
      ],
      enrolledCourses: [
        {'code': 'DEMO101', 'name': 'DEMO101: Introduction to AI/ML'},
      ],
    );
    await pumpLea(tester, api: api);
    expect(find.text('DEMO101 · Introduction to AI/ML'), findsOneWidget);

    await tester.tap(find.byType(CourseBox));
    await tester.pumpAndSettle();
    expect(find.text('DEMO102 · Data Ethics'), findsNothing); // not enrolled, so not in the switcher
    await tester.tap(find.text('Add a course…'));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('add-course-picker')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('DEMO102 · Data Ethics').last);
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Add'));
    await tester.pumpAndSettle();

    expect(find.byType(AlertDialog), findsNothing);
    expect(api.enrolledCourses!.map((c) => c['code']), ['DEMO101', 'DEMO102']);
  });

  testWidgets('"Leave course" un-enrolls after confirming, keeping progress', (tester) async {
    final api = FakeApi(
      courses: [
        {'code': 'DEMO101', 'name': 'DEMO101: Introduction to AI/ML'},
        {'code': 'DEMO102', 'name': 'DEMO102: Data Ethics'},
      ],
      enrolledCourses: [
        {'code': 'DEMO101', 'name': 'DEMO101: Introduction to AI/ML'},
        {'code': 'DEMO102', 'name': 'DEMO102: Data Ethics'},
      ],
    );
    await pumpLea(tester, api: api);

    await tester.tap(find.byType(CourseBox));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Leave DEMO102 · Data Ethics'));
    await tester.pumpAndSettle();

    expect(find.text('Leave DEMO102 · Data Ethics?'), findsOneWidget);
    expect(find.textContaining('Your progress in this course is kept'), findsOneWidget);
    await tester.tap(find.widgetWithText(FilledButton, 'Leave course'));
    await tester.pumpAndSettle();

    expect(find.byType(AlertDialog), findsNothing);
    expect(api.enrolledCourses!.map((c) => c['code']), ['DEMO101']);

    await tester.tap(find.byType(CourseBox));
    await tester.pumpAndSettle();
    expect(find.text('DEMO102 · Data Ethics'), findsNothing);
  });

  group('loading and errors', () {
    testWidgets('shows skeletons, not a spinner, while the course loads', (tester) async {
      final api = FakeApi();
      final gate = api.holds['/me/courses'] = Completer<void>();
      await pumpLea(tester, api: api);
      expect(find.byType(CoursePanelSkeleton), findsOneWidget);
      expect(find.byType(CircularProgressIndicator), findsNothing);

      gate.complete();
      await tester.pumpAndSettle();
      expect(find.byType(CoursePanelSkeleton), findsNothing);
      expect(find.text('DEMO101 · Introduction to AI/ML'), findsOneWidget);
    });

    testWidgets('on a phone the top bar shows skeletons while the course loads', (tester) async {
      final api = FakeApi();
      final gate = api.holds['/me/courses'] = Completer<void>();
      await pumpLea(tester, api: api, size: phone);
      expect(find.descendant(of: find.byType(TopBar), matching: find.byType(SkeletonBox)), findsNWidgets(2));
      gate.complete();
      await tester.pumpAndSettle();
      expect(find.text('2 / 11'), findsOneWidget);
    });

    testWidgets('a failed course load shows the API detail and retries', (tester) async {
      final api = FakeApi();
      api.failures['/me/courses'] = (
        503,
        {'detail': 'LEA is having trouble right now. Try again in a minute.', 'code': 'Unavailable'},
        {},
      );
      await pumpLea(tester, api: api);
      // In the rail and in the content area.
      expect(find.text('LEA is having trouble right now. Try again in a minute.'), findsNWidgets(2));

      api.failures.clear();
      await tester.tap(find.text('Try again').first);
      await tester.pumpAndSettle();
      expect(find.text('DEMO101 · Introduction to AI/ML'), findsOneWidget);
    });

    testWidgets('a student with no courses is told what to do', (tester) async {
      await pumpLea(tester, api: FakeApi(courses: []));
      expect(find.text("You're not enrolled in a course yet. Ask your course tutor to add you."), findsNWidgets(2));
      expect(find.text('Try again'), findsNothing);
    });
  });

  group('login state', () {
    testWidgets('no saved token goes to login', (tester) async {
      await pumpLea(tester, token: null);
      expect(find.byType(LoginScreen), findsOneWidget);
    });

    testWidgets('a saved token logs straight in (checked with GET /me)', (tester) async {
      final r = await pumpLea(tester);
      expect(find.byType(Rail), findsOneWidget);
      expect(r.api.calls('/me'), 1);
    });

    testWidgets('an expired saved token goes to login with "Please log in again."', (tester) async {
      final r = await pumpLea(tester, token: 'expired-token');
      expect(find.byType(LoginScreen), findsOneWidget);
      expect(find.text('Please log in again.'), findsOneWidget);
      expect(r.store.token, isNull);
    });

    testWidgets('a 401 while using the app returns to login with "Please log in again."', (tester) async {
      final api = FakeApi();
      api.failures['/courses/DEMO101/progress'] = (401, {'detail': 'Expired.', 'code': 'NotAuthenticated'}, {});
      final r = await pumpLea(tester, api: api);
      expect(find.byType(LoginScreen), findsOneWidget);
      expect(find.text('Please log in again.'), findsOneWidget);
      expect(r.store.token, isNull);
    });

    testWidgets('log out clears the token and returns to login', (tester) async {
      final r = await pumpLea(tester);
      final before = r.api.requests.length;
      await tester.tap(find.text('Log out'));
      await tester.pumpAndSettle();
      // Only the logout itself: nothing reloads for nobody once the token is gone.
      expect(r.api.requests.skip(before).map((q) => q.url.path), ['/auth/logout']);
      expect(find.byType(LoginScreen), findsOneWidget);
      expect(r.store.token, isNull);
      expect(r.api.calls('/auth/logout'), 1);
    });
  });
}
