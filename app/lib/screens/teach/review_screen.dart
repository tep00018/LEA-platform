import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../teach/kc_state.dart';
import '../../teach/teach_models.dart';
import '../../teach/teach_state.dart';
import '../../teach/teach_widgets.dart';
import '../../theme/lea_colors.dart';
import '../../theme/lea_type.dart';
import '../../widgets/ghost_button.dart';
import '../../widgets/skeleton.dart';

/// Review changes and publish (`publish-*.png`): every change against the live version and
/// who it affects, before anything reaches students.
class ReviewScreen extends ConsumerStatefulWidget {
  const ReviewScreen({super.key, required this.code});

  final String code;

  @override
  ConsumerState<ReviewScreen> createState() => _ReviewScreenState();
}

class _ReviewScreenState extends ConsumerState<ReviewScreen> {
  final _note = TextEditingController();
  int? _published;

  @override
  void dispose() {
    _note.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final wide = MediaQuery.sizeOf(context).width >= 720;
    final code = widget.code;
    final diff = ref.watch(kcDiffProvider(code));
    final edit = ref.watch(kcEditorProvider(code));
    final overview = ref.watch(kcOverviewProvider(code)).value;
    final next = (overview?.publishedVersion ?? 0) + 1;
    final back = TeachSection.objectives.path(code);

    if (_published != null) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          TeachHeader(kicker: '$code · Objectives', title: 'Version $_published is live'),
          Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const TeachBanner(tone: BannerTone.ok, child: Text('Published. Students see the new objectives now.')),
                const SizedBox(height: 12),
                FilledButton(onPressed: () => context.go(back), child: const Text('Back to the objectives')),
              ],
            ),
          ),
        ],
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        TeachHeader(
          kicker: '$code · Objectives',
          title: 'Publish version $next?',
          subtitle: edit.draft == null
              ? null
              : 'Draft based on ${edit.draft!.basedOn == null ? 'nothing yet' : 'version ${edit.draft!.basedOn}'}',
          actions: [
            GhostButton(label: 'Back to the draft', onPressed: () => context.go(back)),
            if (wide)
              FilledButton(
                onPressed: edit.busy || !diff.hasValue || edit.draft == null ? null : _publish,
                child: Text('Publish version $next'),
              ),
          ],
        ),
        Expanded(
          child: switch (diff) {
            AsyncData(value: final d) => _Changes(diff: d, note: _note, wide: wide, error: edit.error),
            AsyncError(:final error) => Padding(
              padding: const EdgeInsets.all(24),
              child: TeachError(error: error, onRetry: () => ref.invalidate(kcDiffProvider(code))),
            ),
            _ => const Padding(padding: EdgeInsets.all(24), child: SkeletonBox(height: 200)),
          },
        ),
      ],
    );
  }

  Future<void> _publish() async {
    final version = await ref.read(kcEditorProvider(widget.code).notifier).publish(_note.text.trim());
    if (version != null && mounted) setState(() => _published = version);
  }
}

class _Changes extends StatelessWidget {
  const _Changes({required this.diff, required this.note, required this.wide, this.error});

