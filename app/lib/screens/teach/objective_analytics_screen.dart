import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../api/api_error.dart';
import '../../teach/analytics_models.dart';
import '../../teach/analytics_state.dart';
import '../../teach/teach_models.dart';
import '../../teach/teach_state.dart';
import '../../teach/teach_widgets.dart';
import '../../theme/lea_colors.dart';
import '../../theme/lea_type.dart';
import '../../widgets/ghost_button.dart';
import '../../widgets/skeleton.dart';

/// One objective (`detail-*.png`): the learning curve against the course's typical one,
/// common wrong answers, tutor struggle, what students ask in Chat, and LEA's suggested
/// action; "Draft an explainer" drafts text for the teacher (never published by LEA).
class ObjectiveAnalyticsScreen extends ConsumerStatefulWidget {
  const ObjectiveAnalyticsScreen({super.key, required this.code, required this.go});

  final String code;
  final String go;

  @override
  ConsumerState<ObjectiveAnalyticsScreen> createState() => _ObjectiveAnalyticsScreenState();
}

class _ObjectiveAnalyticsScreenState extends ConsumerState<ObjectiveAnalyticsScreen> {
  String? _note; // the teacher's edit of the suggestion (this visit only)
  bool _dismissed = false;

  Future<void> _explainer() async {
    await showDialog<void>(
      context: context,
      builder: (_) => _ExplainerDialog(code: widget.code, go: widget.go),
    );
  }

  Future<void> _editNote(String current) async {
    final text = await showDialog<String>(
      context: context,
      builder: (_) => _NoteDialog(initial: current),
    );
    if (text != null) setState(() => _note = text);
  }

