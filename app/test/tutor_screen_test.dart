import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:lea_app/screens/tutor/tutor_header.dart';
import 'package:lea_app/screens/tutor/tutor_screen.dart';
import 'package:lea_app/shell/rail.dart';
import 'package:lea_app/widgets/composer.dart';
import 'package:lea_app/widgets/streaming_cursor.dart';

import 'helpers.dart';

const hint = "Your replies count towards mastery. The first reply is a warm-up and doesn't count.";

Finder get input => find.descendant(of: find.byType(Composer), matching: find.byType(TextField));
Finder get sendButton => find.widgetWithText(FilledButton, 'Send');

/// Pumps the app on the Tutor tab.
Future<FakeApi> openTutor(WidgetTester tester, {FakeApi? api, Size size = desktop, Brightness? brightness}) async {
  final fake = api ?? FakeApi();
  await pumpLea(tester, api: fake, size: size, brightness: brightness ?? Brightness.light);
  GoRouter.of(tester.element(find.byType(Navigator).first)).go('/tutor');
  await tester.pumpAndSettle();
  return fake;
}

Future<void> reply(WidgetTester tester, String text) async {
  await tester.enterText(input, text);
  await tester.pump();
  await tester.tap(sendButton);
  await tester.pumpAndSettle();
}

int steps(WidgetTester tester, StepKind kind) =>
    find.byWidgetPredicate((w) => w is StepPill && w.kind == kind).evaluate().length;

