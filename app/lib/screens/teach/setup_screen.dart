import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../api/api_error.dart';
import '../../teach/setup_state.dart';
import '../../teach/teach_models.dart';
import '../../teach/teach_state.dart';
import '../../teach/teach_widgets.dart';
import '../../theme/lea_colors.dart';
import '../../theme/lea_type.dart';
import '../../widgets/ghost_button.dart';
import '../../widgets/meter.dart';
import '../../widgets/skeleton.dart';

/// Setup and materials (`setup-*.png`): uploads and weekly objectives on the left, the
/// Build card on the right. A build is priced first and runs only when the teacher starts it.
class SetupScreen extends ConsumerWidget {
  const SetupScreen({super.key, required this.code});

  final String code;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final wide = MediaQuery.sizeOf(context).width >= 720;
    final course = ref.watch(teachCourseProvider(code));
    final live = course.value?.hasKcModel ?? false;
    final managed = course.value?.managed ?? true;
    final left = [
      if (!wide) ...[const DesktopOnlyNote(), const SizedBox(height: 14)],
      if (!managed)
        const TeachBanner(
          child: Text(
            'This course was set up by hand, so its files are managed outside LEA. You can still edit its objectives.',
          ),
        )
      else ...[
        _MaterialsCard(code: code, editable: wide),
        const SizedBox(height: 14),
        _LinkedMaterialsCard(code: code, editable: wide),
        const SizedBox(height: 14),
        _PlanCard(code: code, weeks: course.value?.weeks ?? 0, editable: wide),
      ],
    ];
    final right = managed ? [_BuildCard(code: code, editable: wide)] : const <Widget>[];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        TeachHeader(
          kicker: '$code · Setup',
          title: 'Setup and materials',
          subtitle: live
              ? 'Students use the published objectives.'
              : "Students can't see this course until its objectives are published.",
        ),
        Expanded(
          child: course.hasError && course.value == null
              ? Padding(
                  padding: const EdgeInsets.all(24),
                  child: TeachError(error: course.error!, onRetry: () => ref.invalidate(teachCourseProvider(code))),
                )
              : LayoutBuilder(
                  builder: (context, constraints) {
                    final pad = EdgeInsets.fromLTRB(wide ? 24 : 16, 18, wide ? 24 : 16, 24);
                    if (constraints.maxWidth >= 980) {
                      return SingleChildScrollView(
                        padding: pad,
                        child: Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Expanded(
                              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: left),
                            ),
                            if (right.isNotEmpty) ...[
                              const SizedBox(width: 16),
                              SizedBox(width: 330, child: Column(children: right)),
                            ],
                          ],
                        ),
                      );
                    }
                    return ListView(
                      padding: pad,
                      children: [...right, if (right.isNotEmpty) const SizedBox(height: 14), ...left],
                    );
                  },
                ),
        ),
      ],
    );
  }
}

void _showError(BuildContext context, ApiError e) =>
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));

// ---------------------------------------------------------------------------- materials

class _MaterialsCard extends ConsumerWidget {
  const _MaterialsCard({required this.code, required this.editable});

