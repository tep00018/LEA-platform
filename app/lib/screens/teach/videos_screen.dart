import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../teach/teach_widgets.dart';
import '../../teach/video_models.dart';
import '../../teach/video_state.dart';
import '../../theme/lea_colors.dart';
import '../../theme/lea_type.dart';
import '../../widgets/ghost_button.dart';
import '../../widgets/skeleton.dart';

/// Videos for stuck students (`videos-*.png`): which objectives have the instructor's videos,
/// what a stuck student gets for each, and how many students were shown help.
class VideosScreen extends ConsumerStatefulWidget {
  const VideosScreen({super.key, required this.code});

  final String code;

  @override
  ConsumerState<VideosScreen> createState() => _VideosScreenState();
}

class _VideosScreenState extends ConsumerState<VideosScreen> {
  int? _week;
  String _show = 'all';

  static const _shows = [('all', 'All objectives'), ('with', 'With videos'), ('without', 'Without videos')];

  @override
  Widget build(BuildContext context) {
    final wide = MediaQuery.sizeOf(context).width >= 720;
    final code = widget.code;
    final overview = ref.watch(videosProvider(code));
    final o = overview.value;
    final weeks = o == null ? const <int>[] : ({for (final x in o.objectives) x.week}.toList()..sort());
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        TeachHeader(
          kicker: '$code · Videos',
          title: 'Videos for stuck students',
          subtitle: o == null
              ? null
              : 'Shown once when a student gets three answers in a row wrong · '
                    '${o.curatedObjectives} of ${o.objectives.length} objectives have your videos',
          actions: [
            if (o != null) ...[
              TeachFilter<int?>(
                label: 'Week',
                value: _week,
                options: [(null, 'All weeks'), for (final w in weeks) (w, 'Week $w')],
                onChanged: (w) => setState(() => _week = w),
              ),
              TeachFilter<String>(
                label: 'Which objectives',
                value: _show,
                options: _shows,
                onChanged: (v) => setState(() => _show = v),
              ),
            ],
          ],
        ),
        Expanded(
          child: switch (overview) {
            AsyncError(:final error) => Padding(
              padding: const EdgeInsets.all(24),
              child: TeachError(error: error, onRetry: () => ref.invalidate(videosProvider(code))),
            ),
            AsyncData(value: final o) => _body(o, wide),
            _ => const Padding(padding: EdgeInsets.all(24), child: SkeletonBox(height: 240)),
          },
        ),
      ],
    );
  }

  Widget _body(VideosOverview o, bool wide) {
    final c = context.lea;
    final rows = [
      for (final x in o.objectives)
        if ((_week == null || x.week == _week) && (_show == 'all' || (_show == 'with') == x.videos.isNotEmpty)) x,
    ]..sort(_byHelpShown);
    return ListView(
      padding: EdgeInsets.fromLTRB(wide ? 24 : 16, 18, wide ? 24 : 16, 24),
      children: [
        if (!wide) ...[const DesktopOnlyNote(), const SizedBox(height: 12)],
        _SearchBanner(search: o.search),
        TeachCard(
          child: Wrap(
            spacing: 32,
            runSpacing: 12,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              TeachStat(value: '${o.curatedObjectives}', label: 'objectives with your videos'),
              TeachStat(value: '${o.objectives.length - o.curatedObjectives}', label: 'without'),
              TeachStat(
                value: o.helpShownTimes == null ? '< 5' : '${o.helpShownTimes}',
                label: 'times help was shown · ${o.helpWindowDays} days',
              ),
              ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 380),
                child: Text(
                  'Students see the first three videos in your order. Search results for an objective are kept for a week.',
                  style: LeaType.ui(12.5).copyWith(color: c.muted),
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 14),
        if (rows.isEmpty)
          const TeachBanner(tone: BannerTone.soft, child: Text('No objectives match this filter.'))
        else
          TeachCard(
            padding: EdgeInsets.zero,
            child: Column(
              children: [
                if (wide) const _TableHeader(),
                for (final (i, x) in rows.indexed)
                  _Row(
                    objective: x,
                    search: o.search,
                    wide: wide,
                    first: i == 0 && !wide,
                    onOpen: () => context.go('/teach/courses/${widget.code}/videos/${x.goId}'),
                  ),
              ],
            ),
          ),
      ],
    );
  }

  /// Where students are stuck first: most students shown help, then week and ID.
  static int _byHelpShown(ObjectiveVideos a, ObjectiveVideos b) {
    double weight(ObjectiveVideos x) => x.helpShownStudents == null ? 2.5 : x.helpShownStudents!.toDouble();
    final byHelp = weight(b).compareTo(weight(a));
    if (byHelp != 0) return byHelp;
    final byWeek = a.week.compareTo(b.week);
    return byWeek != 0 ? byWeek : a.goId.compareTo(b.goId);
  }
}

class _SearchBanner extends StatelessWidget {
  const _SearchBanner({required this.search});

  final VideoSearch search;

