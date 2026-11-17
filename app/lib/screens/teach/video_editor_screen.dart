import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../api/api_error.dart';
import '../../teach/teach_widgets.dart';
import '../../teach/video_models.dart';
import '../../teach/video_state.dart';
import '../../theme/lea_colors.dart';
import '../../theme/lea_type.dart';
import '../../widgets/ghost_button.dart';
import '../../widgets/skeleton.dart';

/// Videos for one objective (`videos-edit-*.png`): an ordered list, add by link with a note, and
/// a preview of exactly what a stuck student sees. The order is the order students see, and
/// only the first three are shown.
class VideoEditorScreen extends ConsumerStatefulWidget {
  const VideoEditorScreen({super.key, required this.code, required this.go});

  final String code;
  final String go;

  @override
  ConsumerState<VideoEditorScreen> createState() => _VideoEditorScreenState();
}

class _VideoEditorScreenState extends ConsumerState<VideoEditorScreen> {
  final _url = TextEditingController();
  final _note = TextEditingController();
  bool _adding = false;
  String? _error;

  @override
  void dispose() {
    _url.dispose();
    _note.dispose();
    super.dispose();
  }

  void _say(String text, {Duration? duration, SnackBarAction? action}) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(text), duration: duration ?? const Duration(seconds: 4), action: action));
  }

  Future<void> _add() async {
    setState(() {
      _adding = true;
      _error = null;
    });
    try {
      final video = await addVideo(ref, widget.code, widget.go, _url.text.trim(), _note.text.trim());
      _url.clear();
      _note.clear();
      _say('Added “${video.title}”.');
    } on ApiError catch (e) {
      if (mounted) setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _adding = false);
    }
  }

  Future<void> _move(CuratedVideo video, {required bool up}) async {
    try {
      await moveVideo(ref, widget.code, widget.go, video.id, up: up);
    } on ApiError catch (e) {
      _say(e.message);
    }
  }

  Future<void> _remove(CuratedVideo video) async {
    try {
      await removeVideo(ref, widget.code, widget.go, video.id);
      _say(
        'Removed “${video.title}”.',
        duration: const Duration(seconds: 8),
        action: SnackBarAction(
          label: 'Add it again',
          onPressed: () async {
            try {
              await addVideo(ref, widget.code, widget.go, video.url, video.note);
            } on ApiError catch (e) {
              _say(e.message);
            }
          },
        ),
      );
    } on ApiError catch (e) {
      _say(e.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final wide = MediaQuery.sizeOf(context).width >= 720;
    final code = widget.code;
    final overview = ref.watch(videosProvider(code));
    final o = overview.value;
    final x = o?.objective(widget.go);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        TeachHeader(
          kicker: '$code · Videos${x == null ? '' : ' · Week ${x.week}'}',
          title: x?.skillName ?? widget.go,
          subtitle: x == null ? null : '${x.goId} · ${_helpLine(x.helpShownStudents, o!.helpWindowDays)}',
          actions: [GhostButton(label: 'All objectives', onPressed: () => context.go('/teach/courses/$code/videos'))],
        ),
        Expanded(
          child: switch (overview) {
            AsyncError(:final error) => Padding(
              padding: const EdgeInsets.all(24),
              child: TeachError(error: error, onRetry: () => ref.invalidate(videosProvider(code))),
            ),
            AsyncData(value: final o) =>
              o.objective(widget.go) == null
                  ? const Padding(
                      padding: EdgeInsets.all(24),
                      child: TeachBanner(
                        tone: BannerTone.soft,
                        child: Text('That objective isn\'t in the live version of this course.'),
                      ),
                    )
                  : _body(o, o.objective(widget.go)!, wide),
            _ => const Padding(padding: EdgeInsets.all(24), child: SkeletonBox(height: 240)),
          },
        ),
      ],
    );
  }

  static String _helpLine(int? students, int days) {
    if (students == null) return 'fewer than 5 students were shown video help here in the last $days days';
    if (students == 0) return 'no students were shown video help here in the last $days days';
    return '$students ${students == 1 ? 'student was' : 'students were'} shown video help here in the last $days days';
  }

  Widget _body(VideosOverview o, ObjectiveVideos x, bool wide) {
    final list = _ListCard(videos: x.videos, editable: wide, onMove: _move, onRemove: _remove);
    final add = _AddCard(
      url: _url,
      note: _note,
      adding: _adding,
      error: _error,
      full: x.videos.length >= o.maxPerObjective,
      max: o.maxPerObjective,
      onAdd: _add,
    );
    final preview = _PreviewCard(videos: x.videos);
    final fallback = _FallbackCard(search: o.search);
    final pad = EdgeInsets.fromLTRB(wide ? 24 : 16, 18, wide ? 24 : 16, 24);
    const gap = SizedBox(height: 14);
    if (!wide) {
      return ListView(padding: pad, children: [const DesktopOnlyNote(), gap, list, gap, preview, gap, fallback]);
    }
    return SingleChildScrollView(
      padding: pad,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(child: Column(children: [list, gap, add])),
          const SizedBox(width: 14),
          SizedBox(width: 360, child: Column(children: [preview, gap, fallback])),
        ],
      ),
    );
  }
}

