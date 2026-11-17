import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lea_app/shell/rail.dart';
import 'package:lea_app/widgets/composer.dart';
import 'package:lea_app/widgets/message_bubble.dart';
import 'package:lea_app/widgets/streaming_cursor.dart';

import 'helpers.dart';

const greeting = "Hey, I'm LEA. Got questions on DEMO101 Week 1? I'm here to help!";
const hint = "Chat doesn't count towards mastery. Use Tutor or Quiz for that.";

Finder get input => find.descendant(of: find.byType(Composer), matching: find.byType(TextField));
Finder get sendButton => find.widgetWithText(FilledButton, 'Send');

Future<void> type(WidgetTester tester, String text) async {
  await tester.enterText(input, text);
  await tester.pump();
}

void main() {
  for (final brightness in Brightness.values) {
    for (final (name, size) in [('desktop', desktop), ('phone', phone)]) {
      testWidgets('empty chat, $name, ${brightness.name}: greeting, suggestions, composer', (tester) async {
        await pumpLea(tester, size: size, brightness: brightness);
        expect(find.text(greeting), findsOneWidget);
        for (final lo in ['AI Basics', 'AI Types Overview', 'AI vs ML Distinction']) {
          expect(find.widgetWithText(ActionChip, lo), findsOneWidget);
        }
        expect(find.text('Ask anything about DEMO101…'), findsOneWidget);
        // The hint is on wide screens only, as in the design.
        expect(find.text(hint), size == desktop ? findsOneWidget : findsNothing);
        expect(tester.takeException(), isNull);
      });
    }
  }

  testWidgets('history loads in order with times; suggestions stay hidden once the student has asked', (tester) async {
    final api = FakeApi();
    final t = DateTime(2026, 9, 24, 14, 2).millisecondsSinceEpoch / 1000;
    api.chatHistory.addAll([
      {'role': 'user', 'message': 'What is supervised learning?', 'timestamp': t},
      {'role': 'assistant', 'message': 'It learns from **labelled examples**.', 'timestamp': t + 5},
    ]);
    await pumpLea(tester, api: api);

    expect(find.text('What is supervised learning?'), findsOneWidget);
    expect(find.text('2:02 pm'), findsOneWidget);
    expect(find.textContaining('labelled examples', findRichText: true), findsOneWidget);
    expect(find.text(greeting), findsNothing);
    expect(find.byType(ActionChip), findsNothing);
    final student = tester.getRect(find.text('What is supervised learning?'));
    final lea = tester.getRect(find.textContaining('labelled examples', findRichText: true));
    expect(student.top, lessThan(lea.top));
    expect(student.right, greaterThan(lea.right)); // Student bubbles sit on the right.
  });

  testWidgets('a reply streams in with the cursor, then done replaces it with the final message', (tester) async {
    final api = FakeApi()..chatStream = StreamController<String>();
    await pumpLea(tester, api: api);

    await type(tester, 'What is supervised learning?');
    await tester.tap(sendButton);
    await tester.pump();

    // The question shows at once, the input clears, and Send waits for the reply.
    expect(find.text('What is supervised learning?'), findsOneWidget);
    expect(tester.widget<TextField>(input).controller!.text, isEmpty);
    expect(find.byType(StreamingCursor), findsOneWidget);
    expect(find.byType(ActionChip), findsNothing);
    expect(api.chatSent.single, {'text': 'What is supervised learning?', 'week': 1});

    api.chatStream!.add(FakeApi.sse('token', {'text': 'Supervised learning '}));
    await tester.pump();
    api.chatStream!.add(FakeApi.sse('token', {'text': 'uses labels'}));
    await tester.pump();
    expect(find.textContaining('Supervised learning uses labels', findRichText: true), findsOneWidget);

    await type(tester, 'Another');
    expect(tester.widget<FilledButton>(sendButton).onPressed, isNull);

    api.chatStream!.add(FakeApi.sse('done', {'ok': true, 'message': 'Supervised learning uses labelled data.'}));
    await api.chatStream!.close();
    await tester.pump();
    await tester.pump();

    expect(find.textContaining('Supervised learning uses labelled data.', findRichText: true), findsOneWidget);
    expect(find.textContaining('uses labels', findRichText: true), findsNothing);
    expect(find.byType(StreamingCursor), findsNothing);
    expect(tester.widget<FilledButton>(sendButton).onPressed, isNotNull);
  });

  testWidgets('an error event removes the pending reply, keeps the text in the input and shows the detail', (
    tester,
  ) async {
    final api = FakeApi()..chatStream = StreamController<String>();
    await pumpLea(tester, api: api);
    await type(tester, 'Explain neural networks');
    await tester.tap(sendButton);
    await tester.pump();
    api.chatStream!
      ..add(FakeApi.sse('token', {'text': 'Neural'}))
      ..add(
        FakeApi.sse('error', {
          'detail': "LEA couldn't answer just now. Please try again.",
          'code': 'Unavailable',
          'status': 503,
        }),
      );
    await api.chatStream!.close();
    await tester.pumpAndSettle();

    expect(find.text("LEA couldn't answer just now. Please try again."), findsOneWidget);
    expect(find.byType(StudentBubble), findsNothing);
    expect(find.byType(StreamingCursor), findsNothing);
    expect(tester.widget<TextField>(input).controller!.text, 'Explain neural networks');
    // The greeting and suggestions are back, since nothing was asked after all.
    expect(find.text(greeting), findsOneWidget);
  });

  testWidgets('409 Busy uses the design wording', (tester) async {
    final api = FakeApi();
    api.failures['/chat/DEMO101/messages/stream'] = (409, {'detail': 'Busy', 'code': 'Busy'}, {});
    await pumpLea(tester, api: api);
    await type(tester, 'Hello');
    await tester.tap(sendButton);
    await tester.pumpAndSettle();
    expect(find.text('Still working on your last request.'), findsOneWidget);
    expect(tester.widget<TextField>(input).controller!.text, 'Hello');
  });

  testWidgets('429 says how long to wait', (tester) async {
    final api = FakeApi();
    api.failures['/chat/DEMO101/messages/stream'] = (
      429,
      {'detail': "You're going a bit fast. Try again in a moment.", 'code': 'RateLimited'},
      {'retry-after': '20'},
    );
    await pumpLea(tester, api: api);
    await type(tester, 'Hello');
    await tester.tap(sendButton);
    await tester.pumpAndSettle();
    expect(find.text("You're going a bit fast. Try again in a moment. (wait 20 seconds)"), findsOneWidget);
  });

  testWidgets('Enter sends; Shift+Enter does not', (tester) async {
    final api = FakeApi();
    await pumpLea(tester, api: api);
    await tester.tap(input);
    await type(tester, 'Line one');
    await tester.sendKeyDownEvent(LogicalKeyboardKey.shiftLeft);
    await tester.sendKeyEvent(LogicalKeyboardKey.enter);
    await tester.sendKeyUpEvent(LogicalKeyboardKey.shiftLeft);
    await tester.pumpAndSettle();
    expect(api.chatSent, isEmpty);

    await tester.sendKeyEvent(LogicalKeyboardKey.enter);
    await tester.pumpAndSettle();
    expect(api.chatSent, hasLength(1));
    expect(find.textContaining('labelled', findRichText: true), findsOneWidget);
  });

  testWidgets('Send is disabled for an empty or blank message', (tester) async {
    await pumpLea(tester);
    expect(tester.widget<FilledButton>(sendButton).onPressed, isNull);
    await type(tester, '   ');
    expect(tester.widget<FilledButton>(sendButton).onPressed, isNull);
  });

  testWidgets('a suggestion asks about that learning objective', (tester) async {
    final api = FakeApi();
    await pumpLea(tester, api: api);
    await tester.tap(find.widgetWithText(ActionChip, 'AI Basics'));
    await tester.pumpAndSettle();
    expect(api.chatSent.single['text'], 'Tell me about AI Basics.');
    expect(find.text('Tell me about AI Basics.'), findsOneWidget);
  });

  testWidgets('questions carry the selected week', (tester) async {
    final api = FakeApi(currentWeek: 2);
    await pumpLea(tester, api: api);
    expect(find.text("Hey, I'm LEA. Got questions on DEMO101 Week 2? I'm here to help!"), findsOneWidget);
    await tester.tap(find.descendant(of: find.byType(Rail), matching: find.text('Week 1 · Introduction to AI')));
    await tester.pumpAndSettle();
    expect(find.text(greeting), findsOneWidget);
    await type(tester, 'Recap please');
    await tester.tap(sendButton);
    await tester.pumpAndSettle();
    expect(api.chatSent.single['week'], 1);
  });

  testWidgets('a history that fails to load says why and can be retried', (tester) async {
    final api = FakeApi();
    api.failures['/chat/DEMO101/messages'] = (
      503,
      {'detail': 'LEA is having trouble right now. Try again in a minute.', 'code': 'Unavailable'},
      {},
    );
    await pumpLea(tester, api: api);
    expect(find.text('LEA is having trouble right now. Try again in a minute.'), findsOneWidget);
    api.failures.clear();
    await tester.tap(find.widgetWithText(OutlinedButton, 'Try again'));
    await tester.pumpAndSettle();
    expect(find.text(greeting), findsOneWidget);
  });

  testWidgets('the cursor holds still when reduced motion is on', (tester) async {
    final api = FakeApi()..chatStream = StreamController<String>();
    await pumpLea(tester, api: api);
    tester.platformDispatcher.accessibilityFeaturesTestValue = const FakeAccessibilityFeatures(disableAnimations: true);
    addTearDown(tester.platformDispatcher.clearAccessibilityFeaturesTestValue);
    await tester.pump();
    await type(tester, 'Hi');
    await tester.tap(sendButton);
    await tester.pump();

    double opacity() => tester
        .widget<Opacity>(find.descendant(of: find.byType(StreamingCursor), matching: find.byType(Opacity)))
        .opacity;
    expect(opacity(), 1);
    await tester.pump(const Duration(milliseconds: 600));
    expect(opacity(), 1);

    api.chatStream!.add(FakeApi.sse('done', {'ok': true, 'message': 'Hello!'}));
    await api.chatStream!.close();
    await tester.pumpAndSettle();
  });

  testWidgets('the cursor blinks otherwise', (tester) async {
    final api = FakeApi()..chatStream = StreamController<String>();
    await pumpLea(tester, api: api);
    await type(tester, 'Hi');
    await tester.tap(sendButton);
    await tester.pump();
    double opacity() => tester
        .widget<Opacity>(find.descendant(of: find.byType(StreamingCursor), matching: find.byType(Opacity)))
        .opacity;
    final first = opacity();
    await tester.pump(const Duration(milliseconds: 510));
    expect(opacity(), isNot(first));

    api.chatStream!.add(FakeApi.sse('done', {'ok': true, 'message': 'Hello!'}));
    await api.chatStream!.close();
    await tester.pump();
    await tester.pump();
  });
}
