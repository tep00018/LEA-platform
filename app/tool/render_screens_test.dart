// Renders app screens with the bundled fonts at the design's frame sizes, to compare
// side by side with docs/design/screens/*.png. Not part of `flutter test`'s default run:
//
//   flutter test tool/render_screens_test.dart
//
// PNGs go to build/screens/ (or LEA_SCREENS_DIR), named like the design screenshots:
// <screen>-<desktop|phone>-<light|dark>.png. Uses the fake API from test/helpers.dart,
// filled with the same example content as the mockup.
import 'dart:async';
import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lea_app/app.dart';
import 'package:lea_app/auth/token_store.dart';
import 'package:lea_app/chat/chat_controller.dart';
import 'package:lea_app/course/course_state.dart';
import 'package:lea_app/providers.dart';
import 'package:lea_app/router.dart';
import 'package:lea_app/widgets/lea_avatar.dart';

import '../test/helpers.dart';

/// The design screenshots' frames: desktop 1224×680 (below the browser bar), phone 390×780
/// less the 8 px device border.
const frames = {'desktop': Size(1224, 680), 'phone': Size(374, 764)};

typedef Setup = ({
  String route,
  bool loggedIn,
  void Function(FakeApi api)? api,
  Future<void> Function(WidgetTester tester, ProviderContainer container, FakeApi api)? act,
});

final screens = <String, Setup>{
  'login': (route: '/login', loggedIn: false, api: null, act: null),
  'chat': (route: '/chat', loggedIn: true, api: _chatHistory, act: _chatStreaming),
  'chat-empty': (route: '/chat', loggedIn: true, api: null, act: null),
  'progress': (route: '/progress', loggedIn: true, api: _progress, act: null),
  'tutor': (route: '/tutor', loggedIn: true, api: _tutorSession, act: _tutorReply),
  'tutor-start': (route: '/tutor', loggedIn: true, api: null, act: null),
  'question': (route: '/quiz', loggedIn: true, api: _quizQuestion, act: _pickB),
  'feedback': (route: '/quiz', loggedIn: true, api: _quizFeedback, act: _answerWrong),
  'results': (route: '/quiz/results', loggedIn: true, api: _quizResults, act: _pinWeek1),
};

void _chatHistory(FakeApi api) {
  final t = DateTime(2026, 9, 24, 14, 2).millisecondsSinceEpoch / 1000;
  api.chatHistory.addAll([
    {'role': 'user', 'message': 'What is supervised learning?', 'timestamp': t},
    {
      'role': 'assistant',
      'message':
          'Supervised learning is when a model learns from **labelled examples**: each input comes with the right '
          'answer, and the model learns to predict that answer for new inputs.\n\nYour Week 1 notes contrast it '
          'with unsupervised learning, where there are no labels and the model looks for structure on its own.',
      'timestamp': t + 20,
    },
  ]);
  api.chatStream = StreamController<String>();
}

Future<void> _chatStreaming(WidgetTester tester, ProviderContainer container, FakeApi api) async {
  unawaited(container.read(chatProvider('DEMO101').notifier).send('Can you give an example?', 1));
  await tester.pump();
  api.chatStream!.add(
    FakeApi.sse('token', {
      'text':
          "A spam filter is a classic one. It's trained on emails that people have already marked as *spam* or "
          '*not spam*, and it learns which words and patterns go with each label',
    }),
  );
}

void _tutorSession(FakeApi api) {
  api
    ..mastered[1] = 1
    ..startTutor(index: 1)
    ..tutorCorrect = true
    ..tutorAnswer =
        "Both are real AI applications. Let's take face grouping one step at a time:\n\n"
        '1. The app finds the faces in each photo.\n2. It turns each face into a set of numbers.\n'
        '3. Faces with similar numbers go in the same group.\n\n'
        'What do you think the app had to learn before step 2 could work?';
  (api.tutor!['messages'] as List)
    ..add({'role': 'student', 'content': 'Some of it', 'timestamp': '2026-09-24T14:11:00'})
    ..add({
      'role': 'tutor',
      'content':
          'Nice work on types of AI. Next up is **AI applications**.\n\nWhere have you seen AI used in everyday '
          'life, and what job is it doing there?',
      'timestamp': '2026-09-24T14:12:00',
    });
}

/// Replies through the screen, as a student would.
Future<void> _tutorReply(WidgetTester tester, ProviderContainer container, FakeApi api) async {
  await tester.enterText(
    find.byType(TextField),
    "My phone's photo app groups pictures by face, and Netflix suggests shows I might like.",
  );
  await tester.pump();
  await tester.tap(find.widgetWithText(FilledButton, 'Send'));
  await tester.pumpAndSettle();
}

/// An 11-question plan like the mockup's: one per Week 1 objective.
List<Map<String, dynamic>> _plan() => [
  for (final (i, skill) in FakeApi.week1Skills.indexed)
    switch (i) {
      3 => {
        'type': 'multiple_choice',
        'text':
            "A hospital's AI system was trained on scans from one scanner model. Why might it perform worse on "
            'scans from a different hospital?',
        'options': [
          'A) The AI needs more computing power at the new hospital',
          'B) The new scans differ from the data the AI learned from',
          'C) AI systems stop learning after one year',
          'D) Doctors at the new hospital use it incorrectly',
        ],
        'skill_name': skill,
        'go_id': 'GO${i + 1}',
        'answer': 'B',
      },
      4 => {
        'type': 'multiple_choice',
        'text': "A chess program that beats grandmasters but can't do anything else is an example of…",
        'options': ['A) General AI', 'B) Narrow AI', 'C) Super AI', 'D) Reactive memory AI'],
        'explanation':
            'General AI would handle any intellectual task a person can. This program is excellent at one task '
            'only, which is what makes it narrow AI.',
        'skill_name': skill,
        'go_id': 'GO${i + 1}',
        'answer': 'B',
      },
      _ => {
        'type': 'multiple_choice',
        'text': 'Question about $skill',
        'options': ['A) One', 'B) Two'],
        'skill_name': skill,
        'go_id': 'GO${i + 1}',
        'answer': 'A',
      },
    },
];