  final String code;
  final bool editable;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.lea;
    final uploads = ref.watch(uploadsProvider(code));
    final list = uploads.value ?? const <CourseUpload>[];
    final total = list.fold<int>(0, (s, u) => s + u.size);
    final actions = SetupActions(ref, code);
    return TeachCard(
      padding: EdgeInsets.zero,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 14, 16, 10),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('Materials', style: LeaType.heading(17).copyWith(color: c.ink)),
                      Text(
                        '${list.length} ${list.length == 1 ? 'file' : 'files'} · ${(total / 1e6).toStringAsFixed(1)} MB of 1 GB · '
                        'PDF, Word, PowerPoint, Excel, Markdown, text, notebooks, MP3, MP4, WAV (50 MB each)',
                        style: LeaType.ui(12).copyWith(color: c.muted),
                      ),
                    ],
                  ),
                ),
                if (editable) ...[
                  const SizedBox(width: 12),
                  FilledButton(onPressed: () => _upload(context, ref, actions), child: const Text('Upload files')),
                ],
              ],
            ),
          ),
          switch (uploads) {
            AsyncData() when list.isEmpty => Padding(
              padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
              child: Text(
                'No files yet. Upload the course\'s slides, readings, notebooks and recordings.',
                style: LeaType.small().copyWith(color: c.muted),
              ),
            ),
            AsyncData() => _UploadTable(uploads: list, onDelete: editable ? (u) => _delete(context, actions, u) : null),
            AsyncError(:final error) => Padding(
              padding: const EdgeInsets.all(16),
              child: TeachError(error: error, onRetry: () => ref.invalidate(uploadsProvider(code))),
            ),
            _ => const Padding(padding: EdgeInsets.all(16), child: SkeletonBox(height: 80)),
          },
        ],
      ),
    );
  }

  Future<void> _upload(BuildContext context, WidgetRef ref, SetupActions actions) async {
    final files = await ref.read(filePickerProvider)();
    if (files.isEmpty || !context.mounted) return;
    final weeks = ref.read(teachCourseProvider(code)).value?.weeks ?? 1;
    final choice = await showDialog<({int? week, String? kind})>(
      context: context,
      builder: (_) => _UploadOptionsDialog(files: files, weeks: weeks),
    );
    if (choice == null) return;
    try {
      await actions.upload(files, week: choice.week, kind: choice.kind);
    } on ApiError catch (e) {
      if (context.mounted) _showError(context, e);
    }
  }

  Future<void> _delete(BuildContext context, SetupActions actions, CourseUpload u) async {
    try {
      await actions.deleteUpload(u.name);
    } on ApiError catch (e) {
      if (context.mounted) _showError(context, e);
    }
  }
}

class _UploadTable extends StatelessWidget {
  const _UploadTable({required this.uploads, required this.onDelete});

  final List<CourseUpload> uploads;
  final ValueChanged<CourseUpload>? onDelete;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    TextStyle head = LeaType.label(11).copyWith(color: c.muted);
    TextStyle cell = LeaType.ui(13).copyWith(color: c.ink);
    Widget row(List<Widget> cells, {bool header = false}) => Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      decoration: BoxDecoration(
        border: Border(top: BorderSide(color: c.line)),
      ),
      child: Row(
        children: [
          Expanded(flex: 5, child: cells[0]),
          Expanded(flex: 1, child: cells[1]),
          Expanded(flex: 2, child: cells[2]),
          Expanded(
            flex: 2,
            child: Align(alignment: Alignment.centerRight, child: cells[3]),
          ),
          SizedBox(width: 40, child: cells.length > 4 ? cells[4] : null),
        ],
      ),
    );
    return Column(
      children: [
        row([
          Text('FILE', style: head),
          Text('WEEK', style: head),
          Text('KIND', style: head),
          Text('SIZE', style: head),
        ]),
        for (final u in uploads)
          row([
            Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Flexible(
                  child: Text(u.name, style: cell, overflow: TextOverflow.ellipsis),
                ),
                if (u.isLinked) ...[const SizedBox(width: 6), const TeachPill('Linked', tone: PillTone.outline)],
              ],
            ),
            Text(u.week == null ? '—' : '${u.week}', style: cell),
            Text(u.kind ?? 'From file type', style: u.kind == null ? cell.copyWith(color: c.muted) : cell),
            Text(u.sizeLabel, style: cell),
            if (onDelete != null)
              IconButton(
                tooltip: 'Delete ${u.name}',
                visualDensity: VisualDensity.compact,
                icon: Icon(Icons.delete_outline, size: 18, color: c.muted),
                onPressed: () => onDelete!(u),
              ),
          ]),
      ],
    );
  }
}

