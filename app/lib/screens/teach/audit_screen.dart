import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/api_error.dart';
import '../../teach/audit_admin_state.dart';
import '../../teach/teach_models.dart';
import '../../teach/teach_widgets.dart';
import '../../theme/lea_colors.dart';
import '../../theme/lea_type.dart';
import '../../widgets/ghost_button.dart';
import '../../widgets/skeleton.dart';

/// Content audit (`audit-*.png`): findings, not scores, ranked by severity, each with its
/// evidence and evidence tier; the teacher accepts or dismisses each one.
class AuditScreen extends ConsumerStatefulWidget {
  const AuditScreen({super.key, required this.code});

  final String code;

  @override
  ConsumerState<AuditScreen> createState() => _AuditScreenState();
}

class _AuditScreenState extends ConsumerState<AuditScreen> {
  String? _check;
  bool _running = false;

  Future<void> _run() async {
    setState(() => _running = true);
    try {
      await runAudit(ref, widget.code);
    } on ApiError catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    } finally {
      if (mounted) setState(() => _running = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final wide = MediaQuery.sizeOf(context).width >= 720;
    final code = widget.code;
    final audit = ref.watch(auditProvider(code));
    final usd = ref.watch(auditEstimateProvider(code)).value;
    final run = audit.value;
    final cost = usd == null ? '' : ' · ≈ ${dollars(usd)}';
    final findings = run?.findings ?? const <AuditFinding>[];
    final shown = [
      for (final f in findings)
        if (_check == null || f.check == _check) f,
    ];
    final counts = <String, int>{};
    for (final f in findings) {
      counts[f.check] = (counts[f.check] ?? 0) + 1;
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        TeachHeader(
          kicker: '$code · Content audit',
          title: run == null ? 'Content audit' : '${run.total} ${run.total == 1 ? 'finding' : 'findings'}',
          subtitle: run == null
              ? 'Checks the live version: accessibility, question writing, Bloom balance, coverage and more.'
              : 'Run on version ${run.kcVersion} · ${run.date} · ${run.reviewed} reviewed',
          actions: [
            if (wide)
              FilledButton(
                onPressed: _running || audit.isLoading ? null : _run,
                child: Text(_running ? 'Running…' : '${run == null ? 'Run the audit' : 'Run audit again'}$cost'),
              ),
          ],
        ),
        Expanded(
          child: switch (audit) {
            AsyncError(:final error) => Padding(
              padding: const EdgeInsets.all(24),
              child: TeachError(error: error, onRetry: () => ref.invalidate(auditProvider(code))),
            ),
            AsyncData() => ListView(
              padding: EdgeInsets.fromLTRB(wide ? 24 : 16, 18, wide ? 24 : 16, 24),
              children: [
                if (!wide) ...[const DesktopOnlyNote(), const SizedBox(height: 12)],
                if (run == null)
                  const TeachBanner(
                    child: Text(
                      'No audit yet. Findings are suggestions ranked by how much they matter; '
                      'you decide which to act on.',
                    ),
                  )
                else ...[
                  for (final s in run.skipped) ...[
                    TeachBanner(tone: BannerTone.soft, child: Text(s)),
                    const SizedBox(height: 10),
                  ],
                  Wrap(
                    spacing: 6,
                    runSpacing: 6,
                    crossAxisAlignment: WrapCrossAlignment.center,
                    children: [
                      ChoiceChip(
                        label: Text('All ${findings.length}'),
                        selected: _check == null,
                        onSelected: (_) => setState(() => _check = null),
                      ),
                      for (final MapEntry(key: k, value: n) in counts.entries)
                        ChoiceChip(
                          label: Text('${auditChecks[k] ?? k} $n'),
                          selected: _check == k,
                          onSelected: (_) => setState(() => _check = k),
                        ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  Text(
                    'Evidence tiers say how far each kind of check has been validated: Well supported and Rule-based '
                    'checks are reliable; Experimental ones are hypotheses to look at.',
                    style: LeaType.ui(12).copyWith(color: c.muted),
                  ),
                  const SizedBox(height: 12),
                  if (shown.isEmpty)
                    const TeachBanner(tone: BannerTone.ok, child: Text('Nothing found here.'))
                  else
                    TeachCard(
                      padding: EdgeInsets.zero,
                      child: Column(
                        children: [
                          for (final (i, f) in shown.indexed)
                            _FindingTile(code: code, finding: f, first: i == 0, editable: wide),
                        ],
                      ),
                    ),
                  if (run.resolved.isNotEmpty) ...[
                    const SizedBox(height: 16),
                    ExpansionTile(
                      tilePadding: EdgeInsets.zero,
                      title: Text(
                        'Resolved since the last run (${run.resolved.length})',
                        style: LeaType.ui(13.5, weight: FontWeight.w600).copyWith(color: c.ink),
                      ),
                      children: [
                        for (final t in run.resolved)
                          Align(
                            alignment: Alignment.centerLeft,
                            child: Padding(
                              padding: const EdgeInsets.only(bottom: 4),
                              child: Text('✓ $t', style: LeaType.ui(12.5).copyWith(color: c.muted)),
                            ),
                          ),
                      ],
                    ),
                  ],
                ],
              ],
            ),
            _ => const Padding(padding: EdgeInsets.all(24), child: SkeletonBox(height: 200)),
          },
        ),
      ],
    );
  }
}

class _FindingTile extends ConsumerWidget {
  const _FindingTile({required this.code, required this.finding, required this.first, required this.editable});

  final String code;
  final AuditFinding finding;
  final bool first;
  final bool editable;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.lea;
    final f = finding;
    final bar = switch (f.severity) {
      'high' => c.danger,
      'medium' => c.warning,
      _ => c.muted,
    };
    final tierTone = switch (f.tier) {
      'well_supported' || 'rule_based' => PillTone.ok,
      'experimental' => PillTone.dashed,
      _ => PillTone.outline,
    };
    Future<void> decide(String status, [String note = '']) async {
      try {
        await decideFinding(ref, code, f.key, status, note);
      } on ApiError catch (e) {
        if (context.mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
      }
    }

    final decision = switch (f.status) {
      'accepted' => TeachPill(f.note.isEmpty ? 'Accepted' : 'Accepted · “${f.note}”', tone: PillTone.ok),
      'dismissed' => TeachPill(f.note.isEmpty ? 'Dismissed' : 'Dismissed · “${f.note}”', tone: PillTone.outline),
      _ => null,
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
      decoration: BoxDecoration(
        border: first ? null : Border(top: BorderSide(color: c.line)),
      ),
      child: IntrinsicHeight(
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Semantics(
              label: 'Severity ${f.severity}',
              child: Container(
                width: 4,
                decoration: BoxDecoration(color: bar, borderRadius: BorderRadius.circular(99)),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Wrap(
                    spacing: 8,
                    runSpacing: 4,
                    crossAxisAlignment: WrapCrossAlignment.center,
                    children: [
                      Text(
                        f.title,
                        style: LeaType.ui(13.5, weight: FontWeight.w600).copyWith(color: c.ink),
                      ),
                      TeachPill(auditTiers[f.tier] ?? f.tier, tone: tierTone),
                      if (f.llm) TeachPill('LLM suggestion', tone: PillTone.outline),
                      if (f.isNew) const TeachPill('New', tone: PillTone.warn),
                    ],
                  ),
                  const SizedBox(height: 3),
                  Text(f.explanation, style: LeaType.ui(12.5).copyWith(color: c.muted)),
                  if (f.evidence.isNotEmpty) ...[
                    const SizedBox(height: 6),
                    Container(
                      width: double.infinity,
                      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
                      decoration: BoxDecoration(color: c.bg, borderRadius: BorderRadius.circular(8)),
                      child: Text(f.evidence, style: LeaType.ui(12.5).copyWith(color: c.ink)),
                    ),
                  ],
                ],
              ),
            ),
            const SizedBox(width: 12),
            Column(
              mainAxisAlignment: MainAxisAlignment.center,
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                if (decision != null) ...[
                  decision,
                  if (editable) TextButton(onPressed: () => decide('open'), child: const Text('Reopen')),
                ] else if (editable) ...[
                  FilledButton(onPressed: () => decide('accepted'), child: const Text('Accept')),
                  const SizedBox(height: 6),
                  GhostButton(
                    label: 'Dismiss…',
                    onPressed: () async {
                      final note = await showDialog<String>(context: context, builder: (_) => const _DismissDialog());
                      if (note != null) await decide('dismissed', note);
                    },
                  ),
                ],
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _DismissDialog extends StatefulWidget {
  const _DismissDialog();

  @override
  State<_DismissDialog> createState() => _DismissDialogState();
}

class _DismissDialogState extends State<_DismissDialog> {
  final _note = TextEditingController();

  @override
  void dispose() {
    _note.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: const Text('Dismiss this finding?'),
    content: SizedBox(
      width: 400,
      child: TextField(
        key: const Key('dismiss-note'),
        controller: _note,
        decoration: const InputDecoration(labelText: 'Why (optional), e.g. "intended"', border: OutlineInputBorder()),
      ),
    ),
    actions: [
      TextButton(onPressed: () => Navigator.of(context).pop(), child: const Text('Cancel')),
      FilledButton(onPressed: () => Navigator.of(context).pop(_note.text.trim()), child: const Text('Dismiss')),
    ],
  );
}