  @override
  Widget build(BuildContext context) {
    final wide = MediaQuery.sizeOf(context).width >= 720;
    final code = widget.code;
    final detail = ref.watch(objectiveDetailProvider((code, widget.go)));
    final kind = ref.watch(analyticsKindProvider);
    final d = detail.value;
    final s = d?.stats;
    final who = kind == 'simulated' ? ' · simulated' : '';
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        TeachHeader(
          kicker: '$code · Analytics${s == null || s.week == 0 ? '' : ' · Week ${s.week}'}',
          title: s?.skillName ?? widget.go,
          subtitle: s == null
              ? null
              : s.students == null
              ? '${s.goId} · fewer than 5 students$who'
              : '${s.goId} · ${s.students} students · ${s.gradedAttempts} graded attempts$who',
          actions: [
            GhostButton(label: 'All objectives', onPressed: () => context.go(TeachSection.analytics.path(code))),
            if (wide) ...[
              GhostButton(label: 'Open in Objectives', onPressed: () => context.go(TeachSection.objectives.path(code))),
              FilledButton(onPressed: d == null ? null : _explainer, child: const Text('Draft an explainer')),
            ],
          ],
        ),
        Expanded(
          child: switch (detail) {
            AsyncError(:final error) => Padding(
              padding: const EdgeInsets.all(24),
              child: TeachError(
                error: error,
                onRetry: () => ref.invalidate(objectiveDetailProvider((code, widget.go))),
              ),
            ),
            AsyncData(value: final d) => _body(d, wide),
            _ => const Padding(padding: EdgeInsets.all(24), child: SkeletonBox(height: 300)),
          },
        ),
      ],
    );
  }

  Widget _body(ObjectiveDetail d, bool wide) {
    final curve = _CurveCard(detail: d);
    final chat = _ChatCard(code: widget.code, detail: d);
    final wrong = _WrongAnswersCard(wrong: d.wrongAnswers);
    final struggle = _StruggleCard(struggle: d.struggle, students: d.stats.students);
    final suggestion = d.suggestion == null || _dismissed
        ? null
        : _SuggestionCard(
            text: _note ?? d.suggestion!,
            edited: _note != null,
            onEdit: () => _editNote(_note ?? d.suggestion!),
            onDismiss: () => setState(() => _dismissed = true),
          );
    const gap = SizedBox(height: 14);
    final pad = EdgeInsets.fromLTRB(wide ? 24 : 16, 18, wide ? 24 : 16, 24);
    if (!wide) {
      return ListView(
        padding: pad,
        children: [
          const DesktopOnlyNote(),
          gap,
          curve,
          gap,
          wrong,
          gap,
          struggle,
          gap,
          chat,
          if (suggestion != null) ...[gap, suggestion],
        ],
      );
    }
    return SingleChildScrollView(
      padding: pad,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(flex: 3, child: Column(children: [curve, gap, chat])),
          const SizedBox(width: 14),
          Expanded(
            flex: 2,
            child: Column(
              children: [
                wrong,
                gap,
                struggle,
                if (suggestion != null) ...[gap, suggestion],
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _CardTitle extends StatelessWidget {
  const _CardTitle(this.title, {this.trailing});

  final String title;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Wrap(
        alignment: WrapAlignment.spaceBetween,
        crossAxisAlignment: WrapCrossAlignment.center,
        spacing: 12,
        runSpacing: 4,
        children: [
          Semantics(
            header: true,
            child: Text(
              title,
              style: LeaType.heading(16, weight: FontWeight.w700).copyWith(color: c.ink),
            ),
          ),
          ?trailing,
        ],
      ),
    );
  }
}

Widget _muted(BuildContext context, String text) =>
    Text(text, style: LeaType.ui(12.5).copyWith(color: context.lea.muted));

// ---------------------------------------------------------------------------- learning curve

class _CurveCard extends StatelessWidget {
  const _CurveCard({required this.detail});

  final ObjectiveDetail detail;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final shown = detail.curve.where((p) => p.errorRate != null).toList();
    final typical = detail.courseCurve.where((p) => p.errorRate != null).toList();
    final reading = detail.curveReading;
    return TeachCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _CardTitle(
            'Learning curve',
            trailing: Text.rich(
              TextSpan(
                children: [
                  TextSpan(
                    text: '— ',
                    style: TextStyle(color: c.danger),
                  ),
                  const TextSpan(text: 'this objective · '),
                  TextSpan(
                    text: '--- ',
                    style: TextStyle(color: c.muted),
                  ),
                  const TextSpan(text: 'course typical'),
                ],
              ),
              style: LeaType.ui(12).copyWith(color: c.muted),
            ),
          ),
          if (shown.isEmpty)
            _muted(context, 'Not enough students yet: a point is shown once 5 students have reached it.')
          else ...[
            Semantics(
              label:
                  'Learning curve: error rate by practice opportunity, '
                  '${shown.map((p) => '${p.opportunity}: ${percent(p.errorRate!)}').join(', ')}',
              excludeSemantics: true,
              child: SizedBox(
                height: 190,
                width: double.infinity,
                child: CustomPaint(
                  painter: _CurvePainter(
                    points: shown,
                    typical: typical,
                    line: c.danger,
                    dashed: c.muted,
                    grid: c.line,
                    label: LeaType.ui(11).copyWith(color: c.muted),
                  ),
                ),
              ),
            ),
            const SizedBox(height: 10),
            Text.rich(
              TextSpan(
                children: [
                  const TextSpan(text: 'Error rate by practice opportunity. '),
                  if (reading != null)
                    TextSpan(
                      text: reading,
                      style: const TextStyle(fontWeight: FontWeight.w600),
                    ),
                ],
              ),
              style: LeaType.ui(12.5).copyWith(color: c.ink),
            ),
          ],
        ],
      ),
    );
  }
}

class _CurvePainter extends CustomPainter {
  _CurvePainter({
    required this.points,
    required this.typical,
    required this.line,
    required this.dashed,
    required this.grid,
    required this.label,
  });

  final List<CurvePoint> points;
  final List<CurvePoint> typical;
  final Color line;
  final Color dashed;
  final Color grid;
  final TextStyle label;