/// "Linked materials": a read-only folder under the materials root, ingested by a Build
/// job alongside any uploads. See docs/API.md's "Linked materials sources".
class _LinkedMaterialsCard extends ConsumerWidget {
  const _LinkedMaterialsCard({required this.code, required this.editable});

  final String code;
  final bool editable;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.lea;
    final source = ref.watch(materialsSourceProvider(code));
    final actions = SetupActions(ref, code);
    return TeachCard(
      padding: EdgeInsets.zero,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 14, 16, 10),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('Linked materials', style: LeaType.heading(17).copyWith(color: c.ink)),
                      Text(
                        'A read-only folder a Build job ingests alongside uploads.',
                        style: LeaType.ui(12).copyWith(color: c.muted),
                      ),
                    ],
                  ),
                ),
                if (editable && source.value != null) ...[
                  const SizedBox(width: 12),
                  DangerButton(label: 'Unlink', onPressed: () => _unlink(context, actions)),
                ],
              ],
            ),
          ),
          switch (source) {
            AsyncData(value: null) => Padding(
              padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
              child: editable
                  ? _FolderPicker(code: code, actions: actions)
                  : Text('No folder linked.', style: LeaType.small().copyWith(color: c.muted)),
            ),
            AsyncData(value: final linked!) => _SyncPreviewView(code: code, path: linked.path),
            AsyncError(:final error) => Padding(
              padding: const EdgeInsets.all(16),
              child: TeachError(error: error, onRetry: () => ref.invalidate(materialsSourceProvider(code))),
            ),
            _ => const Padding(padding: EdgeInsets.all(16), child: SkeletonBox(height: 40)),
          },
        ],
      ),
    );
  }

  Future<void> _unlink(BuildContext context, SetupActions actions) async {
    try {
      await actions.unlinkMaterialsSource();
    } on ApiError catch (e) {
      if (context.mounted) _showError(context, e);
    }
  }
}

class _FolderPicker extends ConsumerStatefulWidget {
  const _FolderPicker({required this.code, required this.actions});

  final String code;
  final SetupActions actions;

  @override
  ConsumerState<_FolderPicker> createState() => _FolderPickerState();
}

class _FolderPickerState extends ConsumerState<_FolderPicker> {
  String? _selected;
  bool _linking = false;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final folders = ref.watch(materialsFoldersProvider);
    return switch (folders) {
      AsyncData(value: final list) when list.isEmpty => Text(
        'No folders found under the materials root.',
        style: LeaType.small().copyWith(color: c.muted),
      ),
      AsyncData(value: final list) => Builder(
        builder: (context) {
          _selected ??= list.firstWhere((f) => f.name == widget.code, orElse: () => list.first).name;
          return Wrap(
            crossAxisAlignment: WrapCrossAlignment.center,
            spacing: 10,
            runSpacing: 8,
            children: [
              DropdownButton<String>(
                value: _selected,
                items: [for (final f in list) DropdownMenuItem(value: f.name, child: Text(f.name))],
                onChanged: (v) => setState(() => _selected = v),
              ),
              FilledButton(
                onPressed: _linking || _selected == null ? null : _link,
                child: Text(_linking ? 'Linking…' : 'Link'),
              ),
            ],
          );
        },
      ),
      AsyncError(:final error) => TeachError(error: error, onRetry: () => ref.invalidate(materialsFoldersProvider)),
      _ => const SkeletonBox(height: 40),
    };
  }

  Future<void> _link() async {
    setState(() => _linking = true);
    try {
      await widget.actions.linkMaterialsSource(_selected!);
    } on ApiError catch (e) {
      if (mounted) _showError(context, e);
    } finally {
      if (mounted) setState(() => _linking = false);
    }
  }
}

class _SyncPreviewView extends ConsumerWidget {
  const _SyncPreviewView({required this.code, required this.path});

