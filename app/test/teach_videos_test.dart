import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:lea_app/teach/teach_shell.dart';
import 'package:lea_app/teach/teach_widgets.dart';

import 'helpers.dart';

const wide = Size(1300, 1000);
const first = 'GO_01_01_001';
const second = 'GO_01_01_002';
const third = 'GO_02_02_001';

Future<FakeApi> open(WidgetTester tester, String path, {Size size = wide, void Function(FakeTeach)? setup}) async {
  final teach = FakeTeach();
  setup?.call(teach);
  final api = FakeApi()
    ..role = 'teacher'
    ..teach = teach;
  await pumpLea(tester, api: api, size: size);
  GoRouter.of(tester.element(find.byType(Navigator).first)).go(path);
  await tester.pumpAndSettle();
  return api;
}

String location(WidgetTester tester) =>
    GoRouter.of(tester.element(find.byType(Navigator).first)).routeInformationProvider.value.uri.path;

Future<void> pick(WidgetTester tester, String current, String option) async {
  await tester.tap(find.text(current));
  await tester.pumpAndSettle();
  await tester.tap(find.text(option).last, warnIfMissed: false);
  await tester.pumpAndSettle();
}

Map<String, dynamic> video(String id, {String note = ''}) => {
  'id': id,
  'url': 'https://www.youtube.com/watch?v=$id',
  'title': 'Title of $id',
  'channel': 'A Channel',
  'note': note,
  'added_by': 'alex.m',
  'added_at': '2026-09-12T10:00:00+00:00',
};

String link(String id) => 'https://youtu.be/$id';