void main() {
  test('support pill wording', () {
    expect(supportLabel('procedural', 'medium'), 'Step-by-step · medium support');
    expect(supportLabel('conceptual', 'very_high'), 'Big ideas first · lots of support');
    expect(supportLabel('', 'low'), 'Light support');
    expect(supportLabel('', ''), 'Guided practice');
  });

  group('start panel', () {
    testWidgets('with no session: what the week covers, then Start opens the session', (tester) async {
      final api = await openTutor(tester);
      expect(find.text('Ready to learn: Week 1 · Introduction to AI'), findsOneWidget);
      expect(find.textContaining('11 objectives, 2 already mastered'), findsOneWidget);
      expect(find.textContaining('skip what you know'), findsOneWidget);
      expect(find.text("WHAT WE'LL COVER"), findsOneWidget);
      expect(find.text('AI Basics'), findsOneWidget);
      expect(find.text('2 of 4 mastered'), findsOneWidget); // part of a learning objective
      expect(find.text('3 objectives'), findsOneWidget);
      expect(find.text('4 objectives'), findsOneWidget);
      expect(find.text('Mastered'), findsNothing);

      await tester.tap(find.widgetWithText(FilledButton, 'Start Week 1'));
      await tester.pumpAndSettle();
      final start = api.requests.lastWhere((r) => r.url.path == '/tutor' && r.method == 'POST');
      expect(jsonDecode(start.body), {'course': 'DEMO101', 'week': 1});

      expect(find.text('OBJECTIVE 1 OF 11'), findsOneWidget);
      expect(find.text('AI BASICS'), findsOneWidget);
      expect(find.text('Definition Of AI'), findsOneWidget);
      expect(find.text('Step-by-step · medium support'), findsOneWidget);
      expect(find.textContaining('what do you already know', findRichText: true), findsOneWidget);
      expect(find.text(hint), findsOneWidget);
    });

    testWidgets('a learning objective that is fully mastered shows a check and the word Mastered', (tester) async {
      final api = FakeApi()..mastered[1] = 4; // all of "AI Basics"
      await openTutor(tester, api: api);
      expect(find.text('Mastered'), findsOneWidget);
      expect(find.byIcon(Icons.check_circle), findsOneWidget);
      expect(find.textContaining('11 objectives, 4 already mastered'), findsOneWidget);
      expect(find.bySemanticsLabel(RegExp(r'1\. AI Basics, mastered')), findsOneWidget);
    });

    testWidgets('a fully mastered week says there is no need to repeat the tutorial', (tester) async {
      final api = FakeApi()..mastered[1] = 11;
      await openTutor(tester, api: api);
      expect(find.text('Mastered'), findsNWidgets(3));
      expect(find.textContaining("you've mastered all of them"), findsOneWidget);
      expect(find.textContaining('take the quiz for a refresher'), findsOneWidget);
    });

    testWidgets('a session on another week is mentioned, and you can go back to it', (tester) async {
      final api = FakeApi(currentWeek: 2)..startTutor(week: 1);
      await openTutor(tester, api: api);
      expect(find.text('Ready to learn: Week 2 · Machine Learning Basics'), findsOneWidget);
      expect(find.text('You have a Week 1 session in progress. Starting Week 2 ends it.'), findsOneWidget);
      await tester.tap(find.widgetWithText(OutlinedButton, 'Back to Week 1'));
      await tester.pumpAndSettle();
      expect(find.text('Definition Of AI'), findsOneWidget);
    });
  });

  testWidgets('an existing session resumes on entry (GET /tutor)', (tester) async {
    final api = FakeApi()..startTutor(index: 2);
    await openTutor(tester, api: api);
    expect(find.text('OBJECTIVE 3 OF 11'), findsOneWidget);
    expect(find.text('AI Applications'), findsOneWidget);
  });

  testWidgets('step indicator: grouped by learning objective, mastered, current and the rest', (tester) async {
    final api = FakeApi()..startTutor(index: 2);
    await openTutor(tester, api: api);
    expect(steps(tester, StepKind.mastered), 2);
    expect(steps(tester, StepKind.current), 1);
    expect(steps(tester, StepKind.upcoming), 8);
    expect(find.bySemanticsLabel('Objective 3 of 11, 2 mastered'), findsOneWidget);
  });

  testWidgets('debug metrics pill shows mastery, cognitive load and ZPD', (tester) async {
    final api = FakeApi()..startTutor(index: 2);
    await openTutor(tester, api: api);
    expect(find.text('DEBUG · Mastery 36% · Load 4.35 · ZPD 0.50'), findsOneWidget);
  });

  testWidgets('debug metrics pill is hidden when a server sends none of these', (tester) async {
    final api = FakeApi()
      ..startTutor(index: 2)
      ..tutorObjectiveMastery = null
      ..tutorCognitiveLoad = null
      ..tutorZpdScore = null;
    await openTutor(tester, api: api);
    expect(find.textContaining('DEBUG'), findsNothing);
  });

  testWidgets('reply tags: warm-up first, then counted · correct or not yet; mastery refreshes', (tester) async {
    final api = FakeApi()..startTutor();
    api.mastered[1] = 0;
    await openTutor(tester, api: api);

    await reply(tester, 'I think AI means computers that learn');
    expect(find.text('Warm-up · not counted'), findsOneWidget);
    expect(find.text('OBJECTIVE 1 OF 11'), findsOneWidget);

    await reply(tester, 'Right: machines doing tasks that need intelligence');
    expect(find.text('Counted · correct'), findsOneWidget);
    expect(find.text('OBJECTIVE 2 OF 11'), findsOneWidget);
    expect(find.text('Types Of AI'), findsOneWidget);
    expect(steps(tester, StepKind.mastered), 1);
    expect(find.descendant(of: find.byType(Rail), matching: find.text('1 / 11')), findsOneWidget);

    await reply(tester, 'Maybe all AI is the same?');
    expect(find.text('Counted · not yet'), findsOneWidget);
    expect(find.text('OBJECTIVE 2 OF 11'), findsOneWidget);
  });

  testWidgets('a reply the tutor could not check shows Not counted, not Warm-up', (tester) async {
    final api = FakeApi()..startTutor();
    await openTutor(tester, api: api);

    // First reply: the warm-up, always ungraded.
    await reply(tester, 'I think AI means computers that learn');
    expect(find.text('Warm-up · not counted'), findsOneWidget);

    // Second reply: not the warm-up, but the tutor's question still couldn't be checked
    // (e.g. no valid recorded question about the current objective) -- distinct wording.
    api.tutorStream = StreamController<String>();
    await tester.enterText(input, 'A reply to an uncheckable tutor question');
    await tester.pump();
    await tester.tap(sendButton);
    await tester.pump();
    api.tutorStream!.add(FakeApi.sse('token', {'text': 'Let there be more to explore. '}));
    await tester.pump();
    api.tutorStream!.add(
      FakeApi.sse('done', api.tutorDone('A reply to an uncheckable tutor question', graded: false)),
    );
    await api.tutorStream!.close();
    await tester.pump();
    await tester.pump();

    expect(find.text('Not counted'), findsOneWidget);
    expect(find.text('Warm-up · not counted'), findsOneWidget); // the first tag is unchanged
    expect(find.text('OBJECTIVE 1 OF 11'), findsOneWidget); // an ungraded reply never advances
  });

  testWidgets('the reply streams with the cursor, and Send waits', (tester) async {
    final api = FakeApi()
      ..startTutor()
      ..tutorStream = StreamController<String>();
    await openTutor(tester, api: api);
    await tester.enterText(input, 'I know a little');
    await tester.pump();
    await tester.tap(sendButton);
    await tester.pump();

    expect(find.text('I know a little'), findsOneWidget);
    expect(find.byType(StreamingCursor), findsOneWidget);
    api.tutorStream!.add(FakeApi.sse('token', {'text': 'Nice start. '}));
    await tester.pump();
    expect(find.textContaining('Nice start.', findRichText: true), findsOneWidget);
    await tester.enterText(input, 'more');
    await tester.pump();
    expect(tester.widget<FilledButton>(sendButton).onPressed, isNull);

    api.tutorStream!.add(FakeApi.sse('done', api.tutorDone('I know a little', answer: 'Nice start. Tell me more.')));
    await api.tutorStream!.close();
    await tester.pump();
    await tester.pump();
    expect(find.byType(StreamingCursor), findsNothing);
    expect(find.textContaining('Nice start. Tell me more.', findRichText: true), findsOneWidget);
    expect(find.text('Warm-up · not counted'), findsOneWidget);
  });

  testWidgets('a failed reply puts the text back and shows the detail', (tester) async {
    final api = FakeApi()..startTutor();
    api.failures['/tutor/replies/stream'] = (
      503,
      {'detail': "LEA couldn't answer just now. Please try again.", 'code': 'Unavailable'},
      {},
    );
    await openTutor(tester, api: api);
    await reply(tester, 'Machines that learn');
    expect(find.text("LEA couldn't answer just now. Please try again."), findsOneWidget);
    expect(tester.widget<TextField>(input).controller!.text, 'Machines that learn');
    expect(find.text('Machines that learn'), findsOneWidget); // only in the input, not as a bubble
  });

  testWidgets('End session shows the summary, then the start panel', (tester) async {
    final api = FakeApi()..startTutor();
    await openTutor(tester, api: api);
    await reply(tester, 'warm-up answer');
    await reply(tester, 'right answer');

    await tester.tap(find.text('End session'));
    await tester.pumpAndSettle();
    expect(find.text('Session summary'), findsOneWidget);
    expect(find.text('1 / 11'), findsWidgets);
    expect(find.text('100%'), findsOneWidget);
    expect(find.text('2 replies in this session.'), findsOneWidget);

    await tester.tap(find.widgetWithText(FilledButton, 'Done'));
    await tester.pumpAndSettle();
    expect(find.text('Session summary'), findsNothing);
    expect(find.text('Ready to learn: Week 1 · Introduction to AI'), findsOneWidget);
  });

  testWidgets('finishing the last objective shows completion and follows the new week', (tester) async {
    final api = FakeApi()
      ..startTutor(index: 10)
      ..tutorAdvancesTo = 2;
    api.mastered[1] = 10;
    (api.tutor!['messages'] as List).add({'role': 'student', 'content': 'warm-up', 'timestamp': ''});
    await openTutor(tester, api: api);

    await reply(tester, 'Right: AI is broader than ML');
    expect(find.text('Every objective covered'), findsOneWidget);
    expect(find.bySemanticsLabel('Week 1 complete. Week 2 · Machine Learning Basics is now open.'), findsOneWidget);
    expect(find.byType(Composer), findsNothing);

    await tester.tap(find.widgetWithText(FilledButton, 'Go to Week 2'));
    await tester.pumpAndSettle();
    expect(find.text('Ready to learn: Week 2 · Machine Learning Basics'), findsOneWidget);
    expect(
      find.descendant(of: find.byType(Rail), matching: find.text('Opens when 75% of Week 2 is mastered')),
      findsOneWidget,
    );
  });

  testWidgets('finishing without moving on offers the quiz', (tester) async {
    final api = FakeApi()..startTutor(index: 10);
    (api.tutor!['messages'] as List).add({'role': 'student', 'content': 'warm-up', 'timestamp': ''});
    await openTutor(tester, api: api);
    await reply(tester, 'right');
    await tester.tap(find.widgetWithText(FilledButton, 'Take the Week 1 quiz'));
    await tester.pumpAndSettle();
    expect(find.byType(TutorScreen), findsNothing);
  });

  for (final brightness in Brightness.values) {
    for (final (name, size) in [('desktop', desktop), ('phone', phone)]) {
      testWidgets('session, $name, ${brightness.name}: lays out without overflow', (tester) async {
        final api = FakeApi()..startTutor(index: 2);
        await openTutor(tester, api: api, size: size, brightness: brightness);
        expect(find.byType(TutorHeader), findsOneWidget);
        expect(find.text(hint), size == desktop ? findsOneWidget : findsNothing);
        expect(tester.takeException(), isNull);
      });
    }
  }
}