  final String code;
  final String path;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.lea;
    final preview = ref.watch(syncPreviewProvider(code));
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(path, style: LeaType.mono(13).copyWith(color: c.ink)),
          const SizedBox(height: 10),
          switch (preview) {
            AsyncData(value: final p) when p.entries.isEmpty => Text(
              'Nothing in this folder yet.',
              style: LeaType.small().copyWith(color: c.muted),
            ),
            AsyncData(value: final p) => Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Wrap(
                  spacing: 8,
                  runSpacing: 6,
                  children: [
                    if (p.newCount > 0) TeachPill('${p.newCount} new', tone: PillTone.ok),
                    if (p.changed > 0) TeachPill('${p.changed} changed', tone: PillTone.warn),
                    if (p.unchanged > 0) TeachPill('${p.unchanged} unchanged', tone: PillTone.neutral),
                    if (p.removed > 0) TeachPill('${p.removed} removed', tone: PillTone.bad),
                    if (p.rejected > 0) TeachPill('${p.rejected} rejected', tone: PillTone.dashed),
                  ],
                ),
                const SizedBox(height: 10),
                for (final e in p.entries)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 3),
                    child: Row(
                      children: [
                        Expanded(
                          child: Text(
                            e.relpath,
                            style: LeaType.ui(13).copyWith(color: c.ink),
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                        if (e.reason != null) ...[
                          Flexible(
                            child: Text(
                              e.reason!,
                              style: LeaType.ui(12).copyWith(color: c.muted),
                              overflow: TextOverflow.ellipsis,
                              textAlign: TextAlign.right,
                            ),
                          ),
                          const SizedBox(width: 8),
                        ],
                        TeachPill(
                          e.status,
                          tone: switch (e.status) {
                            'new' => PillTone.ok,
                            'changed' => PillTone.warn,
                            'removed' => PillTone.bad,
                            'rejected' => PillTone.dashed,
                            _ => PillTone.neutral,
                          },
                        ),
                      ],
                    ),
                  ),
              ],
            ),
            AsyncError(:final error) => TeachError(
              error: error,
              onRetry: () => ref.invalidate(syncPreviewProvider(code)),
            ),
            _ => const SkeletonBox(height: 40),
          },
        ],
      ),
    );
  }
}

class _UploadOptionsDialog extends StatefulWidget {
  const _UploadOptionsDialog({required this.files, required this.weeks});

  final List<PickedFile> files;
  final int weeks;

  @override
  State<_UploadOptionsDialog> createState() => _UploadOptionsDialogState();
}

class _UploadOptionsDialogState extends State<_UploadOptionsDialog> {
  int? _week;
  String? _kind;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final n = widget.files.length;
    return AlertDialog(
      title: Text('Upload $n ${n == 1 ? 'file' : 'files'}'),
      content: SizedBox(
        width: 420,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(widget.files.map((f) => f.name).join(', '), style: LeaType.small().copyWith(color: c.muted)),
            const SizedBox(height: 14),
            DropdownButtonFormField<int?>(
              initialValue: _week,
              decoration: const InputDecoration(labelText: 'Week', border: OutlineInputBorder()),
              items: [
                const DropdownMenuItem(value: null, child: Text('No week yet')),
                for (var w = 1; w <= widget.weeks; w++) DropdownMenuItem(value: w, child: Text('Week $w')),
              ],
              onChanged: (v) => setState(() => _week = v),
            ),
            const SizedBox(height: 12),
            DropdownButtonFormField<String?>(
              initialValue: _kind,
              decoration: const InputDecoration(labelText: 'Kind', border: OutlineInputBorder()),
              items: [
                const DropdownMenuItem(value: null, child: Text('From the file type')),
                for (final k in uploadKinds) DropdownMenuItem(value: k, child: Text(k)),
              ],
              onChanged: (v) => setState(() => _kind = v),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.of(context).pop(), child: const Text('Cancel')),
        FilledButton(
          onPressed: () => Navigator.of(context).pop((week: _week, kind: _kind)),
          child: const Text('Upload'),
        ),
      ],
    );
  }
}

// ---------------------------------------------------------------------------- weekly objectives

