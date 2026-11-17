import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:lea_app/theme/lea_colors.dart';
import 'package:lea_app/theme/lea_theme.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import 'helpers.dart';

/// Every screen the app has, set up against the fake API.
final screens =
    <String, (String route, String? token, void Function(FakeApi) setup, Future<void> Function(WidgetTester)? act)>{
      'login': ('/login', null, (_) {}, null),
      'chat': (
        '/chat',
        validToken,
        (api) => api.chatHistory.addAll([
          {'role': 'user', 'message': 'What is supervised learning?', 'timestamp': 1790000000.0},
          {'role': 'assistant', 'message': 'It learns from **labelled examples**.', 'timestamp': 1790000005.0},
        ]),
        null,
      ),
      'chat-empty': ('/chat', validToken, (_) {}, null),
      'tutor-start': ('/tutor', validToken, (_) {}, null),
      'tutor': ('/tutor', validToken, (api) => api.startTutor(index: 2), null),
      'quiz-question': ('/quiz', validToken, (api) => api.startQuiz(), null),
      'quiz-feedback': (
        '/quiz',
        validToken,
        (api) => api.startQuiz(),
        (tester) async {
          await tester.tap(find.text('AI systems stop learning after one year'));
          await tester.pump();
          await tester.tap(find.widgetWithText(FilledButton, 'Submit answer'));
          await tester.pumpAndSettle();
        },
      ),
      'quiz-results': (
        '/quiz',
        validToken,
        (api) {
          api
            ..startQuiz()
            ..quizAdvancesTo = 2;
        },
        (tester) async {
          await tester.tap(find.text('End quiz'));
          await tester.pumpAndSettle();
        },
      ),
      'progress': (
        '/progress',
        validToken,
        (api) => api.objectiveValues.addAll({1: (0.82, 0.6), 3: (0.41, 0.75)}),
        null,
      ),
    };

Future<void> open(
  WidgetTester tester,
  String name, {
  Size size = desktop,
  Brightness brightness = Brightness.light,
  double textScale = 1,
}) async {
  final (route, token, setup, act) = screens[name]!;
  final api = FakeApi();
  setup(api);
  tester.platformDispatcher.textScaleFactorTestValue = textScale;
  addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
  await pumpLea(tester, api: api, token: token, size: size, brightness: brightness);
  if (token != null) {
    GoRouter.of(tester.element(find.byType(Navigator).first)).go(route);
    await tester.pumpAndSettle();
  }
  await act?.call(tester);
}

/// WCAG relative luminance of an sRGB colour.
double luminance(Color c) {
  double channel(double v) => v <= 0.03928 ? v / 12.92 : math.pow((v + 0.055) / 1.055, 2.4).toDouble();
  return 0.2126 * channel(c.r) + 0.7152 * channel(c.g) + 0.0722 * channel(c.b);
}

/// WCAG contrast ratio between two opaque colours.
double contrast(Color a, Color b) {
  final (hi, lo) = (math.max(luminance(a), luminance(b)), math.min(luminance(a), luminance(b)));
  return (hi + 0.05) / (lo + 0.05);
}

/// Every text colour on the tutor session screen, on the background it sits on.
List<(String, Color, Color)> tutorTextPairs(LeaColors c) => [
  ('title and kicker text on the header band', c.ink, c.bg),
  ('kicker, "End session", times, hint (muted) on bg', c.muted, c.bg),
  ('"Counted · correct" tag on bg', c.success, c.bg),
  ('support pill text on surface-2', c.ink, c.surface2),
  ("LEA's bubble text on surface", c.ink, c.surface),
  ("the student's bubble text on primary", c.onPrimary, c.primary),
  ('composer placeholder (muted) on surface', c.muted, c.surface),
  ('Send button text on primary', c.onPrimary, c.primary),
];

void main() {
  setUpAll(loadAppFonts);

  for (final name in screens.keys) {
    for (final brightness in Brightness.values) {
      testWidgets('$name, ${brightness.name}: text contrast and labelled tap targets', (tester) async {
        final handle = tester.ensureSemantics();
        await open(tester, name, brightness: brightness);
        // The tutor session is checked directly below instead: on Linux (CI) Flutter's
        // pixel-sampling guideline measures the header's "End session" link at its
        // position inside the header rather than on screen (always 4.01:1, whatever
        // the colour or widget), while Windows passes. See tutorTextPairs.
        if (name != 'tutor') await expectLater(tester, meetsGuideline(textContrastGuideline));
        await expectLater(tester, meetsGuideline(labeledTapTargetGuideline));
        handle.dispose();
      });
    }

    for (final (frame, size) in [('desktop', desktop), ('phone', phone)]) {
      testWidgets('$name, $frame: text at 200% lays out without clipping', (tester) async {
        await open(tester, name, size: size, textScale: 2);
        expect(tester.takeException(), isNull);
      });
    }
  }

  test('buttons show a 2 px focus ring: ink on filled buttons, primary on outlined and text', () {
    final theme = LeaTheme.light();
    final c = LeaColors.light;
    final focused = {WidgetState.focused};
    expect(theme.filledButtonTheme.style!.side!.resolve(focused), BorderSide(color: c.ink, width: 2));
    expect(theme.filledButtonTheme.style!.side!.resolve({}), isNull);
    expect(theme.outlinedButtonTheme.style!.side!.resolve(focused), BorderSide(color: c.primary, width: 2));
    expect(theme.textButtonTheme.style!.side!.resolve(focused), BorderSide(color: c.primary, width: 2));
  });

  testWidgets('custom controls show the offset ring when reached with Tab', (tester) async {
    await pumpLea(tester);
    Finder ring() => find.byWidgetPredicate(
      (w) =>
          w is DecoratedBox &&
          w.decoration is BoxDecoration &&
          (w.decoration as BoxDecoration).border == Border.all(color: LeaColors.light.primary, width: 2),
    );
    expect(ring(), findsNothing);
    for (var i = 0; i < 15 && ring().evaluate().isEmpty; i++) {
      await tester.sendKeyEvent(LogicalKeyboardKey.tab);
      await tester.pumpAndSettle();
    }
    expect(ring(), findsOneWidget);
  });

  for (final (theme, colors) in [('light', LeaColors.light), ('dark', LeaColors.dark)]) {
    test('tutor session, $theme: every text colour meets 4.5:1 on its background', () {
      for (final (what, text, background) in tutorTextPairs(colors)) {
        expect(contrast(text, background), greaterThanOrEqualTo(4.5), reason: what);
      }
    });
  }

  test('the contrast helper matches known WCAG values', () {
    expect(contrast(const Color(0xFF000000), const Color(0xFFFFFFFF)), closeTo(21, 0.01));
    expect(contrast(const Color(0xFF777777), const Color(0xFFFFFFFF)), closeTo(4.48, 0.01));
  });
}