class _Thumb extends StatelessWidget {
  const _Thumb();

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    return Container(
      width: 76,
      height: 43,
      decoration: BoxDecoration(
        color: c.surface2,
        border: Border.all(color: c.line),
        borderRadius: BorderRadius.circular(7),
      ),
      child: ExcludeSemantics(child: Icon(Icons.play_arrow, size: 22, color: c.primary)),
    );
  }
}

class _ListCard extends StatelessWidget {
  const _ListCard({required this.videos, required this.editable, required this.onMove, required this.onRemove});

  final List<CuratedVideo> videos;
  final bool editable;
  final Future<void> Function(CuratedVideo, {required bool up}) onMove;
  final Future<void> Function(CuratedVideo) onRemove;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    return TeachCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Wrap(
            alignment: WrapAlignment.spaceBetween,
            crossAxisAlignment: WrapCrossAlignment.center,
            spacing: 12,
            children: [
              Text(
                'Your videos',
                style: LeaType.heading(17, weight: FontWeight.w700).copyWith(color: c.ink),
              ),
              Text(
                '${videos.length} of $maxVideosPerObjective · the first three are shown',
                style: LeaType.ui(12.5).copyWith(color: c.muted),
              ),
            ],
          ),
          const SizedBox(height: 10),
          if (videos.isEmpty)
            Text(
              'No videos yet. Students who get stuck see a search result instead. Paste a YouTube link to choose '
              'what they see.',
              style: LeaType.ui(13).copyWith(color: c.muted),
            ),
          for (final (i, v) in videos.indexed)
            Container(
              padding: EdgeInsets.only(top: i == 0 ? 0 : 9, bottom: 9),
              decoration: BoxDecoration(
                border: i == 0 ? null : Border(top: BorderSide(color: c.line)),
              ),
              child: i < videosShown ? _full(context, i, v) : _compact(context, i, v),
            ),
        ],
      ),
    );
  }

  Widget _controls(BuildContext context, int i, CuratedVideo v) {
    final c = context.lea;
    if (!editable) return const SizedBox.shrink();
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        IconButton(
          key: Key('move-up-${v.id}'),
          tooltip: 'Move up',
          visualDensity: VisualDensity.compact,
          onPressed: i == 0 ? null : () => onMove(v, up: true),
          icon: const Icon(Icons.arrow_upward, size: 18),
        ),
        IconButton(
          key: Key('move-down-${v.id}'),
          tooltip: 'Move down',
          visualDensity: VisualDensity.compact,
          onPressed: i == videos.length - 1 ? null : () => onMove(v, up: false),
          icon: const Icon(Icons.arrow_downward, size: 18),
        ),
        TextButton(
          key: Key('remove-${v.id}'),
          onPressed: () => onRemove(v),
          style: TextButton.styleFrom(foregroundColor: c.danger),
          child: Text('Remove', semanticsLabel: 'Remove ${v.title}'),
        ),
      ],
    );
  }

  Widget _full(BuildContext context, int i, CuratedVideo v) {
    final c = context.lea;
    return Row(
      crossAxisAlignment: CrossAxisAlignment.center,
      children: [
        TeachPill('${i + 1}', tone: PillTone.ok),
        const SizedBox(width: 10),
        const _Thumb(),
        const SizedBox(width: 10),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                v.title,
                style: LeaType.ui(13.5, weight: FontWeight.w600).copyWith(color: c.ink),
              ),
              Text(
                [if (v.channel.isNotEmpty) v.channel, v.addedLine].join(' · '),
                style: LeaType.ui(12).copyWith(color: c.muted),
              ),
              if (v.note.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: 2),
                  child: Text('Note: ${v.note}', style: LeaType.ui(12.5).copyWith(color: c.ink)),
                ),
            ],
          ),
        ),
        _controls(context, i, v),
      ],
    );
  }

  Widget _compact(BuildContext context, int i, CuratedVideo v) {
    final c = context.lea;
    return Row(
      children: [
        TeachPill('${i + 1}', tone: PillTone.dashed),
        const SizedBox(width: 10),
        Expanded(
          child: Text.rich(
            TextSpan(
              children: [
                TextSpan(
                  text: v.title,
                  style: const TextStyle(fontWeight: FontWeight.w700),
                ),
                TextSpan(
                  text: ' · ${v.channel.isEmpty ? '' : '${v.channel} · '}waits: students see the first three',
                  style: TextStyle(color: c.muted),
                ),
              ],
            ),
            style: LeaType.ui(12.5).copyWith(color: c.ink),
          ),
        ),
        _controls(context, i, v),
      ],
    );
  }
}