class _PlanCard extends ConsumerWidget {
  const _PlanCard({required this.code, required this.weeks, required this.editable});

  final String code;
  final int weeks;
  final bool editable;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.lea;
    final plan = ref.watch(planProvider(code));
    return TeachCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text('Weekly learning objectives', style: LeaType.heading(17).copyWith(color: c.ink)),
              ),
              if (editable && plan.hasValue)
                TextButton(
                  onPressed: () => showDialog<void>(
                    context: context,
                    builder: (_) => PlanEditor(code: code, weeks: weeks, initial: plan.value ?? const []),
                  ),
                  child: Text(plan.value == null ? 'Add' : 'Edit'),
                ),
            ],
          ),
          Text(
            'The objectives the KC model is drafted from. Full sentences, like "Explain how…".',
            style: LeaType.ui(12.5).copyWith(color: c.muted),
          ),
          const SizedBox(height: 8),
          switch (plan) {
            AsyncData(value: null) => Text('None yet.', style: LeaType.small().copyWith(color: c.muted)),
            AsyncData(value: final list?) => Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                for (final w in list)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 4),
                    child: Text.rich(
                      TextSpan(
                        children: [
                          TextSpan(
                            text: 'Week ${w.week} · ${w.title}',
                            style: LeaType.ui(13, weight: FontWeight.w600),
                          ),
                          TextSpan(
                            text: ' — ${w.objectives.length} ${w.objectives.length == 1 ? 'objective' : 'objectives'}',
                          ),
                        ],
                      ),
                      style: LeaType.ui(13).copyWith(color: c.ink),
                    ),
                  ),
              ],
            ),
            AsyncError(:final error) => TeachError(error: error, onRetry: () => ref.invalidate(planProvider(code))),
            _ => const SkeletonBox(height: 40),
          },
        ],
      ),
    );
  }
}

/// Every week's title and objectives (one per line).
class PlanEditor extends ConsumerStatefulWidget {
  const PlanEditor({super.key, required this.code, required this.weeks, required this.initial});

  final String code;
  final int weeks;
  final List<WeekPlan> initial;

  @override
  ConsumerState<PlanEditor> createState() => _PlanEditorState();
}

class _PlanEditorState extends ConsumerState<PlanEditor> {
  late final _titles = [
    for (var w = 1; w <= widget.weeks; w++)
      TextEditingController(text: widget.initial.where((p) => p.week == w).firstOrNull?.title ?? ''),
  ];
  late final _objectives = [
    for (var w = 1; w <= widget.weeks; w++)
      TextEditingController(text: widget.initial.where((p) => p.week == w).firstOrNull?.objectives.join('\n') ?? ''),
  ];
  String? _error;
  bool _busy = false;

  @override
  void dispose() {
    for (final c in [..._titles, ..._objectives]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _save() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await SetupActions(ref, widget.code).savePlan([
        for (var i = 0; i < widget.weeks; i++)
          WeekPlan(
            week: i + 1,
            title: _titles[i].text.trim(),
            objectives: [
              for (final l in _objectives[i].text.split('\n'))
                if (l.trim().isNotEmpty) l.trim(),
            ],
          ),
      ]);
      if (mounted) Navigator.of(context).pop();
    } on ApiError catch (e) {
      if (mounted) {
        setState(() {
          _busy = false;
          _error = e.message;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    return AlertDialog(
      title: const Text('Weekly learning objectives'),
      content: SizedBox(
        width: 620,
        child: SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text('One objective per line, as a full sentence.', style: LeaType.small().copyWith(color: c.muted)),
              for (var i = 0; i < widget.weeks; i++) ...[
                const SizedBox(height: 16),
                TextField(
                  key: Key('week-${i + 1}-title'),
                  controller: _titles[i],
                  decoration: InputDecoration(labelText: 'Week ${i + 1} title', border: const OutlineInputBorder()),
                ),
                const SizedBox(height: 8),
                TextField(
                  key: Key('week-${i + 1}-objectives'),
                  controller: _objectives[i],
                  minLines: 2,
                  maxLines: 8,
                  decoration: const InputDecoration(labelText: 'Learning objectives', border: OutlineInputBorder()),
                ),
              ],
              if (_error != null) ...[
                const SizedBox(height: 12),
                Text(_error!, style: LeaType.small().copyWith(color: c.danger)),
              ],
            ],
          ),
        ),
      ),
      actions: [
        TextButton(onPressed: _busy ? null : () => Navigator.of(context).pop(), child: const Text('Cancel')),
        FilledButton(onPressed: _busy ? null : _save, child: const Text('Save objectives')),
      ],
    );
  }
}

// ---------------------------------------------------------------------------- build

class _BuildCard extends ConsumerWidget {
  const _BuildCard({required this.code, required this.editable});