  void _text(Canvas canvas, String s, Offset at, {bool right = false}) {
    final tp = TextPainter(
      text: TextSpan(text: s, style: label),
      textDirection: TextDirection.ltr,
    )..layout();
    tp.paint(canvas, at - Offset(right ? tp.width : tp.width / 2, tp.height / 2));
  }

  @override
  void paint(Canvas canvas, Size size) {
    const left = 40.0, bottom = 22.0, top = 6.0, right = 12.0;
    final w = size.width - left - right, h = size.height - top - bottom;
    final last = [...points, ...typical].fold<int>(2, (m, p) => p.opportunity > m ? p.opportunity : m);
    double x(int o) => left + w * (o - 1) / (last - 1);
    double y(double r) => top + h * (1 - r);
    final gridPaint = Paint()
      ..color = grid
      ..strokeWidth = 1;
    for (final r in [0.0, 0.25, 0.5, 0.75, 1.0]) {
      canvas.drawLine(Offset(left, y(r)), Offset(left + w, y(r)), gridPaint);
      _text(canvas, '${(r * 100).round()}%', Offset(left - 8, y(r)), right: true);
    }
    for (var o = 1; o <= last; o++) {
      _text(canvas, '$o', Offset(x(o), size.height - bottom / 2 + 2));
    }
    // The course's typical curve, dashed.
    final dash = Paint()
      ..color = dashed
      ..strokeWidth = 1.6;
    for (var i = 0; i + 1 < typical.length; i++) {
      final a = Offset(x(typical[i].opportunity), y(typical[i].errorRate!));
      final b = Offset(x(typical[i + 1].opportunity), y(typical[i + 1].errorRate!));
      final length = (b - a).distance;
      for (var t = 0.0; t < length; t += 7) {
        final end = (t + 4).clamp(0.0, length);
        canvas.drawLine(a + (b - a) * (t / length), a + (b - a) * (end / length), dash);
      }
    }
    // This objective, solid with dots.
    final stroke = Paint()
      ..color = line
      ..strokeWidth = 2.2
      ..style = PaintingStyle.stroke;
    final path = Path();
    for (final (i, p) in points.indexed) {
      final at = Offset(x(p.opportunity), y(p.errorRate!));
      i == 0 ? path.moveTo(at.dx, at.dy) : path.lineTo(at.dx, at.dy);
    }
    canvas.drawPath(path, stroke);
    final dot = Paint()..color = line;
    for (final p in points) {
      canvas.drawCircle(Offset(x(p.opportunity), y(p.errorRate!)), 3.5, dot);
    }
  }

  @override
  bool shouldRepaint(_CurvePainter old) => old.points != points || old.typical != typical || old.line != line;
}

// ---------------------------------------------------------------------------- wrong answers, struggle

class _WrongAnswersCard extends StatelessWidget {
  const _WrongAnswersCard({required this.wrong});

  final WrongAnswers wrong;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    return TeachCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const _CardTitle('Common wrong answers'),
          if (wrong.suppressed || wrong.answers.isEmpty)
            _muted(context, 'Not enough students yet: shown once 5 students have answered wrongly.')
          else
            for (final a in wrong.answers) ...[
              Text.rich(
                TextSpan(
                  children: [
                    TextSpan(
                      text: percent(a.share),
                      style: const TextStyle(fontWeight: FontWeight.w700),
                    ),
                    TextSpan(text: ' of wrong answers: ${a.answer}'),
                  ],
                ),
                style: LeaType.ui(13).copyWith(color: c.ink),
              ),
              const SizedBox(height: 6),
              ClipRRect(
                borderRadius: BorderRadius.circular(99),
                child: LinearProgressIndicator(
                  value: a.share,
                  minHeight: 6,
                  color: c.danger,
                  backgroundColor: c.line,
                  semanticsLabel: '${percent(a.share)} of wrong answers',
                ),
              ),
              const SizedBox(height: 12),
            ],
          _muted(context, 'Grouped by objective: quiz questions are written fresh for each student.'),
        ],
      ),
    );
  }
}

