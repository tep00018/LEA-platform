import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lea_app/connectivity.dart';
import 'package:lea_app/screens/login/login_screen.dart';
import 'package:lea_app/shell/rail.dart';
import 'package:lea_app/widgets/composer.dart';
import 'package:lea_app/widgets/offline_banner.dart';

import 'helpers.dart';

const banner = "Can't reach LEA. Check that the LEA server is running.";

Finder get bannerText => find.descendant(of: find.byType(OfflineBanner), matching: find.text(banner));

void main() {
  testWidgets('no banner while the server answers', (tester) async {
    await pumpLea(tester);
    expect(bannerText, findsNothing);
  });

  testWidgets('server down at start: login with the banner; it clears when the server is back', (tester) async {
    final api = FakeApi()..down = true;
    await pumpLea(tester, api: api);
    expect(find.byType(LoginScreen), findsOneWidget);
    expect(bannerText, findsOneWidget);

    api.down = false;
    await tester.pump(ConnectivityController.checkEvery);
    await tester.pumpAndSettle();
    expect(bannerText, findsNothing);
    expect(api.requests.any((r) => r.url.path == '/health'), isTrue);
  });

  testWidgets('server stops while in use: banner and the message by the composer', (tester) async {
    final api = FakeApi();
    await pumpLea(tester, api: api);
    api.down = true;
    await tester.enterText(find.descendant(of: find.byType(Composer), matching: find.byType(TextField)), 'Hello?');
    await tester.pump();
    await tester.tap(find.widgetWithText(FilledButton, 'Send'));
    await tester.pumpAndSettle();
    expect(bannerText, findsOneWidget);
    expect(find.text(banner), findsNWidgets(2)); // banner + composer error

    // "Try again" checks at once.
    api.down = false;
    await tester.tap(find.descendant(of: find.byType(OfflineBanner), matching: find.text('Try again')));
    await tester.pumpAndSettle();
    expect(bannerText, findsNothing);
  });

  testWidgets('a course that failed while offline loads by itself when the server is back', (tester) async {
    final api = FakeApi();
    await pumpLea(tester, api: api, token: null);
    // Log in, then lose the server before the course loads.
    await tester.enterText(find.byType(TextField).at(0), 'alex.m');
    await tester.enterText(find.byType(TextField).at(1), 'correct horse');
    await tester.tap(find.widgetWithText(FilledButton, 'Log in'));
    api.down = true;
    await tester.pumpAndSettle();
    expect(bannerText, findsOneWidget);
    expect(find.descendant(of: find.byType(Rail), matching: find.text(banner)), findsOneWidget);

    api.down = false;
    await tester.pump(ConnectivityController.checkEvery);
    await tester.pumpAndSettle();
    expect(bannerText, findsNothing);
    expect(find.text('DEMO101 · Introduction to AI/ML'), findsOneWidget);
  });

  testWidgets('the course list on Create account reloads by itself when the server is back', (tester) async {
    final api = FakeApi();
    await pumpLea(tester, api: api, token: null);
    api.down = true;
    await tester.tap(find.text('Create account').first);
    await tester.pumpAndSettle();
    expect(find.text(banner), findsNWidgets(2)); // banner + the course field

    api.down = false;
    await tester.pump(ConnectivityController.checkEvery);
    await tester.pumpAndSettle();
    expect(find.text(banner), findsNothing);
    expect(find.text('DEMO101 · Introduction to AI/ML'), findsOneWidget);
  });

  testWidgets('a chat history that failed offline reloads by itself', (tester) async {
    final api = FakeApi();
    api.chatHistory.add({'role': 'user', 'message': 'Earlier question', 'timestamp': 1790000000.0});
    api.holds['/chat/DEMO101/messages'] = Completer<void>();
    await pumpLea(tester, api: api);
    api.down = true;
    api.holds.remove('/chat/DEMO101/messages')!.complete();
    await tester.pumpAndSettle();
    expect(bannerText, findsOneWidget);
    expect(find.text('Earlier question'), findsNothing);

    api.down = false;
    await tester.pump(ConnectivityController.checkEvery);
    await tester.pumpAndSettle();
    expect(find.text('Earlier question'), findsOneWidget);
  });
}