  @override
  Widget build(BuildContext context) {
    if (search.paused) {
      return Padding(
        padding: const EdgeInsets.only(bottom: 14),
        child: TeachBanner(
          tone: BannerTone.soft,
          child: Text.rich(
            TextSpan(
              children: [
                const TextSpan(
                  text: 'Automatic YouTube search is paused',
                  style: TextStyle(fontWeight: FontWeight.w700),
                ),
                TextSpan(
                  text:
                      ' until midnight Pacific (${search.pausedFor(DateTime.now())}): Google\'s daily quota is '
                      'used up. Your videos are unaffected; objectives without them show generic search links '
                      'until then.',
                ),
              ],
            ),
          ),
        ),
      );
    }
    if (!search.enabled) {
      return const Padding(
        padding: EdgeInsets.only(bottom: 14),
        child: TeachBanner(
          child: Text(
            'Automatic YouTube search isn\'t set up, so objectives without your videos show generic search links.',
          ),
        ),
      );
    }
    return const SizedBox.shrink();
  }
}

const _flex = [5, 2, 3, 2, 2];

class _TableHeader extends StatelessWidget {
  const _TableHeader();

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    Widget h(String t, int i, {bool end = false}) => Expanded(
      flex: _flex[i],
      child: Text(
        t.toUpperCase(),
        textAlign: end ? TextAlign.end : TextAlign.start,
        style: LeaType.label(11).copyWith(color: c.muted),
      ),
    );
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 10),
      child: Row(
        children: [
          h('Objective', 0),
          h('Your videos', 1),
          h('What a stuck student gets', 2),
          h('Help shown', 3, end: true),
          h('', 4),
        ],
      ),
    );
  }
}

class _Row extends StatelessWidget {
  const _Row({
    required this.objective,
    required this.search,
    required this.wide,
    required this.first,
    required this.onOpen,
  });

  final ObjectiveVideos objective;
  final VideoSearch search;
  final bool wide;
  final bool first;
  final VoidCallback onOpen;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final x = objective;
    final has = x.videos.isNotEmpty;
    final yours = has
        ? TeachPill('${x.videos.length} of $maxVideosPerObjective', tone: PillTone.ok)
        : const TeachPill('None yet', tone: PillTone.dashed);
    final gets = switch (x.studentGets) {
      'curated' => const Wrap(children: [TeachPill('Your videos', tone: PillTone.ok)]),
      'search' => const Wrap(children: [TeachPill('Automatic search', tone: PillTone.outline)]),
      _ => Wrap(
        spacing: 6,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          const TeachPill('Search links', tone: PillTone.warn),
          Text(search.paused ? 'search paused' : 'search not set up', style: LeaType.ui(12).copyWith(color: c.muted)),
        ],
      ),
    };
    final figure = LeaType.ui(13).copyWith(color: c.ink, fontFeatures: const [FontFeature.tabularFigures()]);
    final help = x.helpShownStudents;
    final helpText = help == null
        ? Text(
            '< 5',
            textAlign: TextAlign.end,
            style: figure.copyWith(color: c.muted),
          )
        : help == 0
        ? Text(
            '—',
            textAlign: TextAlign.end,
            style: figure.copyWith(color: c.muted),
          )
        : Text('$help', textAlign: TextAlign.end, style: figure);
    final name = Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          x.skillName,
          style: LeaType.ui(13.5, weight: FontWeight.w600).copyWith(color: c.ink),
        ),
        const SizedBox(height: 2),
        IdText(x.goId),
      ],
    );
    return InkWell(
      key: Key('video-row-${x.goId}'),
      onTap: onOpen,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        decoration: BoxDecoration(
          border: first ? null : Border(top: BorderSide(color: c.line)),
        ),
        child: wide
            ? Row(
                crossAxisAlignment: CrossAxisAlignment.center,
                children: [
                  Expanded(flex: _flex[0], child: name),
                  Expanded(
                    flex: _flex[1],
                    child: Align(alignment: Alignment.centerLeft, child: yours),
                  ),
                  Expanded(flex: _flex[2], child: gets),
                  Expanded(flex: _flex[3], child: helpText),
                  Expanded(
                    flex: _flex[4],
                    child: Align(
                      alignment: Alignment.centerRight,
                      child: GhostButton(label: has ? 'Edit videos' : 'Add videos', onPressed: onOpen),
                    ),
                  ),
                ],
              )
            : Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  name,
                  const SizedBox(height: 6),
                  Wrap(
                    spacing: 8,
                    runSpacing: 4,
                    crossAxisAlignment: WrapCrossAlignment.center,
                    children: [yours, gets],
                  ),
                  const SizedBox(height: 4),
                  Text(
                    help == null
                        ? 'Help shown to fewer than 5 students'
                        : 'Help shown to ${help == 0 ? 'no' : help} students',
                    style: LeaType.ui(12.5).copyWith(color: c.muted),
                  ),
                ],
              ),
      ),
    );
  }
}