class _StruggleCard extends StatelessWidget {
  const _StruggleCard({required this.struggle, required this.students});

  final Struggle struggle;
  final int? students;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final s = struggle;
    Widget row(String label, String value) => Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Row(
        children: [
          Expanded(
            child: Text(label, style: LeaType.ui(12.5).copyWith(color: c.muted)),
          ),
          Text(
            value,
            style: LeaType.ui(13, weight: FontWeight.w700).copyWith(color: c.ink),
          ),
        ],
      ),
    );
    String of(int? n) {
      if (n == null) return '—';
      final share = students == null || students == 0 ? '' : ' (${percent(n / students!)})';
      return '$n ${n == 1 ? 'student' : 'students'}$share';
    }

    return TeachCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const _CardTitle('Tutor struggle'),
          if (s.suppressed)
            _muted(context, 'Not enough students yet.')
          else ...[
            row('3+ wrong replies in a row', of(s.streakStudents)),
            row('Video help shown', of(s.videoStudents)),
            row(
              'Left without moving on',
              '${s.sessionsLeftStuck ?? 0} ${s.sessionsLeftStuck == 1 ? 'session' : 'sessions'}',
            ),
          ],
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------- chat topics

class _ChatCard extends ConsumerStatefulWidget {
  const _ChatCard({required this.code, required this.detail});

  final String code;
  final ObjectiveDetail detail;

  @override
  ConsumerState<_ChatCard> createState() => _ChatCardState();
}

class _ChatCardState extends ConsumerState<_ChatCard> {
  bool _running = false;

  Future<void> _run() async {
    setState(() => _running = true);
    try {
      await runChatTopics(ref, widget.code);
    } on ApiError catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    } finally {
      if (mounted) setState(() => _running = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final status = ref.watch(chatTopicsProvider(widget.code)).value;
    final topics = widget.detail.chatTopics;
    final result = status?.result;
    final button = status == null || !status.canRun
        ? null
        : GhostButton(
            label: _running
                ? 'Grouping…'
                : '${result == null ? 'Group chat questions' : 'Group again'} · ≈ ${dollars(status.usd)}',
            onPressed: _running ? null : _run,
          );
    return TeachCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const _CardTitle('What students ask in Chat'),
          if (result == null)
            _muted(
              context,
              status != null && !status.canRun
                  ? 'Not enough students have asked questions yet (5 needed).'
                  : 'Chat questions haven’t been grouped by topic yet. LEA sends ${status?.questions ?? 0} '
                        'questions, with names removed, to GPT-4o mini.',
            )
          else if (topics.isEmpty)
            _muted(context, 'No topic about this objective was asked by 5 or more students.')
          else
            for (final t in topics) ...[
              Text.rich(
                TextSpan(
                  children: [
                    TextSpan(
                      text: t.label,
                      style: const TextStyle(fontWeight: FontWeight.w700),
                    ),
                    TextSpan(
                      text: ' · ${t.students} students',
                      style: TextStyle(color: c.muted),
                    ),
                  ],
                ),
                style: LeaType.ui(13).copyWith(color: c.ink),
              ),
              if (t.paraphrases.isNotEmpty) ...[
                const SizedBox(height: 6),
                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
                  decoration: BoxDecoration(color: c.bg, borderRadius: BorderRadius.circular(8)),
                  child: Text(
                    t.paraphrases.map((p) => '“$p”').join(' · '),
                    style: LeaType.ui(12.5).copyWith(color: c.ink),
                  ),
                ),
              ],
              const SizedBox(height: 10),
            ],
          if (result != null) ...[
            const SizedBox(height: 4),
            _muted(
              context,
              'Paraphrased by LEA; names removed. Topics asked by fewer than 5 students aren’t shown. '
              '${result.agreement == null ? '' : 'Two independent passes agreed on ${percent(result.agreement!)} of '
                        'questions. '}Grouped ${result.date}.',
            ),
          ],
          if (button != null) ...[const SizedBox(height: 10), button],
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------- suggestion, explainer

class _SuggestionCard extends StatelessWidget {
  const _SuggestionCard({required this.text, required this.edited, required this.onEdit, required this.onDismiss});