class _AddCard extends StatelessWidget {
  const _AddCard({
    required this.url,
    required this.note,
    required this.adding,
    required this.error,
    required this.full,
    required this.max,
    required this.onAdd,
  });

  final TextEditingController url;
  final TextEditingController note;
  final bool adding;
  final String? error;
  final bool full;
  final int max;
  final VoidCallback onAdd;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    return TeachCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Add a video',
            style: LeaType.heading(17, weight: FontWeight.w700).copyWith(color: c.ink),
          ),
          const SizedBox(height: 10),
          Wrap(
            spacing: 10,
            runSpacing: 10,
            children: [
              SizedBox(
                width: 260,
                child: TextField(
                  key: const Key('video-url'),
                  controller: url,
                  enabled: !adding && !full,
                  keyboardType: TextInputType.url,
                  decoration: InputDecoration(
                    labelText: 'YouTube link',
                    hintText: 'Paste a link, e.g. https://youtu.be/…',
                    errorText: error,
                    errorMaxLines: 4,
                    border: const OutlineInputBorder(),
                  ),
                  onSubmitted: (_) => full || adding ? null : onAdd(),
                ),
              ),
              SizedBox(
                width: 260,
                child: TextField(
                  key: const Key('video-note'),
                  controller: note,
                  enabled: !adding && !full,
                  maxLength: 200,
                  decoration: const InputDecoration(
                    labelText: 'Note for students (optional)',
                    hintText: 'e.g. Watch from 3:20',
                    border: OutlineInputBorder(),
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 4),
          Wrap(
            spacing: 12,
            runSpacing: 6,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              FilledButton(
                key: const Key('add-video'),
                onPressed: adding || full ? null : onAdd,
                child: Text(adding ? 'Checking…' : 'Check and add'),
              ),
              Text(
                full
                    ? 'An objective can have up to $max videos. Remove one first.'
                    : 'LEA checks the link with YouTube and fills in the title and channel.',
                style: LeaType.ui(12.5).copyWith(color: c.muted),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _PreviewCard extends StatelessWidget {
  const _PreviewCard({required this.videos});

  final List<CuratedVideo> videos;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final shown = videos.take(videosShown).toList();
    return TeachCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'What a stuck student sees',
            style: LeaType.heading(16, weight: FontWeight.w700).copyWith(color: c.ink),
          ),
          const SizedBox(height: 10),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
            decoration: BoxDecoration(color: c.surface2, borderRadius: BorderRadius.circular(12)),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('LEA tutor', style: LeaType.ui(11.5).copyWith(color: c.muted)),
                const SizedBox(height: 4),
                Text('Let\'s take this one step at a time.', style: LeaType.ui(13).copyWith(color: c.ink)),
                const SizedBox(height: 10),
                if (shown.isEmpty)
                  Text(
                    'A search result for this objective (see below).',
                    style: LeaType.ui(13).copyWith(color: c.muted),
                  )
                else ...[
                  Text('📹 Video Resources to Help You:', style: LeaType.ui(13, weight: FontWeight.w700)),
                  const SizedBox(height: 4),
                  for (final (i, v) in shown.indexed)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 2),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            '${i + 1}. ${v.title}',
                            style: LeaType.ui(13).copyWith(color: c.ink, decoration: TextDecoration.underline),
                          ),
                          if (v.note.isNotEmpty) Text(v.note, style: LeaType.ui(12.5).copyWith(color: c.muted)),
                        ],
                      ),
                    ),
                ],
              ],
            ),
          ),
          const SizedBox(height: 8),
          Text(
            'Shown once, when a student has three wrong answers in a row on this objective.',
            style: LeaType.ui(12.5).copyWith(color: c.muted),
          ),
        ],
      ),
    );
  }
}

class _FallbackCard extends StatelessWidget {
  const _FallbackCard({required this.search});

  final VideoSearch search;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final text = search.enabled
        ? 'LEA searches YouTube for this objective at most once a week and shows what it finds. When Google\'s daily '
              'quota is used up it shows generic search links instead. '
        : 'Automatic YouTube search isn\'t set up, so LEA shows generic search links. ';
    return TeachCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'With no videos of yours',
            style: LeaType.heading(16, weight: FontWeight.w700).copyWith(color: c.ink),
          ),
          const SizedBox(height: 6),
          Text.rich(
            TextSpan(
              children: [
                TextSpan(text: text),
                TextSpan(
                  text: search.enabled
                      ? 'Choosing videos here avoids both.'
                      : 'Choosing videos here gives students something better.',
                  style: TextStyle(color: c.muted),
                ),
              ],
            ),
            style: LeaType.ui(12.5).copyWith(color: c.ink),
          ),
        ],
      ),
    );
  }
}
