import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:lea_app/screens/progress/progress_screen.dart';
import 'package:lea_app/shell/bottom_nav.dart';
import 'package:lea_app/shell/mode.dart';
import 'package:lea_app/shell/rail.dart';
import 'package:lea_app/theme/lea_colors.dart';

import 'helpers.dart';

Future<FakeApi> openProgress(WidgetTester tester, {FakeApi? api, Size size = desktop, Brightness? brightness}) async {
  final fake = api ?? FakeApi();
  await pumpLea(tester, api: fake, size: size, brightness: brightness ?? Brightness.light);
  GoRouter.of(tester.element(find.byType(Navigator).first)).go('/progress');
  await tester.pumpAndSettle();
  return fake;
}

/// The design's example: two mastered, one in progress, the rest not assessed.
FakeApi designApi({int currentWeek = 1}) =>
    FakeApi(currentWeek: currentWeek)
      ..objectiveValues.addAll({1: (0.82, 0.60), 2: (0.74, 0.65), 3: (0.41, 0.75), 4: (null, 0.85)});

Finder rowFor(String skill) => find.byWidgetPredicate((w) => w is ObjectiveRow && w.objective.skillName == skill);

void main() {
  testWidgets('week cards: current with its percentage, locked ones say when they open', (tester) async {
    await openProgress(tester, api: designApi());
    expect(find.text('Current'), findsOneWidget);
    expect(find.text('18%'), findsOneWidget);
    expect(find.text('2 of 11 mastered'), findsOneWidget);
    expect(find.text('Locked'), findsNWidgets(2));
    expect(find.text('Opens at 75% of Week 1'), findsOneWidget);
    expect(find.text('Opens after Week 2'), findsOneWidget);
    expect(find.text('Machine Learning Basics'), findsOneWidget);
  });

  testWidgets('legend, learning objectives and each objective against its threshold', (tester) async {
    await openProgress(tester, api: designApi());
    for (final label in ['Mastered', 'In progress', 'Threshold']) {
      expect(find.text(label), findsOneWidget);
    }
    for (final lo in ['AI Basics', 'AI Types Overview', 'AI vs ML Distinction']) {
      expect(find.text(lo), findsOneWidget);
    }
    expect(find.text('0.82 / 0.60', findRichText: true), findsOneWidget);
    expect(find.text('0.41 / 0.75', findRichText: true), findsOneWidget);
    expect(find.text('– / 0.85', findRichText: true), findsOneWidget);
    expect(find.bySemanticsLabel('Definition Of AI: mastery 0.82, needs 0.60, mastered'), findsOneWidget);
    expect(find.bySemanticsLabel('AI Limitations: not assessed yet, needs 0.85, in progress'), findsOneWidget);
  });

  testWidgets('gauges: primary when mastered, accent otherwise, tick at the threshold', (tester) async {
    await openProgress(tester, api: designApi());
    final c = LeaColors.light;

    Color fill(String skill) =>
        ((tester
                    .widget<Container>(
                      find.descendant(of: rowFor(skill), matching: find.byKey(const ValueKey('gauge-fill'))),
                    )
                    .decoration!)
                as BoxDecoration)
            .color!;
    expect(fill('Definition Of AI'), c.primary);
    expect(fill('AI Applications'), c.accent);

    final gauge = tester.getRect(find.descendant(of: rowFor('AI Applications'), matching: find.byType(Gauge)));
    final fillRect = tester.getRect(
      find.descendant(of: rowFor('AI Applications'), matching: find.byKey(const ValueKey('gauge-fill'))),
    );
    final tick = tester.getRect(
      find.descendant(of: rowFor('AI Applications'), matching: find.byKey(const ValueKey('gauge-tick'))),
    );
    expect(fillRect.width / gauge.width, closeTo(0.41, 0.01));
    expect((tick.center.dx - gauge.left) / gauge.width, closeTo(0.75, 0.01));
  });

  testWidgets('values stay on one line on desktop', (tester) async {
    await openProgress(tester, api: designApi());
    final value = find.descendant(
      of: rowFor('Definition Of AI'),
      matching: find.text('0.82 / 0.60', findRichText: true),
    );
    expect(tester.getSize(value).height, lessThan(24));
  });

  testWidgets('an earlier week can be opened from its card', (tester) async {
    final api = designApi(currentWeek: 2)..mastered[2] = 3;
    await openProgress(tester, api: api);
    expect(find.text('Completed'), findsOneWidget);
    expect(find.text('Current'), findsOneWidget);
    expect(find.text('Definition Of AI'), findsNothing); // week 2 has no objectives in the fake

    await tester.tap(find.text('Introduction to AI'));
    await tester.pumpAndSettle();
    expect(find.text('Definition Of AI'), findsOneWidget);
    expect(find.descendant(of: find.byType(Rail), matching: find.text('2 / 11')), findsOneWidget);
  });

  for (final (name, size) in [('desktop', desktop), ('phone', phone)]) {
    testWidgets('$name: a failed load says why in the content area and retries', (tester) async {
      final api = designApi();
      api.failures['/courses/DEMO101/mastery'] = (
        503,
        {'detail': 'LEA is having trouble right now. Try again in a minute.', 'code': 'Unavailable'},
        {},
      );
      await openProgress(tester, api: api, size: size);
      final message = find.text('LEA is having trouble right now. Try again in a minute.');
      // On desktop the rail says it too; on a phone the content area is the only place.
      expect(message, size == desktop ? findsNWidgets(2) : findsOneWidget);

      api.failures.clear();
      await tester.tap(find.text('Try again').last);
      await tester.pumpAndSettle();
      expect(message, findsNothing);
      expect(find.text('0.82 / 0.60', findRichText: true), findsOneWidget);
    });
  }

  testWidgets('desktop: rail link active, cards in one row', (tester) async {
    await openProgress(tester, api: designApi());
    final cards = [
      for (final t in ['Introduction to AI', 'Machine Learning Basics', 'Neural Networks'])
        tester.getRect(find.text(t)),
    ];
    expect(cards.map((r) => r.top.round()).toSet(), hasLength(1));
  });

  for (final brightness in Brightness.values) {
    for (final (name, size) in [('desktop', desktop), ('phone', phone)]) {
      testWidgets('$name, ${brightness.name}: no overflow', (tester) async {
        await openProgress(tester, api: designApi(), size: size, brightness: brightness);
        expect(tester.takeException(), isNull);
        if (size == phone) {
          expect(tester.widget<BottomNav>(find.byType(BottomNav)).active, Mode.progress);
          // Cards stack on phones.
          final a = tester.getRect(find.text('Introduction to AI'));
          final b = tester.getRect(find.text('Machine Learning Basics'));
          expect(b.top, greaterThan(a.bottom));
        }
      });
    }
  }
}
