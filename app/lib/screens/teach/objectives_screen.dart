import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../teach/download.dart';
import '../../teach/kc_state.dart';
import '../../teach/setup_state.dart';
import '../../teach/teach_models.dart';
import '../../teach/teach_state.dart';
import '../../teach/teach_widgets.dart';
import '../../theme/lea_colors.dart';
import '../../theme/lea_type.dart';
import '../../widgets/ghost_button.dart';
import '../../widgets/skeleton.dart';

const _xlsx = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';

/// Picks one spreadsheet for import (tests override this).
final spreadsheetPickerProvider = Provider<Future<PickedFile?> Function()>(
  (ref) => () async {
    final files = await FilePicker.pickFiles(type: FileType.custom, allowedExtensions: ['xlsx']);
    if (files.isEmpty) return null;
    return (name: files.first.name, bytes: await files.first.xFile.readAsBytes());
  },
);

/// Objectives (`kc-*.png`): the KC draft as a table by week and learning objective, with
/// checks and row details at the side. IDs are shown but never editable.
class ObjectivesScreen extends ConsumerStatefulWidget {
  const ObjectivesScreen({super.key, required this.code, this.from});

  final String code;

  /// `job:<id>` when arriving from a finished build.
  final String? from;

  @override
  ConsumerState<ObjectivesScreen> createState() => _ObjectivesScreenState();
}

class _ObjectivesScreenState extends ConsumerState<ObjectivesScreen> {
  int? _week;

  @override
  Widget build(BuildContext context) {
    final wide = MediaQuery.sizeOf(context).width >= 720;
    final code = widget.code;
    final edit = ref.watch(kcEditorProvider(code));
    final editor = ref.read(kcEditorProvider(code).notifier);
    final overview = ref.watch(kcOverviewProvider(code)).value;
    final live = overview?.publishedVersion;
    final draft = edit.draft;

    final List<Widget> actions;
    if (draft == null || !wide) {
      actions = [
        if (overview != null && live != null) GhostButton(label: 'Export to Excel', onPressed: () => _export(editor)),
      ];
    } else {
      actions = [
        GhostButton(label: 'Export to Excel', onPressed: edit.busy ? null : () => _export(editor)),
        GhostButton(label: 'Import', onPressed: edit.busy ? null : () => _import(editor)),
        DangerButton(label: 'Discard draft', onPressed: edit.busy ? null : () => _discard(editor)),
        if (edit.dirty)
          FilledButton(onPressed: edit.busy ? null : editor.save, child: const Text('Save draft'))
        else
          FilledButton(
            onPressed: edit.busy || edit.errors > 0
                ? null
                : () => context.go('${TeachSection.objectives.path(code)}/review'),
            child: const Text('Review changes'),
          ),
      ];
    }

    final String title;
    final String? subtitle;
    if (draft != null) {
      title = 'Objectives: draft';
      subtitle = [
        draft.basedOn == null ? 'New model' : 'Based on version ${draft.basedOn}',
        if (draft.source.startsWith('job:')) 'from a build',
        if (draft.source == 'import') 'imported from Excel',
        '${draft.saves} ${draft.saves == 1 ? 'save' : 'saves'}',
        if (edit.dirty) 'unsaved changes',
      ].join(' · ');
    } else {
      title = live == null ? 'Objectives' : 'Objectives: version $live (live)';
      subtitle = live == null ? 'Nothing published yet.' : 'Students use this version.';
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        TeachHeader(kicker: '$code · Objectives', title: title, subtitle: subtitle, actions: actions),
        Expanded(
          child: edit.loading
              ? const Padding(padding: EdgeInsets.all(24), child: SkeletonBox(height: 200))
              : edit.loadError != null
              ? Padding(
                  padding: const EdgeInsets.all(24),
                  child: TeachError(error: edit.loadError!, onRetry: editor.load),
                )
              : draft == null
              ? _NoDraft(code: code, live: live, from: widget.from, wide: wide, busy: edit.busy, error: edit.error)
              : _DraftView(
                  code: code,
                  edit: edit,
                  wide: wide,
                  week: _week ?? (edit.rows.isEmpty ? 1 : edit.rows.first.week),
                  onWeek: (w) => setState(() => _week = w),
                ),
        ),
      ],
    );
  }

  Future<void> _export(KCEditor editor) async {
    final bytes = await editor.export();
    if (bytes != null) await saveBytes('${widget.code}_kc_model.xlsx', bytes, _xlsx);
  }

  Future<void> _import(KCEditor editor) async {
    final file = await ref.read(spreadsheetPickerProvider)();
    if (file == null) return;
    final ok = await editor.import(file.name, file.bytes);
    if (ok && mounted) context.go('${TeachSection.objectives.path(widget.code)}/review');
  }

  Future<void> _discard(KCEditor editor) async {
    final sure = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Discard the draft?'),
        content: const Text('Your edits are lost. Students keep the published version.'),
        actions: [
          TextButton(onPressed: () => Navigator.of(context).pop(false), child: const Text('Keep editing')),
          FilledButton(onPressed: () => Navigator.of(context).pop(true), child: const Text('Discard')),
        ],
      ),
    );
    if (sure == true) await editor.discard();
  }
}