  final KCDiff diff;
  final TextEditingController note;
  final bool wide;
  final String? error;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final counts = diff.counts;
    Widget change(String label, PillTone tone, String title, String detail) => Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      decoration: BoxDecoration(
        border: Border(top: BorderSide(color: c.line)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 84,
            child: Align(
              alignment: Alignment.centerLeft,
              child: TeachPill(label, tone: tone),
            ),
          ),
          Expanded(
            child: Text(
              title,
              style: LeaType.ui(13, weight: FontWeight.w500).copyWith(color: c.ink),
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Text(detail, style: LeaType.ui(12.5).copyWith(color: c.muted)),
          ),
        ],
      ),
    );
    String fields(Map<String, dynamic> ch) => [
      for (final f in (ch['changes'] as List).cast<Map<String, dynamic>>())
        '${(f['field'] as String).replaceAll('_', ' ')}: ${f['before']} → ${f['after']}',
    ].join(' · ');
    final changes = TeachCard(
      padding: EdgeInsets.zero,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(14, 10, 14, 10),
            child: Text('CHANGES', style: LeaType.label(11).copyWith(color: c.muted)),
          ),
          for (final a in diff.added)
            change('Added', PillTone.ok, '${a['skill_name']}', '${a['go_id']} · week ${a['week']}'),
          for (final ch in diff.changed) change('Changed', PillTone.warn, '${ch['go_id']}', fields(ch)),
          for (final s in diff.splits)
            change('Split', PillTone.neutral, '${s['from']}', 'into ${(s['to'] as List).join(', ')}'),
          for (final m in diff.merges)
            change('Merged', PillTone.neutral, (m['from'] as List).join(' + '), 'into ${m['to']}'),
          for (final r in diff.retired)
            change('Retired', PillTone.bad, '${r['skill_name']}', '${r['go_id']} · its ID is never reused'),
          if ((counts['added'] ?? 0) + (counts['changed'] ?? 0) + (counts['removed'] ?? 0) == 0)
            Padding(
              padding: const EdgeInsets.all(14),
              child: Text('No changes against the live version.', style: LeaType.small().copyWith(color: c.muted)),
            ),
        ],
      ),
    );
    final affected = TeachCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Students affected', style: LeaType.heading(16).copyWith(color: c.ink)),
          const SizedBox(height: 8),
          TeachStat(
            value: '${diff.studentsAffected}',
            label: 'of ${diff.studentsWithMastery} students have mastery on objectives this changes',
          ),
          const SizedBox(height: 8),
          for (final (kind, label, what) in [
            ('split', 'Split', 'each part starts at their old mastery'),
            ('merged', 'Merged', 'the average of their mastery on the merged ones'),
            ('retired', 'Retired', 'kept, no longer counted'),
          ])
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(
                '$label (${diff.withMasteryOn(kind)}): $what',
                style: LeaType.ui(12.5).copyWith(color: c.ink),
              ),
            ),
        ],
      ),
    );
    final side = Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        affected,
        const SizedBox(height: 12),
        const TeachBanner(
          tone: BannerTone.soft,
          child: Text(
            'Research note. Publishing changes what students see and moves mastery as above. '
            "It's recorded in the event log with your review time and edits.",
          ),
        ),
        const SizedBox(height: 12),
        TextField(
          key: const Key('publish-note'),
          controller: note,
          decoration: const InputDecoration(
            labelText: 'Note for this version (optional)',
            border: OutlineInputBorder(),
          ),
        ),
      ],
    );
    final stats = TeachCard(
      child: Wrap(
        spacing: 26,
        runSpacing: 10,
        children: [
          TeachStat(value: '${counts['added'] ?? 0}', label: 'added'),
          TeachStat(value: '${counts['changed'] ?? 0}', label: 'changed'),
          TeachStat(value: '${counts['splits'] ?? 0}', label: 'split'),
          TeachStat(value: '${counts['merges'] ?? 0}', label: 'merged'),
          TeachStat(value: '${diff.retired.length}', label: 'retired'),
          TeachStat(value: '${counts['total'] ?? 0}', label: 'objectives after'),
        ],
      ),
    );
    return LayoutBuilder(
      builder: (context, constraints) {
        final pad = EdgeInsets.fromLTRB(wide ? 24 : 16, 18, wide ? 24 : 16, 24);
        final main = Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            if (error != null) ...[TeachBanner(tone: BannerTone.bad, child: Text(error!)), const SizedBox(height: 12)],
            stats,
            const SizedBox(height: 12),
            changes,
          ],
        );
        if (constraints.maxWidth >= 980) {
          return SingleChildScrollView(
            padding: pad,
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(child: main),
                const SizedBox(width: 16),
                SizedBox(width: 330, child: side),
              ],
            ),
          );
        }
        return ListView(padding: pad, children: [main, const SizedBox(height: 12), side]);
      },
    );
  }
}
