import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lea_app/screens/login/board_panel.dart';
import 'package:lea_app/screens/login/login_screen.dart';
import 'package:lea_app/shell/rail.dart';

import 'helpers.dart';

Finder field(String key) => find.descendant(of: find.byKey(ValueKey(key)), matching: find.byType(TextField));
Finder button(String label) => find.widgetWithText(FilledButton, label);

Future<void> tapTab(WidgetTester tester, String label) async {
  await tester.tap(find.descendant(of: find.byType(Row), matching: find.text(label)).first);
  await tester.pumpAndSettle();
}

void main() {
  for (final brightness in Brightness.values) {
    testWidgets('desktop, ${brightness.name}: board panel beside the form, with the description', (tester) async {
      await pumpLea(tester, token: null, brightness: brightness);
      final board = tester.getRect(find.byType(BoardPanel));
      expect(board.left, 0);
      expect(board.height, desktop.height);
      expect(board.width, closeTo(desktop.width * 105 / 205, 1));

      expect(find.text('LEA'), findsOneWidget);
      expect(find.text('Learning Engagement Assistant'), findsOneWidget);
      expect(find.bySemanticsLabel('Slide In. Study Up. Show Off.'), findsOneWidget);
      expect(find.text(BoardPanel.description), findsOneWidget);
      expect(find.text('Welcome back'), findsOneWidget);
      expect(find.text('Username'), findsOneWidget);
      expect(find.text('Password'), findsOneWidget);
      expect(button('Log in'), findsOneWidget);
      expect(find.text('Forgot your password? Ask your course tutor to reset it.'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('phone, ${brightness.name}: the panel is a header above the form, without the description', (
      tester,
    ) async {
      await pumpLea(tester, token: null, size: phone, brightness: brightness);
      final board = tester.getRect(find.byType(BoardPanel));
      final heading = tester.getRect(find.text('Welcome back'));
      expect(board.width, phone.width);
      expect(heading.top, greaterThan(board.bottom));
      expect(find.text(BoardPanel.description), findsNothing);
      expect(tester.takeException(), isNull);
    });
  }

  group('log in', () {
    testWidgets('success opens Chat and saves the token', (tester) async {
      final r = await pumpLea(tester, token: null);
      await tester.enterText(field('login-username'), 'alex.m');
      await tester.enterText(field('login-password'), 'correct horse');
      await tester.tap(button('Log in'));
      await tester.pumpAndSettle();
      expect(find.byType(Rail), findsOneWidget);
      expect(r.store.token, validToken);
    });

    testWidgets('Enter in the password field logs in', (tester) async {
      await pumpLea(tester, token: null);
      await tester.enterText(field('login-username'), 'alex.m');
      await tester.enterText(field('login-password'), 'correct horse');
      await tester.testTextInput.receiveAction(TextInputAction.done);
      await tester.pumpAndSettle();
      expect(find.byType(Rail), findsOneWidget);
    });

    testWidgets('a wrong password shows the API detail under the form', (tester) async {
      await pumpLea(tester, token: null);
      await tester.enterText(field('login-username'), 'alex.m');
      await tester.enterText(field('login-password'), 'nope');
      await tester.tap(button('Log in'));
      await tester.pumpAndSettle();
      expect(find.text('Wrong username or password.'), findsOneWidget);
      expect(find.byType(LoginScreen), findsOneWidget);
    });

    testWidgets('empty fields are caught before calling the API', (tester) async {
      final r = await pumpLea(tester, token: null);
      await tester.tap(button('Log in'));
      await tester.pumpAndSettle();
      expect(find.text('Enter your username and password.'), findsOneWidget);
      expect(r.api.calls('/auth/login'), 0);
    });

    testWidgets('a 429 shows how long to wait', (tester) async {
      final api = FakeApi();
      api.failures['/auth/login'] = (
        429,
        {'detail': 'Too many failed logins from this device. Try again later.', 'code': 'RateLimited'},
        {'retry-after': '540'},
      );
      await pumpLea(tester, token: null, api: api);
      await tester.enterText(field('login-username'), 'alex.m');
      await tester.enterText(field('login-password'), 'x');
      await tester.tap(button('Log in'));
      await tester.pumpAndSettle();
      expect(find.text('Too many failed logins from this device. Try again later. (wait 9 minutes)'), findsOneWidget);
    });

    testWidgets('a server that is down says so', (tester) async {
      final api = FakeApi();
      api.failures['/auth/login'] = (502, {}, {});
      await pumpLea(tester, token: null, api: api);
      await tester.enterText(field('login-username'), 'alex.m');
      await tester.enterText(field('login-password'), 'x');
      await tester.tap(button('Log in'));
      await tester.pumpAndSettle();
      expect(find.text('Something went wrong on the LEA server. Please try again.'), findsOneWidget);
    });
  });

  group('create account', () {
    Future<void> fill(
      WidgetTester tester, {
      String username = 'sam.k',
      String name = 'Sam K.',
      String password = 'secret1',
      String? confirm,
    }) async {
      await tester.enterText(field('register-username'), username);
      await tester.enterText(field('register-full-name'), name);
      await tester.enterText(field('register-password'), password);
      await tester.enterText(field('register-confirm'), confirm ?? password);
    }

    testWidgets('lists courses from GET /courses and picks the only one', (tester) async {
      final r = await pumpLea(tester, token: null);
      await tapTab(tester, 'Create account');
      expect(find.text('Create your account'), findsOneWidget);
      expect(find.text('Full name'), findsOneWidget);
      expect(find.text('Confirm password'), findsOneWidget);
      expect(find.text('DEMO101 · Introduction to AI/ML'), findsOneWidget);
      expect(r.api.calls('/courses'), 1);
    });

    testWidgets('success switches to Log in with the message and the username filled in', (tester) async {
      final r = await pumpLea(tester, token: null);
      await tapTab(tester, 'Create account');
      await fill(tester);
      await tester.tap(button('Create account'));
      await tester.pumpAndSettle();

      expect(r.api.registered.single, {
        'username': 'sam.k',
        'full_name': 'Sam K.',
        'password': 'secret1',
        'courses': ['DEMO101'],
      });
      expect(find.text('Welcome back'), findsOneWidget);
      expect(find.text('Account created. You can log in now.'), findsOneWidget);
      expect(tester.widget<TextField>(field('login-username')).controller!.text, 'sam.k');
    });

    testWidgets('mismatched passwords are caught before calling the API', (tester) async {
      final r = await pumpLea(tester, token: null);
      await tapTab(tester, 'Create account');
      await fill(tester, confirm: 'secret2');
      await tester.tap(button('Create account'));
      await tester.pumpAndSettle();
      expect(find.text("The passwords don't match."), findsOneWidget);
      expect(r.api.calls('/auth/register'), 0);
    });

    testWidgets('a short password or username is caught before calling the API', (tester) async {
      final r = await pumpLea(tester, token: null);
      await tapTab(tester, 'Create account');
      await fill(tester, password: '12345');
      await tester.tap(button('Create account'));
      await tester.pumpAndSettle();
      expect(find.text('Choose a password of at least 6 characters.'), findsOneWidget);

      await fill(tester, username: 'ab');
      await tester.tap(button('Create account'));
      await tester.pumpAndSettle();
      expect(find.text('Choose a username of 3 to 32 characters.'), findsOneWidget);
      expect(r.api.calls('/auth/register'), 0);
    });

    testWidgets('an API error is shown under the form', (tester) async {
      await pumpLea(tester, token: null);
      await tapTab(tester, 'Create account');
      await fill(tester, username: 'alex.m');
      await tester.tap(button('Create account'));
      await tester.pumpAndSettle();
      expect(find.text('That username is taken. Choose another.'), findsOneWidget);
      expect(find.text('Create your account'), findsOneWidget);
    });

    testWidgets('with several courses the student must choose one', (tester) async {
      final api = FakeApi(
        courses: [
          {'code': 'DEMO101', 'name': 'DEMO101: Introduction to AI/ML'},
          {'code': 'DEMO102', 'name': 'DEMO102: Data Ethics'},
        ],
      );
      await pumpLea(tester, token: null, api: api);
      await tapTab(tester, 'Create account');
      await fill(tester);
      await tester.tap(button('Create account'));
      await tester.pumpAndSettle();
      expect(find.text('Choose your course.'), findsOneWidget);

      await tester.tap(find.text('Choose your course'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('DEMO102 · Data Ethics').last);
      await tester.pumpAndSettle();
      await tester.tap(button('Create account'));
      await tester.pumpAndSettle();
      expect(api.registered.single['courses'], ['DEMO102']);
    });

    testWidgets('with several courses the open course (AIML101) is suggested', (tester) async {
      final api = FakeApi(
        courses: [
          {'code': 'AIML101', 'name': 'AIML101: Introduction to AI and Machine Learning (open course)'},
          {'code': 'DEMO102', 'name': 'DEMO102: Second demo course'},
        ],
      );
      await pumpLea(tester, token: null, api: api);
      await tapTab(tester, 'Create account');
      await fill(tester);
      await tester.tap(button('Create account'));
      await tester.pumpAndSettle();
      expect(api.registered.single['courses'], ['AIML101']);
    });
  });
}