  final String text;
  final bool edited;
  final VoidCallback onEdit;
  final VoidCallback onDismiss;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    return TeachCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _CardTitle(
            'Suggested action',
            trailing: TeachPill(edited ? 'Your note' : 'LEA suggestion', tone: PillTone.outline),
          ),
          Text(text, style: LeaType.ui(13).copyWith(color: c.ink)),
          const SizedBox(height: 12),
          Wrap(
            spacing: 8,
            children: [
              GhostButton(label: 'Edit note', onPressed: onEdit),
              GhostButton(label: 'Dismiss', onPressed: onDismiss),
            ],
          ),
        ],
      ),
    );
  }
}

class _NoteDialog extends StatefulWidget {
  const _NoteDialog({required this.initial});

  final String initial;

  @override
  State<_NoteDialog> createState() => _NoteDialogState();
}

class _NoteDialogState extends State<_NoteDialog> {
  late final _text = TextEditingController(text: widget.initial);

  @override
  void dispose() {
    _text.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: const Text('Edit note'),
    content: SizedBox(
      width: 480,
      child: TextField(
        key: const Key('suggestion-note'),
        controller: _text,
        maxLines: 5,
        decoration: const InputDecoration(border: OutlineInputBorder()),
      ),
    ),
    actions: [
      TextButton(onPressed: () => Navigator.of(context).pop(), child: const Text('Cancel')),
      FilledButton(onPressed: () => Navigator.of(context).pop(_text.text.trim()), child: const Text('Save')),
    ],
  );
}

class _ExplainerDialog extends ConsumerStatefulWidget {
  const _ExplainerDialog({required this.code, required this.go});

  final String code;
  final String go;

  @override
  ConsumerState<_ExplainerDialog> createState() => _ExplainerDialogState();
}

class _ExplainerDialogState extends ConsumerState<_ExplainerDialog> {
  final _text = TextEditingController();
  bool _drafting = false;
  bool _drafted = false;
  String? _error;

  @override
  void dispose() {
    _text.dispose();
    super.dispose();
  }

  Future<void> _draft() async {
    setState(() {
      _drafting = true;
      _error = null;
    });
    try {
      final e = await draftExplainer(ref, widget.code, widget.go);
      _text.text = e.text;
      _drafted = true;
    } on ApiError catch (e) {
      _error = e.message;
    } finally {
      if (mounted) setState(() => _drafting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    return AlertDialog(
      title: const Text('Draft an explainer'),
      content: SizedBox(
        width: 560,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'LEA drafts a short explanation from the course material for you to edit and use as you '
              'like. It is never published or shown to students by LEA. Uses GPT-4o mini (well under a cent).',
              style: LeaType.ui(12.5).copyWith(color: c.muted),
            ),
            const SizedBox(height: 12),
            if (_drafted)
              TextField(
                key: const Key('explainer-text'),
                controller: _text,
                maxLines: 10,
                decoration: const InputDecoration(border: OutlineInputBorder()),
              )
            else if (_drafting)
              const SkeletonBox(height: 120),
            if (_error != null) ...[const SizedBox(height: 8), TeachBanner(tone: BannerTone.bad, child: Text(_error!))],
          ],
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.of(context).pop(), child: const Text('Close')),
        if (_drafted)
          FilledButton(
            onPressed: () async {
              await Clipboard.setData(ClipboardData(text: _text.text));
              if (context.mounted) {
                ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Copied')));
              }
            },
            child: const Text('Copy'),
          )
        else
          FilledButton(onPressed: _drafting ? null : _draft, child: Text(_drafting ? 'Drafting…' : 'Draft')),
      ],
    );
  }
}