void main() {
  group('overview', () {
    testWidgets('shows what a stuck student gets for each objective, and where students are stuck first', (
      tester,
    ) async {
      await open(
        tester,
        '/teach/courses/AIML101/videos',
        setup: (t) {
          t.videos['AIML101'] = {
            first: [video('vid00000001'), video('vid00000002')],
          };
          t.helpShown[first] = 14;
          t.helpShown[second] = 11;
          t.helpShown[third] = null; // 1 to 4 students: withheld
          t.helpShownTimes = 212;
        },
      );
      expect(
        find.descendant(of: find.byType(TeachHeader), matching: find.text('Videos for stuck students')),
        findsOneWidget,
      );
      expect(find.textContaining('1 of 4 objectives have your videos'), findsOneWidget);
      expect(find.text('2 of 5'), findsOneWidget);
      expect(find.text('Your videos'), findsWidgets);
      expect(find.text('Automatic search'), findsNWidgets(3));
      expect(find.text('212'), findsOneWidget);
      expect(find.text('times help was shown · 30 days'), findsOneWidget);
      expect(find.text('14'), findsOneWidget);
      expect(find.text('11'), findsOneWidget);
      expect(find.text('< 5'), findsOneWidget); // withheld
      expect(find.text('—'), findsOneWidget); // nobody was shown help
      // Most students shown help first.
      double top(String go) => tester.getTopLeft(find.byKey(Key('video-row-$go'))).dy;
      expect(top(first), lessThan(top(second)));
      expect(top(second), lessThan(top(third)));
      expect(top(third), lessThan(top('GO_02_02_002')));
      expect(find.widgetWithText(OutlinedButton, 'Edit videos'), findsOneWidget);
      expect(find.widgetWithText(OutlinedButton, 'Add videos'), findsNWidgets(3));
    });

    testWidgets('says when automatic search is paused, and what students get meanwhile', (tester) async {
      await open(
        tester,
        '/teach/courses/AIML101/videos',
        setup: (t) => t.quotaPausedUntil = DateTime.now().toUtc().add(const Duration(hours: 7)).toIso8601String(),
      );
      expect(find.textContaining('Automatic YouTube search is paused'), findsOneWidget);
      expect(find.textContaining("Google's daily quota is used up"), findsOneWidget);
      expect(find.text('Search links'), findsNWidgets(4));
      expect(find.text('search paused'), findsNWidgets(4));
      expect(find.text('Automatic search'), findsNothing);
    });

    testWidgets('says when there is no API key', (tester) async {
      await open(tester, '/teach/courses/AIML101/videos', setup: (t) => t.searchEnabled = false);
      expect(find.textContaining("Automatic YouTube search isn't set up"), findsOneWidget);
      expect(find.text('search not set up'), findsNWidgets(4));
    });

    testWidgets('filters by week and by whether the objective has videos', (tester) async {
      await open(
        tester,
        '/teach/courses/AIML101/videos',
        setup: (t) => t.videos['AIML101'] = {
          third: [video('vid00000003')],
        },
      );
      await pick(tester, 'All weeks', 'Week 2');
      expect(find.byKey(const Key('video-row-$first')), findsNothing);
      expect(find.byKey(const Key('video-row-$third')), findsOneWidget);
      await pick(tester, 'All objectives', 'Without videos');
      expect(find.byKey(const Key('video-row-$third')), findsNothing);
      expect(find.byKey(const Key('video-row-GO_02_02_002')), findsOneWidget);
      await pick(tester, 'Without videos', 'With videos');
      expect(find.byKey(const Key('video-row-$third')), findsOneWidget);
      expect(find.byKey(const Key('video-row-GO_02_02_002')), findsNothing);
      await pick(tester, 'Week 2', 'Week 1'); // nothing in week 1 has videos
      expect(find.text('No objectives match this filter.'), findsOneWidget);
    });

    testWidgets('opens an objective from its row or its button', (tester) async {
      await open(tester, '/teach/courses/AIML101/videos');
      await tester.tap(find.widgetWithText(OutlinedButton, 'Add videos').first);
      await tester.pumpAndSettle();
      expect(location(tester), startsWith('/teach/courses/AIML101/videos/GO_'));
    });

    testWidgets('the rail links to Videos and counts the objectives that have them', (tester) async {
      await open(
        tester,
        '/teach/courses/AIML101/audit',
        setup: (t) => t.videos['AIML101'] = {
          first: [video('vid00000001')],
          second: [video('vid00000002')],
        },
      );
      expect(find.descendant(of: find.byType(TeachRail), matching: find.text('2')), findsOneWidget);
      await tester.tap(find.descendant(of: find.byType(TeachRail), matching: find.text('Videos')));
      await tester.pumpAndSettle();
      expect(location(tester), '/teach/courses/AIML101/videos');
    });

    testWidgets('a phone is read-only', (tester) async {
      await open(tester, '/teach/courses/AIML101/videos', size: const Size(400, 900));
      expect(find.text('Open LEA on a computer to edit. On a phone you can follow progress.'), findsOneWidget);
      expect(find.widgetWithText(OutlinedButton, 'Add videos'), findsNothing);
    });
  });

  group('one objective', () {
    const path = '/teach/courses/AIML101/videos/$first';

    testWidgets('adds a video from a link, with a note, and shows what a student sees', (tester) async {
      final api = await open(tester, path);
      expect(
        find.text(
          'No videos yet. Students who get stuck see a search result instead. Paste a YouTube link to choose what they see.',
        ),
        findsOneWidget,
      );
      expect(find.textContaining('A search result for this objective'), findsOneWidget);

      await tester.enterText(find.byKey(const Key('video-url')), link('vid00000001'));
      await tester.enterText(find.byKey(const Key('video-note')), 'Watch from 3:20');
      await tester.tap(find.byKey(const Key('add-video')));
      await tester.pumpAndSettle();

      expect(api.teach!.videos['AIML101']![first]!.single['note'], 'Watch from 3:20');
      expect(find.text('Title of vid00000001'), findsOneWidget);
      expect(find.text('Note: Watch from 3:20'), findsOneWidget);
      expect(find.textContaining('1 of 5 · the first three are shown'), findsOneWidget);
      // The preview is what the tutor shows: a numbered list with the note under it.
      expect(find.text('1. Title of vid00000001'), findsOneWidget);
      expect(find.text('Watch from 3:20'), findsOneWidget);
      // The fields are cleared for the next one.
      expect(tester.widget<TextField>(find.byKey(const Key('video-url'))).controller!.text, '');
    });

    testWidgets('says what is wrong with a link, in plain words, under the field', (tester) async {
      await open(tester, path);
      await tester.enterText(find.byKey(const Key('video-url')), 'https://vimeo.com/123');
      await tester.tap(find.byKey(const Key('add-video')));
      await tester.pumpAndSettle();
      expect(
        find.text("That isn't a YouTube link. Paste the address of a video on youtube.com or youtu.be."),
        findsOneWidget,
      );

      await tester.enterText(find.byKey(const Key('video-url')), link('private00001'));
      await tester.tap(find.byKey(const Key('add-video')));
      await tester.pumpAndSettle();
      expect(find.textContaining("YouTube can't show that video"), findsOneWidget);

      await tester.enterText(find.byKey(const Key('video-url')), link('vid00000001'));
      await tester.tap(find.byKey(const Key('add-video')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('video-url')), link('vid00000001'));
      await tester.tap(find.byKey(const Key('add-video')));
      await tester.pumpAndSettle();
      expect(find.text("That video is already in this objective's list."), findsOneWidget);
    });

    testWidgets('the first three are shown; the rest wait; five is the most', (tester) async {
      await open(
        tester,
        path,
        setup: (t) => t.videos['AIML101'] = {
          first: [for (var i = 1; i <= 5; i++) video('vid0000000$i', note: i == 2 ? 'The proof' : '')],
        },
      );
      expect(find.textContaining('5 of 5 · the first three are shown'), findsOneWidget);
      expect(find.textContaining('waits: students see the first three'), findsNWidgets(2));
      expect(find.text('An objective can have up to 5 videos. Remove one first.'), findsOneWidget);
      expect(tester.widget<FilledButton>(find.byKey(const Key('add-video'))).onPressed, isNull);
      expect(find.text('3. Title of vid00000003'), findsOneWidget);
      expect(find.text('4. Title of vid00000004'), findsNothing); // not in the preview
      expect(find.text('The proof'), findsOneWidget);
    });

    testWidgets('moves a video up and down; the ends are disabled', (tester) async {
      final api = await open(
        tester,
        path,
        setup: (t) => t.videos['AIML101'] = {
          first: [video('vid00000001'), video('vid00000002'), video('vid00000003')],
        },
      );
      IconButton button(String key) => tester.widget<IconButton>(find.byKey(Key(key)));
      expect(button('move-up-vid00000001').onPressed, isNull);
      expect(button('move-down-vid00000003').onPressed, isNull);
      expect(find.byTooltip('Move up'), findsNWidgets(3));

      await tester.tap(find.byKey(const Key('move-up-vid00000003')));
      await tester.pumpAndSettle();
      expect(
        [for (final v in api.teach!.videos['AIML101']![first]!) v['id']],
        ['vid00000001', 'vid00000003', 'vid00000002'],
      );
      double order(String id) => tester.getTopLeft(find.text('Title of $id').first).dy;
      expect(order('vid00000003'), lessThan(order('vid00000002')));
      await tester.tap(find.byKey(const Key('move-down-vid00000001')));
      await tester.pumpAndSettle();
      expect(
        [for (final v in api.teach!.videos['AIML101']![first]!) v['id']],
        ['vid00000003', 'vid00000001', 'vid00000002'],
      );
    });

    testWidgets('removes a video and offers to add it again', (tester) async {
      final api = await open(
        tester,
        path,
        setup: (t) => t.videos['AIML101'] = {
          first: [video('vid00000001', note: 'Watch from 3:20'), video('vid00000002')],
        },
      );
      await tester.tap(find.byKey(const Key('remove-vid00000001')));
      await tester.pumpAndSettle();
      expect([for (final v in api.teach!.videos['AIML101']![first]!) v['id']], ['vid00000002']);
      expect(find.textContaining('Removed “Title of vid00000001”'), findsOneWidget);

      await tester.tap(find.text('Add it again'));
      await tester.pumpAndSettle();
      final restored = api.teach!.videos['AIML101']![first]!;
      expect(restored.length, 2);
      expect(restored.last['note'], 'Watch from 3:20'); // the note comes back with it
    });

    testWidgets('says how many students were shown help, or that it is withheld', (tester) async {
      await open(tester, path, setup: (t) => t.helpShown[first] = 11);
      expect(find.textContaining('11 students were shown video help here in the last 30 days'), findsOneWidget);
      await open(tester, path, setup: (t) => t.helpShown[first] = null);
      expect(find.textContaining('fewer than 5 students were shown video help here'), findsOneWidget);
      await open(tester, path);
      expect(find.textContaining('no students were shown video help here'), findsOneWidget);
    });

    testWidgets('the fallback card follows the state of automatic search', (tester) async {
      await open(tester, path);
      expect(find.textContaining('at most once a week'), findsOneWidget);
      await open(tester, path, setup: (t) => t.searchEnabled = false);
      expect(
        find.textContaining("Automatic YouTube search isn't set up, so LEA shows generic search links."),
        findsOneWidget,
      );
    });

    testWidgets('an objective that is not in the live version says so', (tester) async {
      await open(tester, '/teach/courses/AIML101/videos/GO_99_99_999');
      expect(find.textContaining("That objective isn't in the live version"), findsOneWidget);
    });

    testWidgets('a phone can read the list but not change it', (tester) async {
      await open(
        tester,
        path,
        size: const Size(400, 900),
        setup: (t) => t.videos['AIML101'] = {
          first: [video('vid00000001', note: 'Watch from 3:20')],
        },
      );
      expect(find.text('Open LEA on a computer to edit. On a phone you can follow progress.'), findsOneWidget);
      expect(find.text('Title of vid00000001'), findsOneWidget);
      expect(find.byKey(const Key('video-url')), findsNothing);
      expect(find.byKey(const Key('remove-vid00000001')), findsNothing);
      expect(find.byKey(const Key('move-up-vid00000001')), findsNothing);
    });

    testWidgets('All objectives goes back to the overview', (tester) async {
      await open(tester, path);
      await tester.tap(find.widgetWithText(OutlinedButton, 'All objectives'));
      await tester.pumpAndSettle();
      expect(location(tester), '/teach/courses/AIML101/videos');
    });
  });
}