class _NoDraft extends ConsumerWidget {
  const _NoDraft({
    required this.code,
    required this.live,
    required this.from,
    required this.wide,
    required this.busy,
    this.error,
  });

  final String code;
  final int? live;
  final String? from;
  final bool wide;
  final bool busy;
  final String? error;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.lea;
    final editor = ref.read(kcEditorProvider(code).notifier);
    final latestJob = ref.watch(latestJobProvider(code)).value;
    final jobSource = from ?? (latestJob?.status == 'succeeded' ? 'job:${latestJob!.id}' : null);
    return ListView(
      padding: EdgeInsets.fromLTRB(wide ? 24 : 16, 18, wide ? 24 : 16, 24),
      children: [
        if (!wide) ...[const DesktopOnlyNote(), const SizedBox(height: 14)],
        if (error != null) ...[TeachBanner(tone: BannerTone.bad, child: Text(error!)), const SizedBox(height: 14)],
        TeachCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('No draft', style: LeaType.heading(17).copyWith(color: c.ink)),
              const SizedBox(height: 4),
              Text(
                live == null
                    ? 'Build the course from its materials, then review the drafted objectives here.'
                    : 'Start a draft to change the objectives. Students keep version $live until you publish.',
                style: LeaType.small().copyWith(color: c.muted),
              ),
              if (wide) ...[
                const SizedBox(height: 12),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    if (jobSource != null)
                      FilledButton(
                        onPressed: busy ? null : () => editor.start(jobSource),
                        child: const Text("Review the build's draft"),
                      ),
                    if (live != null && jobSource == null)
                      FilledButton(
                        onPressed: busy ? null : () => editor.start('published'),
                        child: const Text('Edit the live objectives'),
                      )
                    else if (live != null)
                      GhostButton(
                        label: 'Edit the live objectives',
                        onPressed: busy ? null : () => editor.start('published'),
                      ),
                  ],
                ),
              ],
            ],
          ),
        ),
      ],
    );
  }
}

class _DraftView extends ConsumerWidget {
  const _DraftView({
    required this.code,
    required this.edit,
    required this.wide,
    required this.week,
    required this.onWeek,
  });

  final String code;
  final KCEditState edit;
  final bool wide;
  final int week;
  final ValueChanged<int> onWeek;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final editor = ref.read(kcEditorProvider(code).notifier);
    final weeks = {for (final r in edit.rows) r.week}.toList()..sort();
    final indexed = [
      for (final (i, r) in edit.rows.indexed)
        if (r.week == week) (i, r),
    ];
    final los = <String, List<(int, KCRow)>>{};
    for (final (i, r) in indexed) {
      (los[r.loId ?? 'new:${r.loTitle}'] ??= []).add((i, r));
    }
    final table = Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (edit.error != null) ...[
          TeachBanner(tone: BannerTone.bad, child: Text(edit.error!)),
          const SizedBox(height: 12),
        ],
        Wrap(
          spacing: 4,
          children: [
            for (final w in weeks)
              ChoiceChip(label: Text('Week $w'), selected: w == week, onSelected: (_) => onWeek(w)),
          ],
        ),
        const SizedBox(height: 12),
        for (final entry in los.entries) ...[
          _LoCard(
            rows: entry.value,
            selected: edit.selected,
            onSelect: editor.select,
            onAdd: wide ? () => editor.addAfter(entry.value.last.$1) : null,
            onMerge: wide && entry.value.where((e) => e.$2.goId != null).length >= 2
                ? () => _merge(context, editor, entry.value)
                : null,
            issues: edit.issues,
          ),
          const SizedBox(height: 12),
        ],
      ],
    );
    final side = Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _Checks(edit: edit, onCheck: editor.check),
        if (edit.selected != null && edit.selected! < edit.rows.length) ...[
          const SizedBox(height: 12),
          _RowDetails(
            key: ValueKey('row-${edit.selected}-${edit.rows[edit.selected!].goId}'),
            index: edit.selected!,
            row: edit.rows[edit.selected!],
            editable: wide,
            onApply: (row) => editor.update(edit.selected!, row),
            onRemove: () => editor.remove(edit.selected!),
            onSplit: edit.rows[edit.selected!].goId == null ? null : () => editor.split(edit.selected!),
          ),
        ],
      ],
    );
    return LayoutBuilder(
      builder: (context, constraints) {
        final pad = EdgeInsets.fromLTRB(wide ? 24 : 16, 18, wide ? 24 : 16, 24);
        if (constraints.maxWidth >= 980) {
          return SingleChildScrollView(
            padding: pad,
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(child: table),
                const SizedBox(width: 16),
                SizedBox(width: 330, child: side),
              ],
            ),
          );
        }
        return ListView(
          padding: pad,
          children: [if (!wide) const DesktopOnlyNote(), side, const SizedBox(height: 12), table],
        );
      },
    );
  }

  Future<void> _merge(BuildContext context, KCEditor editor, List<(int, KCRow)> rows) async {
    final result = await showDialog<(List<int>, String)>(
      context: context,
      builder: (_) => _MergeDialog(rows: rows),
    );
    if (result != null) editor.merge(result.$1, result.$2);
  }
}

