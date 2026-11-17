import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:lea_app/api/models.dart';
import 'package:lea_app/screens/quiz/question_panel.dart';
import 'package:lea_app/screens/quiz/results_view.dart';
import 'package:lea_app/screens/tutor/tutor_screen.dart';
import 'package:lea_app/shell/bottom_nav.dart';
import 'package:lea_app/shell/mode_tabs.dart';
import 'package:lea_app/shell/rail.dart';
import 'package:lea_app/shell/top_bar.dart';
import 'package:lea_app/theme/lea_type.dart';

import 'helpers.dart';

Finder button(String label) => find.widgetWithText(FilledButton, label);

Future<FakeApi> openQuiz(WidgetTester tester, {FakeApi? api, Size size = desktop, Brightness? brightness}) async {
  final fake = api ?? FakeApi();
  await pumpLea(tester, api: fake, size: size, brightness: brightness ?? Brightness.light);
  GoRouter.of(tester.element(find.byType(Navigator).first)).go('/quiz');
  await tester.pumpAndSettle();
  return fake;
}

String location(WidgetTester tester) =>
    GoRouter.of(tester.element(find.byType(Navigator).first)).routeInformationProvider.value.uri.path;

OptionLook lookOf(WidgetTester tester, String text) =>
    tester.widget<OptionCard>(find.widgetWithText(OptionCard, text)).look;

Future<void> tapAndSettle(WidgetTester tester, Finder f) async {
  await tester.ensureVisible(f);
  await tester.tap(f);
  await tester.pumpAndSettle();
}

List<Map<String, dynamic>> answersSent(FakeApi api) => [
  for (final r in api.requests.where((r) => r.url.path == '/quiz/answer')) jsonDecode(r.body) as Map<String, dynamic>,
];