Map<String, dynamic> _result(int i, bool? correct) => {
  'graded': correct != null,
  'correct': correct,
  'score': null,
  'explanation': '',
  'your_answer': 'A',
  'correct_answer': null,
  'achievements': <String>[],
  'go_id': 'GO${i + 1}',
};

void _quizQuestion(FakeApi api) {
  api
    ..quizPlan = _plan()
    ..startQuiz();
  api.quiz!['index'] = 3;
  (api.quiz!['results'] as List<Map<String, dynamic>>).addAll([_result(0, true), _result(1, true), _result(2, false)]);
}

void _quizFeedback(FakeApi api) {
  api
    ..quizPlan = _plan()
    ..startQuiz();
  api.quiz!['index'] = 4;
  (api.quiz!['results'] as List<Map<String, dynamic>>).addAll([
    _result(0, true),
    _result(1, true),
    _result(2, true),
    _result(3, false),
  ]);
}

void _quizResults(FakeApi api) {
  api
    ..quizPlan = _plan()
    ..startQuiz()
    ..currentWeek = 2
    ..mastered[1] = 9;
  const marks = [true, true, true, true, false, true, null, true, true, false, true];
  (api.quiz!['results'] as List<Map<String, dynamic>>).addAll([for (final (i, m) in marks.indexed) _result(i, m)]);
  api.quiz!
    ..['index'] = 10
    ..['status'] = 'completed'
    ..['advanced'] = 2;
}

Future<void> _pickB(WidgetTester tester, ProviderContainer container, FakeApi api) async {
  await tester.tap(find.text('The new scans differ from the data the AI learned from'));
  await tester.pumpAndSettle();
}

Future<void> _answerWrong(WidgetTester tester, ProviderContainer container, FakeApi api) async {
  await tester.tap(find.text('General AI'));
  await tester.pump();
  await tester.tap(find.widgetWithText(FilledButton, 'Submit answer'));
  await tester.pumpAndSettle();
}

Future<void> _pinWeek1(WidgetTester tester, ProviderContainer container, FakeApi api) async {
  container.read(selectionProvider.notifier).selectWeek(1);
  await tester.pumpAndSettle();
}

void _progress(FakeApi api) {
  api.objectiveValues.addAll({
    1: (0.82, 0.60),
    2: (0.74, 0.65),
    3: (0.41, 0.75),
    4: (null, 0.85),
    5: (null, 0.65),
    6: (null, 0.65),
    7: (null, 0.85),
    8: (null, 0.60),
    9: (null, 0.60),
    10: (null, 0.70),
    11: (null, 0.70),
  });
}

void main() {
  final outDir = Directory(Platform.environment['LEA_SCREENS_DIR'] ?? 'build/screens')..createSync(recursive: true);

  setUpAll(loadAppFonts);

  for (final MapEntry(key: frame, value: size) in frames.entries) {
    for (final brightness in Brightness.values) {
      for (final MapEntry(key: screen, value: setup) in screens.entries) {
        final name = '$screen-$frame-${brightness.name}';
        testWidgets(name, (tester) async {
          tester.view.physicalSize = size * 2;
          tester.view.devicePixelRatio = 2;
          tester.platformDispatcher.platformBrightnessTestValue = brightness;
          // Reduced motion keeps the streaming cursor still, so the screen can settle.
          tester.platformDispatcher.accessibilityFeaturesTestValue = const FakeAccessibilityFeatures(
            disableAnimations: true,
          );
          addTearDown(tester.view.reset);
          addTearDown(tester.platformDispatcher.clearPlatformBrightnessTestValue);
          addTearDown(tester.platformDispatcher.clearAccessibilityFeaturesTestValue);

          final api = FakeApi();
          setup.api?.call(api);
          final boundary = GlobalKey();
          final container = ProviderContainer(
            retry: noRetry,
            overrides: [
              httpClientProvider.overrideWithValue(api.client),
              tokenStoreProvider.overrideWithValue(MemoryTokenStore(setup.loggedIn ? validToken : null)),
              apiBaseUrlProvider.overrideWithValue('http://lea.test'),
            ],
          );
          addTearDown(container.dispose);

          await tester.pumpWidget(
            UncontrolledProviderScope(
              container: container,
              child: RepaintBoundary(key: boundary, child: const LeaApp()),
            ),
          );
          await tester.pumpAndSettle();
          if (setup.loggedIn) {
            container.read(routerProvider).go(setup.route);
            await tester.pumpAndSettle();
          }
          await setup.act?.call(tester, container, api);
          await tester.pump();

          // Decode the avatar for real before capturing.
          await tester.runAsync(() async {
            await precacheImage(const AssetImage(LeaAvatar.asset), tester.element(find.byType(LeaApp)));
          });
          await tester.pump();

          await tester.runAsync(() async {
            final render = boundary.currentContext!.findRenderObject()! as RenderRepaintBoundary;
            final image = await render.toImage(pixelRatio: 1);
            final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
            File('${outDir.path}/$name.png').writeAsBytesSync(bytes!.buffer.asUint8List());
          });

          await api.chatStream?.close();
        });
      }
    }
  }
}