  final String code;
  final bool editable;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.lea;
    final latest = ref.watch(latestJobProvider(code));
    final id = latest.value?.id;
    final job = id == null ? null : (ref.watch(jobProvider(id)).value ?? latest.value);
    final actions = SetupActions(ref, code);
    final uploads = ref.watch(uploadsProvider(code)).value ?? const [];
    final plan = ref.watch(planProvider(code)).value;

    Future<void> run(Future<void> Function() f) async {
      try {
        await f();
      } on ApiError catch (e) {
        if (context.mounted) _showError(context, e);
      }
    }

    final (String status, PillTone tone) = switch (job?.status) {
      'awaiting_confirmation' => ('Waiting for you', PillTone.warn),
      'queued' => ('Queued', PillTone.warn),
      'running' => ('Running', PillTone.warn),
      'succeeded' => ('Done', PillTone.ok),
      'failed' => ('Failed', PillTone.bad),
      'cancelled' => ('Cancelled', PillTone.outline),
      _ => ('Not built yet', PillTone.outline),
    };
    return TeachCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Expanded(
                child: Text('Build', style: LeaType.heading(17).copyWith(color: c.ink)),
              ),
              TeachPill(status, tone: tone),
            ],
          ),
          const SizedBox(height: 10),
          if (latest.isLoading && job == null)
            const SkeletonBox(height: 60)
          else if (job != null && job.awaitingConfirmation)
            ..._estimate(
              context,
              job,
              editable,
              () => run(() => actions.confirm(job.id)),
              () => run(() => actions.cancel(job.id)),
            )
          else if (job != null && job.active)
            ..._progress(context, job, editable, () => run(() => actions.cancel(job.id)))
          else ...[
            if (job?.status == 'succeeded') ...[
              TeachBanner(tone: BannerTone.ok, child: Text(_doneText(job!))),
              const SizedBox(height: 10),
              FilledButton(
                onPressed: () => context.go('${TeachSection.objectives.path(code)}?from=job:${job.id}'),
                child: const Text('Review the objectives'),
              ),
              const SizedBox(height: 10),
            ],
            if (job?.status == 'failed') ...[
              TeachBanner(tone: BannerTone.bad, child: Text(job!.error ?? 'The build failed.')),
              const SizedBox(height: 10),
            ],
            Text(
              uploads.isEmpty
                  ? 'Upload some materials first.'
                  : plan == null
                  ? 'Add the weekly learning objectives first: the KC model is drafted from them.'
                  : 'LEA converts and indexes the materials, drafts the objectives, then checks the content for each. '
                        'It shows the price first.',
              style: LeaType.ui(12.5).copyWith(color: c.muted),
            ),
            if (editable) ...[
              const SizedBox(height: 10),
              FilledButton(
                onPressed: uploads.isEmpty || plan == null ? null : () => run(actions.prepareBuild),
                child: Text(job == null ? 'Price a build' : 'Build again'),
              ),
            ],
          ],
        ],
      ),
    );
  }

  String _doneText(Job job) {
    final verify = job.result['verify'] as Map<String, dynamic>?;
    final weak = (verify?['weak_support'] as List?)?.length;
    return 'Draft ready: ${verify?['objectives'] ?? ''} objectives drafted'
        '${weak == null ? '' : ', $weak with weak support in the content'}. Students still see the published version.';
  }

  List<Widget> _estimate(BuildContext context, Job job, bool editable, VoidCallback start, VoidCallback notNow) {
    final c = context.lea;
    final e = job.estimate;
    final labels = {for (final (k, v) in jobSteps) k: v};
    return [
      Text('LEA shows the price per step and waits:', style: LeaType.ui(12.5).copyWith(color: c.muted)),
      const SizedBox(height: 6),
      for (final s in job.steps)
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 3),
          child: Row(
            children: [
              Expanded(
                child: Text(labels[s] ?? s, style: LeaType.ui(12.5).copyWith(color: c.ink)),
              ),
              Text(dollars(e.perStep[s] ?? 0), style: LeaType.ui(12.5).copyWith(color: c.ink)),
            ],
          ),
        ),
      Divider(color: c.line),
      Row(
        children: [
          Expanded(
            child: Text(
              'Total',
              style: LeaType.ui(13, weight: FontWeight.w600).copyWith(color: c.ink),
            ),
          ),
          Text(
            dollars(e.usd),
            style: LeaType.ui(13, weight: FontWeight.w600).copyWith(color: c.ink),
          ),
        ],
      ),
      for (final n in e.notes) ...[const SizedBox(height: 6), Text(n, style: LeaType.ui(12).copyWith(color: c.muted))],
      if (editable) ...[
        const SizedBox(height: 12),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            FilledButton(onPressed: start, child: Text('Start build · ${dollars(e.usd)}')),
            GhostButton(label: 'Not now', onPressed: notNow),
          ],
        ),
      ],
    ];
  }

  List<Widget> _progress(BuildContext context, Job job, bool editable, VoidCallback cancel) {
    final c = context.lea;
    final current = job.steps.indexOf(job.step ?? '');
    return [
      Row(
        children: [
          Expanded(
            child: Text(
              job.status == 'queued' ? 'Waiting to start' : job.stepLabel,
              style: LeaType.ui(12.5).copyWith(color: c.ink),
            ),
          ),
          Text('${job.percent.round()}%', style: LeaType.ui(12.5).copyWith(color: c.ink)),
        ],
      ),
      const SizedBox(height: 6),
      Meter(value: job.percent / 100, semanticLabel: 'Build progress'),
      const SizedBox(height: 10),
      for (final (i, (key, label)) in jobSteps.indexed)
        if (job.steps.contains(key))
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 3),
            child: Row(
              children: [
                Icon(
                  i < current
                      ? Icons.check_circle
                      : (i == current ? Icons.radio_button_checked : Icons.radio_button_unchecked),
                  size: 18,
                  color: i < current ? c.primary : (i == current ? c.accent : c.line),
                ),
                const SizedBox(width: 9),
                Expanded(
                  child: Text(label, style: LeaType.ui(12.5).copyWith(color: c.ink)),
                ),
              ],
            ),
          ),
      if (job.log.isNotEmpty) ...[
        const SizedBox(height: 8),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
          decoration: BoxDecoration(
            color: c.bg,
            border: Border.all(color: c.line),
            borderRadius: BorderRadius.circular(8),
          ),
          child: Text(
            job.log.skip(job.log.length > 5 ? job.log.length - 5 : 0).join('\n'),
            style: LeaType.mono(11.5).copyWith(color: c.muted),
          ),
        ),
      ],
      const SizedBox(height: 8),
      Text(
        'Estimated cost ${dollars(job.estimate.usd)} · started by ${job.createdBy}',
        style: LeaType.ui(12).copyWith(color: c.muted),
      ),
      if (editable) ...[const SizedBox(height: 10), DangerButton(label: 'Cancel after this file', onPressed: cancel)],
    ];
  }
}