void main() {
  test('score line', () {
    QuizView quiz(int correct, int graded, List<bool?> results) => QuizView(
      quizId: 'q',
      course: 'DEMO101',
      week: 1,
      status: 'completed',
      position: 1,
      total: results.length,
      correctCount: correct,
      gradedCount: graded,
      results: [for (final r in results) QuizFeedback(graded: r != null, correct: r, score: null, explanation: '')],
    );
    expect(
      scoreSummary(quiz(8, 10, [...List.filled(8, true), false, false, null])),
      "80% of graded answers correct. One answer couldn't be graded and isn't counted.",
    );
    expect(scoreSummary(quiz(1, 2, [true, false, null, null])), contains("2 answers couldn't be graded"));
    expect(scoreSummary(quiz(0, 0, [null])), "None of your answers could be graded, so this quiz doesn't count.");
    expect(scoreSummary(quiz(0, 0, [])), 'You ended the quiz before answering any questions.');
  });

  test('options: letters from "A) text", or A, B, … when unlabelled', () {
    const q = QuizQuestion(number: 1, type: 'multiple_choice', text: '', options: ['A) One', '(b) Two', 'Three']);
    expect(q.choices.map((c) => (c.letter, c.text)), [('A', 'One'), ('B', 'Two'), ('C', 'Three')]);
  });

  testWidgets('start panel, then Start opens the first question', (tester) async {
    final api = await openQuiz(tester);
    expect(find.text('Check yourself: Week 1 · Introduction to AI'), findsOneWidget);
    await tester.tap(button('Start Week 1 quiz'));
    await tester.pumpAndSettle();
    final start = api.requests.lastWhere((r) => r.url.path == '/quiz' && r.method == 'POST');
    expect(jsonDecode(start.body), {'course': 'DEMO101', 'week': 1});

    expect(find.text('Question 1 of 4 · AI Basics', findRichText: true), findsOneWidget);
    expect(find.text('Correct so far 0 / 0', findRichText: true), findsOneWidget);
    expect(find.text('MULTIPLE CHOICE'), findsOneWidget);
    expect(find.text('AI LIMITATIONS'), findsOneWidget);
    // The "B) " prefix becomes the letter chip.
    expect(find.text('The new scans differ from the data the AI learned from'), findsOneWidget);
    expect(find.text('B'), findsOneWidget);
  });

  group('multiple choice', () {
    testWidgets('nothing is sent until Submit; Submit waits for a choice', (tester) async {
      final api = FakeApi()..startQuiz();
      await openQuiz(tester, api: api);
      expect(tester.widget<FilledButton>(button('Submit answer')).onPressed, isNull);

      await tester.tap(find.text('The AI needs more computing power at the new hospital'));
      await tester.pump();
      await tester.tap(find.text('The new scans differ from the data the AI learned from'));
      await tester.pump();
      expect(lookOf(tester, 'The new scans differ from the data the AI learned from'), OptionLook.selected);
      expect(lookOf(tester, 'The AI needs more computing power at the new hospital'), OptionLook.idle);
      expect(answersSent(api), isEmpty);

      await tester.tap(button('Submit answer'));
      await tester.pumpAndSettle();
      expect(answersSent(api), [
        {'answer': 'B'},
      ]);
    });

    testWidgets('a right answer: "Correct.", the choice marked as your answer, count goes up', (tester) async {
      final api = FakeApi()..startQuiz();
      await openQuiz(tester, api: api);
      await tester.tap(find.text('The new scans differ from the data the AI learned from'));
      await tester.pump();
      await tester.tap(button('Submit answer'));
      await tester.pumpAndSettle();

      expect(find.text('Correct.'), findsOneWidget);
      expect(lookOf(tester, 'The new scans differ from the data the AI learned from'), OptionLook.right);
      expect(find.text('Your answer'), findsOneWidget);
      expect(find.text('Correct so far 1 / 1', findRichText: true), findsOneWidget);
      expect(button('Next question'), findsOneWidget);
      // The rail's count follows the new mastery.
      expect(find.descendant(of: find.byType(Rail), matching: find.text('3 / 11')), findsOneWidget);
    });

    testWidgets('a wrong answer: yours on danger, the right one on success, "Not quite."', (tester) async {
      final api = FakeApi()..startQuiz();
      await openQuiz(tester, api: api);
      await tester.tap(find.text('AI systems stop learning after one year'));
      await tester.pump();
      await tester.tap(button('Submit answer'));
      await tester.pumpAndSettle();

      expect(find.text('Not quite.'), findsOneWidget);
      expect(lookOf(tester, 'AI systems stop learning after one year'), OptionLook.wrong);
      expect(lookOf(tester, 'The new scans differ from the data the AI learned from'), OptionLook.right);
      expect(find.text('Your answer'), findsOneWidget);
      expect(find.text('Correct answer'), findsOneWidget);
      expect(find.textContaining('New scans can differ', findRichText: true), findsOneWidget);
      // Answered options can't be changed.
      await tester.tap(find.text('The AI needs more computing power at the new hospital'));
      await tester.pump();
      expect(answersSent(api), hasLength(1));
    });
  });

  testWidgets('true/false: two large cards', (tester) async {
    final api = FakeApi()..startQuiz();
    api.quiz!['index'] = 1;
    await openQuiz(tester, api: api);
    expect(find.text('TRUE OR FALSE'), findsOneWidget);
    expect(find.widgetWithText(OptionCard, 'True'), findsOneWidget);
    expect(find.widgetWithText(OptionCard, 'False'), findsOneWidget);
    await tester.tap(find.text('False'));
    await tester.pump();
    await tester.tap(button('Submit answer'));
    await tester.pumpAndSettle();
    expect(answersSent(api).single, {'answer': 'False'});
    expect(lookOf(tester, 'False'), OptionLook.wrong);
    expect(lookOf(tester, 'True'), OptionLook.right);
  });

  testWidgets('fill in the blank: one input; Enter submits', (tester) async {
    final api = FakeApi()..startQuiz();
    api.quiz!['index'] = 2;
    await openQuiz(tester, api: api);
    expect(find.text('FILL IN THE BLANK'), findsOneWidget);
    await tester.enterText(find.byType(TextField), 'labelled');
    await tester.testTextInput.receiveAction(TextInputAction.done);
    await tester.pumpAndSettle();
    expect(answersSent(api).single, {'answer': 'labelled'});
    expect(find.text('Correct.'), findsOneWidget);
  });

  testWidgets('open answer: at least 10 characters, code in monospace, "Couldn\'t grade this one"', (tester) async {
    final api = FakeApi()..startQuiz();
    api.quiz!['index'] = 3;
    await openQuiz(tester, api: api);
    expect(find.text('OPEN ANSWER'), findsOneWidget);

    // The code block renders in the monospace font.
    final code = tester.widget<RichText>(
      find.byWidgetPredicate((w) => w is RichText && w.text.toPlainText().contains('model.fit(examples, labels)')),
    );
    expect((code.text as TextSpan).style!.fontFamily, LeaType.monoFamily);

    await tester.enterText(find.byType(TextField), 'AI is big');
    await tester.pump();
    expect(find.text('9 characters · at least 10'), findsOneWidget);
    expect(tester.widget<FilledButton>(button('Submit answer')).onPressed, isNull);

    await tester.enterText(find.byType(TextField), 'ML is one way to build AI.');
    await tester.pump();
    await tapAndSettle(tester, button('Submit answer'));
    expect(find.text("Couldn't grade this one"), findsOneWidget);
    expect(find.textContaining("This answer doesn't count towards your score.", findRichText: true), findsOneWidget);
    // Last question: move on to the results.
    expect(button('See results'), findsOneWidget);
  });

  testWidgets('a whole quiz: results at /quiz/results with score, list and actions', (tester) async {
    final api = FakeApi()..startQuiz();
    await openQuiz(tester, api: api);

    await tester.tap(find.text('The new scans differ from the data the AI learned from'));
    await tester.pump();
    await tapAndSettle(tester, button('Submit answer'));
    await tapAndSettle(tester, button('Next question'));
    await tester.tap(find.text('True'));
    await tester.pump();
    await tapAndSettle(tester, button('Submit answer'));
    await tapAndSettle(tester, button('Next question'));
    await tester.enterText(find.byType(TextField), 'labelled');
    await tester.pump();
    await tapAndSettle(tester, button('Submit answer'));
    await tapAndSettle(tester, button('Next question'));
    await tester.enterText(find.byType(TextField), 'Machine learning is part of AI.');
    await tester.pump();
    await tapAndSettle(tester, button('Submit answer'));
    await tapAndSettle(tester, button('See results'));

    expect(location(tester), '/quiz/results');
    expect(find.bySemanticsLabel('3 out of 3 correct'), findsOneWidget);
    expect(
      find.text("100% of graded answers correct. One answer couldn't be graded and isn't counted."),
      findsOneWidget,
    );
    expect(find.text('AI Limitations'), findsOneWidget);
    expect(find.text('AI Basics'), findsOneWidget);
    expect(find.text('Correct'), findsNWidgets(3));
    expect(find.text('Not counted'), findsOneWidget);
    // No tab is active on the results page.
    final tabs = tester.widget<ModeTabs>(find.byType(ModeTabs));
    expect(tabs.active, isNull);

    await tapAndSettle(tester, button('Start a new quiz'));
    expect(api.requests.any((r) => r.url.path == '/quiz' && r.method == 'DELETE'), isTrue);
    expect(find.text('Question 1 of 4 · AI Basics', findRichText: true), findsOneWidget);
    expect(location(tester), '/quiz');
  });

  testWidgets('End quiz early shows the results so far; Review with the tutor goes to Tutor', (tester) async {
    final api = FakeApi()..startQuiz();
    await openQuiz(tester, api: api);
    await tester.tap(find.text('AI systems stop learning after one year'));
    await tester.pump();
    await tapAndSettle(tester, button('Submit answer'));
    await tapAndSettle(tester, find.text('End quiz'));

    expect(find.bySemanticsLabel('0 out of 1 correct'), findsOneWidget);
    expect(find.text('Incorrect'), findsOneWidget);
    await tapAndSettle(tester, find.widgetWithText(OutlinedButton, 'Review with the tutor'));
    expect(find.byType(TutorScreen), findsOneWidget);
    final start = api.requests.lastWhere((r) => r.url.path == '/tutor' && r.method == 'POST');
    expect(jsonDecode(start.body), {'course': 'DEMO101', 'week': 1, 'review_quiz': true});
    expect(find.textContaining("Let's go over your Week 1 quiz"), findsOneWidget);
  });

  testWidgets('a quiz that moves the student on: banner, and Start Week 2 quiz', (tester) async {
    final api = FakeApi()
      ..startQuiz()
      ..quizAdvancesTo = 2;
    await openQuiz(tester, api: api);
    await tester.tap(find.text('The new scans differ from the data the AI learned from'));
    await tester.pump();
    await tapAndSettle(tester, button('Submit answer'));
    await tapAndSettle(tester, find.text('End quiz'));

    expect(find.bySemanticsLabel('Week 1 complete. Week 2 · Machine Learning Basics is now open.'), findsOneWidget);
    await tapAndSettle(tester, button('Start Week 2 quiz'));
    final start = api.requests.lastWhere((r) => r.url.path == '/quiz' && r.method == 'POST');
    expect(jsonDecode(start.body), {'course': 'DEMO101', 'week': 2});
    expect(
      find.descendant(of: find.byType(Rail), matching: find.text('Opens when 75% of Week 2 is mastered')),
      findsOneWidget,
    );
  });

  testWidgets('a quiz in progress resumes on entry', (tester) async {
    final api = FakeApi()..startQuiz();
    api.quiz!['index'] = 1;
    await openQuiz(tester, api: api);
    expect(find.text('Question 2 of 4 · AI Types Overview', findRichText: true), findsOneWidget);
  });

  testWidgets('reopened mid-feedback (no question from the API): your answer and the feedback', (tester) async {
    final api = FakeApi()..startQuiz();
    await openQuiz(tester, api: api);
    await tester.tap(find.text('AI systems stop learning after one year'));
    await tester.pump();
    await tapAndSettle(tester, button('Submit answer'));

    // A fresh app over the same server state.
    await tester.pumpWidget(const SizedBox());
    await pumpLea(tester, api: api);
    GoRouter.of(tester.element(find.byType(Navigator).first)).go('/quiz');
    await tester.pumpAndSettle();
    expect(find.text('Your answer: C'), findsOneWidget);
    expect(find.text('Not quite.'), findsOneWidget);
    expect(button('Next question'), findsOneWidget);
  });

  testWidgets('a failed answer shows the detail and keeps the choice to try again', (tester) async {
    final api = FakeApi()..startQuiz();
    api.failures['/quiz/answer'] = (
      503,
      {'detail': "Your answer couldn't be checked. Please submit it again.", 'code': 'Unavailable'},
      {},
    );
    await openQuiz(tester, api: api);
    await tester.tap(find.text('The new scans differ from the data the AI learned from'));
    await tester.pump();
    await tapAndSettle(tester, button('Submit answer'));
    expect(find.text("Your answer couldn't be checked. Please submit it again."), findsOneWidget);
    expect(lookOf(tester, 'The new scans differ from the data the AI learned from'), OptionLook.selected);

    api.failures.clear();
    await tapAndSettle(tester, button('Submit answer'));
    expect(find.text('Correct.'), findsOneWidget);
  });

  testWidgets('a quiz on another week is mentioned on the start panel', (tester) async {
    final api = FakeApi(currentWeek: 2)..startQuiz(week: 1);
    await openQuiz(tester, api: api);
    expect(find.textContaining('You have a Week 1 quiz in progress (question 1 of 4)'), findsOneWidget);
    await tapAndSettle(tester, find.widgetWithText(OutlinedButton, 'Back to Week 1'));
    expect(find.text('MULTIPLE CHOICE'), findsOneWidget);
  });

  for (final brightness in Brightness.values) {
    for (final (name, size) in [('desktop', desktop), ('phone', phone)]) {
      testWidgets('question, feedback and results, $name, ${brightness.name}: no overflow', (tester) async {
        final api = FakeApi()..startQuiz();
        await openQuiz(tester, api: api, size: size, brightness: brightness);
        expect(tester.takeException(), isNull);
        await tester.tap(find.text('AI systems stop learning after one year'));
        await tester.pump();
        await tapAndSettle(tester, button('Submit answer'));
        expect(tester.takeException(), isNull);
        await tapAndSettle(tester, find.text('End quiz'));
        expect(tester.takeException(), isNull);
        if (size == phone) {
          expect(find.descendant(of: find.byType(TopBar), matching: find.text('Quiz results')), findsOneWidget);
          expect(tester.widget<BottomNav>(find.byType(BottomNav)).active, isNull);
        }
      });
    }
  }
}