class _LoCard extends StatelessWidget {
  const _LoCard({
    required this.rows,
    required this.selected,
    required this.onSelect,
    required this.onAdd,
    required this.onMerge,
    required this.issues,
  });

  final List<(int, KCRow)> rows;
  final int? selected;
  final ValueChanged<int> onSelect;
  final VoidCallback? onAdd;
  final VoidCallback? onMerge;
  final List<KCIssue> issues;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final first = rows.first.$2;
    final head = LeaType.label(11).copyWith(color: c.muted);
    return TeachCard(
      padding: EdgeInsets.zero,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
            decoration: BoxDecoration(
              color: c.bg,
              borderRadius: const BorderRadius.vertical(top: Radius.circular(12)),
              border: Border(bottom: BorderSide(color: c.line)),
            ),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                IdText(first.loId ?? 'new'),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    first.loTitle,
                    style: LeaType.ui(13.5, weight: FontWeight.w600).copyWith(color: c.ink),
                  ),
                ),
                if (first.loShortTitle.isNotEmpty) ...[
                  const SizedBox(width: 10),
                  Text('Short title: ${first.loShortTitle}', style: LeaType.ui(12).copyWith(color: c.muted)),
                ],
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 8, 12, 4),
            child: Row(
              children: [
                Expanded(flex: 5, child: Text('OBJECTIVE', style: head)),
                Expanded(flex: 2, child: Text('BLOOM', style: head)),
                Expanded(
                  flex: 2,
                  child: Text('THRESHOLD', style: head, textAlign: TextAlign.right),
                ),
                const SizedBox(width: 12),
                Expanded(flex: 3, child: Text('CONTENT MATCH', style: head)),
              ],
            ),
          ),
          for (final (i, r) in rows)
            _RowTile(
              index: i,
              row: r,
              selected: selected == i,
              onTap: () => onSelect(i),
              hasError: issues.any((x) => x.error && x.row == i + 1),
            ),
          Padding(
            padding: const EdgeInsets.fromLTRB(4, 2, 4, 4),
            child: Wrap(
              children: [
                if (onAdd != null) TextButton(onPressed: onAdd, child: const Text('+ Add objective')),
                if (onMerge != null) TextButton(onPressed: onMerge, child: const Text('Merge…')),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _RowTile extends StatelessWidget {
  const _RowTile({
    required this.index,
    required this.row,
    required this.selected,
    required this.onTap,
    required this.hasError,
  });

  final int index;
  final KCRow row;
  final bool selected;
  final VoidCallback onTap;
  final bool hasError;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final sim = row.similarity;
    final weak = sim != null && sim < 0.45;
    return Material(
      color: selected ? c.surface2 : Colors.transparent,
      child: InkWell(
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
          decoration: BoxDecoration(
            border: Border(top: BorderSide(color: c.line)),
          ),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                flex: 5,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      row.skillName,
                      style: LeaType.ui(13, weight: FontWeight.w500).copyWith(color: c.ink),
                    ),
                    Wrap(
                      spacing: 6,
                      crossAxisAlignment: WrapCrossAlignment.center,
                      children: [
                        IdText(row.goId ?? 'new · ID when saved'),
                        if (row.splitFrom != null) TeachPill('Split from ${row.splitFrom}'),
                        if (row.mergedFrom.isNotEmpty) TeachPill('Merged from ${row.mergedFrom.length}'),
                      ],
                    ),
                    if (weak && row.excerpt != null)
                      Container(
                        margin: const EdgeInsets.only(top: 4),
                        padding: const EdgeInsets.only(left: 8),
                        decoration: BoxDecoration(
                          border: Border(left: BorderSide(color: c.line, width: 3)),
                        ),
                        child: Text(
                          '“${row.excerpt}” · ${row.source ?? ''}',
                          style: LeaType.ui(12).copyWith(color: c.muted),
                          maxLines: 3,
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                  ],
                ),
              ),
              Expanded(
                flex: 2,
                child: Align(
                  alignment: Alignment.centerLeft,
                  child: TeachPill(row.cognitiveLevel, tone: PillTone.outline),
                ),
              ),
              Expanded(
                flex: 2,
                child: Text(
                  row.masteryThreshold.toStringAsFixed(2),
                  textAlign: TextAlign.right,
                  style: LeaType.ui(13).copyWith(
                    color: hasError ? c.danger : c.ink,
                    decoration: hasError ? TextDecoration.underline : null,
                    decorationColor: c.danger,
                  ),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                flex: 3,
                child: sim == null
                    ? Text('—', style: LeaType.ui(12.5).copyWith(color: c.muted))
                    : weak
                    ? Text('▲ Weak support', style: LeaType.ui(12.5).copyWith(color: c.warning))
                    : Text(sim.toStringAsFixed(2), style: LeaType.ui(12.5).copyWith(color: c.ink)),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _Checks extends StatelessWidget {
  const _Checks({required this.edit, required this.onCheck});

  final KCEditState edit;
  final VoidCallback onCheck;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final errors = edit.issues.where((i) => i.error).toList();
    final warnings = edit.issues.where((i) => !i.error).toList();
    String where(KCIssue i) => i.row == null ? '' : 'Row ${i.row} · ';
    return TeachCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Expanded(
                child: Text('Checks', style: LeaType.heading(16).copyWith(color: c.ink)),
              ),
              if (edit.dirty) TextButton(onPressed: edit.busy ? null : onCheck, child: const Text('Check now')),
            ],
          ),
          const SizedBox(height: 8),
          if (errors.isEmpty && warnings.isEmpty)
            const TeachBanner(tone: BannerTone.ok, child: Text('No problems found.')),
          if (errors.isNotEmpty) ...[
            TeachBanner(
              tone: BannerTone.bad,
              child: Text(
                '${errors.length} ${errors.length == 1 ? 'problem stops' : 'problems stop'} this draft being saved',
              ),
            ),
            for (final i in errors)
              Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Text('${where(i)}${i.message}', style: LeaType.ui(12.5).copyWith(color: c.ink)),
              ),
            const SizedBox(height: 8),
          ],
          if (warnings.isNotEmpty) ...[
            TeachBanner(
              tone: BannerTone.soft,
              child: Text('${warnings.length} ${warnings.length == 1 ? 'warning' : 'warnings'}'),
            ),
            for (final i in warnings)
              Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Text('${where(i)}${i.message}', style: LeaType.ui(12.5).copyWith(color: c.ink)),
              ),
          ],
        ],
      ),
    );
  }
}

/// The selected row's fields; Apply changes the draft locally (Save draft stores it).
class _RowDetails extends StatefulWidget {
  const _RowDetails({
    super.key,
    required this.index,
    required this.row,
    required this.editable,
    required this.onApply,
    required this.onRemove,
    required this.onSplit,
  });

  final int index;
  final KCRow row;
  final bool editable;
  final ValueChanged<KCRow> onApply;
  final VoidCallback onRemove;
  final VoidCallback? onSplit;

  @override
  State<_RowDetails> createState() => _RowDetailsState();
}

class _RowDetailsState extends State<_RowDetails> {
  late final _name = TextEditingController(text: widget.row.skillName);
  late final _description = TextEditingController(text: widget.row.description);
  late final _threshold = TextEditingController(text: widget.row.masteryThreshold.toStringAsFixed(2));
  late final _keywords = TextEditingController(text: widget.row.keywords.join(', '));
  late String _bloom = bloomLevels.contains(widget.row.cognitiveLevel) ? widget.row.cognitiveLevel : 'Understand';

  @override
  void dispose() {
    for (final c in [_name, _description, _threshold, _keywords]) {
      c.dispose();
    }
    super.dispose();
  }

  void _apply() {
    widget.onApply(
      widget.row.copyWith(
        skillName: _name.text.trim(),
        description: _description.text.trim(),
        cognitiveLevel: _bloom,
        masteryThreshold: double.tryParse(_threshold.text.trim()) ?? widget.row.masteryThreshold,
        keywords: [
          for (final k in _keywords.text.split(','))
            if (k.trim().isNotEmpty) k.trim(),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    InputDecoration deco(String label) =>
        InputDecoration(labelText: label, border: const OutlineInputBorder(), isDense: true);
    final row = widget.row;
    return TeachCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text('Row ${widget.index + 1} details', style: LeaType.heading(16).copyWith(color: c.ink)),
          const SizedBox(height: 4),
          IdText(row.goId ?? 'New: LEA assigns the ID when you save'),
          const SizedBox(height: 10),
          TextField(
            key: const Key('row-name'),
            controller: _name,
            enabled: widget.editable,
            decoration: deco('Objective name'),
          ),
          const SizedBox(height: 10),
          TextField(
            key: const Key('row-description'),
            controller: _description,
            enabled: widget.editable,
            minLines: 2,
            maxLines: 5,
            decoration: deco('Description'),
          ),
          const SizedBox(height: 10),
          Row(
            children: [
              Expanded(
                child: DropdownButtonFormField<String>(
                  isExpanded: true,
                  initialValue: _bloom,
                  decoration: deco('Bloom level'),
                  items: [for (final b in bloomLevels) DropdownMenuItem(value: b, child: Text(b))],
                  onChanged: widget.editable ? (v) => setState(() => _bloom = v ?? _bloom) : null,
                ),
              ),
              const SizedBox(width: 10),
              SizedBox(
                width: 110,
                child: TextField(
                  key: const Key('row-threshold'),
                  controller: _threshold,
                  enabled: widget.editable,
                  decoration: deco('Threshold'),
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          TextField(
            key: const Key('row-keywords'),
            controller: _keywords,
            enabled: widget.editable,
            decoration: deco('Keywords'),
          ),
          if (row.prerequisites.isNotEmpty) ...[
            const SizedBox(height: 10),
            Text('PREREQUISITES', style: LeaType.label(11).copyWith(color: c.muted)),
            const SizedBox(height: 4),
            Wrap(
              spacing: 6,
              runSpacing: 6,
              children: [for (final p in row.prerequisites) TeachPill(p, tone: PillTone.outline)],
            ),
          ],
          if (row.excerpt != null) ...[
            const SizedBox(height: 10),
            Text('SOURCE EXCERPT', style: LeaType.label(11).copyWith(color: c.muted)),
            const SizedBox(height: 4),
            Text('“${row.excerpt}” (${row.source ?? ''})', style: LeaType.ui(12).copyWith(color: c.muted)),
          ],
          if (widget.editable) ...[
            const SizedBox(height: 12),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                FilledButton(onPressed: _apply, child: const Text('Apply')),
                if (widget.onSplit != null) GhostButton(label: 'Split in two', onPressed: widget.onSplit),
                DangerButton(label: 'Remove', onPressed: widget.onRemove),
              ],
            ),
          ],
        ],
      ),
    );
  }
}

class _MergeDialog extends StatefulWidget {
  const _MergeDialog({required this.rows});

  final List<(int, KCRow)> rows;

  @override
  State<_MergeDialog> createState() => _MergeDialogState();
}

class _MergeDialogState extends State<_MergeDialog> {
  final _chosen = <int>{};
  final _name = TextEditingController();

  @override
  void dispose() {
    _name.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final ok = _chosen.length >= 2 && _name.text.trim().isNotEmpty;
    return AlertDialog(
      title: const Text('Merge objectives'),
      content: SizedBox(
        width: 420,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text('Students get the average of their mastery on the ones you merge.'),
            for (final (i, r) in widget.rows)
              if (r.goId != null)
                CheckboxListTile(
                  value: _chosen.contains(i),
                  title: Text(r.skillName),
                  subtitle: Text(r.goId!),
                  onChanged: (v) => setState(() => v == true ? _chosen.add(i) : _chosen.remove(i)),
                ),
            TextField(
              key: const Key('merge-name'),
              controller: _name,
              onChanged: (_) => setState(() {}),
              decoration: const InputDecoration(labelText: 'Name of the merged objective'),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.of(context).pop(), child: const Text('Cancel')),
        FilledButton(
          onPressed: ok ? () => Navigator.of(context).pop((_chosen.toList()..sort(), _name.text.trim())) : null,
          child: const Text('Merge'),
        ),
      ],
    );
  }
}
