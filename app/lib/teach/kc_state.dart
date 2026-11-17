import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/api_error.dart';
import '../providers.dart';
import 'teach_models.dart';
import 'teach_state.dart';

/// Published versions and whether there's a draft.
final kcOverviewProvider = FutureProvider.autoDispose.family<KCOverview, String>((ref, code) async {
  return KCOverview.fromJson(await ref.watch(apiClientProvider).getObject('/teach/courses/$code/kc'));
});

/// What publishing the draft would change, and who it affects.
final kcDiffProvider = FutureProvider.autoDispose.family<KCDiff, String>((ref, code) async {
  return KCDiff.fromJson(await ref.watch(apiClientProvider).getObject('/teach/courses/$code/kc/diff'));
});

/// The draft being edited: the server's copy plus unsaved edits.
class KCEditState {
  const KCEditState({
    this.loading = true,
    this.draft,
    this.rows = const [],
    this.dirty = false,
    this.issues = const [],
    this.selected,
    this.busy = false,
    this.error,
    this.loadError,
  });

  final bool loading;

  /// Null when the course has no draft.
  final KCDraft? draft;
  final List<KCRow> rows;
  final bool dirty;
  final List<KCIssue> issues;
  final int? selected;
  final bool busy;

  /// The last action's failure, shown above the table.
  final String? error;
  final ApiError? loadError;

  int get errors => issues.where((i) => i.error).length;
  int get warnings => issues.where((i) => !i.error).length;

  KCEditState copyWith({
    bool? loading,
    KCDraft? Function()? draft,
    List<KCRow>? rows,
    bool? dirty,
    List<KCIssue>? issues,
    int? Function()? selected,
    bool? busy,
    String? Function()? error,
    ApiError? Function()? loadError,
  }) => KCEditState(
    loading: loading ?? this.loading,
    draft: draft == null ? this.draft : draft(),
    rows: rows ?? this.rows,
    dirty: dirty ?? this.dirty,
    issues: issues ?? this.issues,
    selected: selected == null ? this.selected : selected(),
    busy: busy ?? this.busy,
    error: error == null ? this.error : error(),
    loadError: loadError == null ? this.loadError : loadError(),
  );
}

class KCEditor extends Notifier<KCEditState> {
  KCEditor(this.code);

  final String code;

  @override
  KCEditState build() {
    Future.microtask(load);
    return const KCEditState();
  }

  String get _base => '/teach/courses/$code/kc';

  void _show(KCDraft? draft) {
    state = KCEditState(
      loading: false,
      draft: draft,
      rows: draft?.rows ?? const [],
      issues: draft?.issues ?? const [],
      selected: state.selected != null && draft != null && state.selected! < draft.rows.length ? state.selected : null,
    );
  }

  Future<void> load() async {
    try {
      _show(KCDraft.fromJson(await ref.read(apiClientProvider).getObject('$_base/draft')));
    } on ApiError catch (e) {
      if (!ref.mounted) return;
      if (e.status == 404) {
        _show(null);
      } else {
        state = state.copyWith(loading: false, loadError: () => e);
      }
    }
  }

  Future<void> _act(Future<void> Function() action) async {
    state = state.copyWith(busy: true, error: () => null);
    try {
      await action();
    } on ApiError catch (e) {
      if (ref.mounted) state = state.copyWith(error: () => e.message);
    } finally {
      if (ref.mounted) state = state.copyWith(busy: false);
    }
  }

  /// Starts a draft from the live model (`published`) or a build (`job:<id>`).
  Future<void> start(String source, {bool replace = false}) => _act(() async {
    final json = await ref.read(apiClientProvider).postObject('$_base/draft', {'source': source, 'replace': replace});
    _show(KCDraft.fromJson(json));
    ref.invalidate(kcOverviewProvider(code));
  });

  Future<void> save() => _act(() async {
    final json = await ref.read(apiClientProvider).putObject('$_base/draft', {
      'rows': [for (final r in state.rows) r.toJson()],
    });
    _show(KCDraft.fromJson(json));
    ref.invalidate(kcDiffProvider(code));
  });

  Future<void> discard() => _act(() async {
    await ref.read(apiClientProvider).delete('$_base/draft');
    _show(null);
    ref.invalidate(kcOverviewProvider(code));
  });

  /// Checks the unsaved rows without saving them.
  Future<void> check() => _act(() async {
    final json = await ref.read(apiClientProvider).postObject('$_base/draft/validate', {
      'rows': [for (final r in state.rows) r.toJson()],
    });
    state = state.copyWith(
      issues: [for (final i in json['issues'] as List) KCIssue.fromJson(i as Map<String, dynamic>)],
    );
  });

  Future<List<int>?> export() async {
    try {
      return await ref.read(apiClientProvider).getBytes('$_base/draft/export');
    } on ApiError catch (e) {
      state = state.copyWith(error: () => e.message);
      return null;
    }
  }

  /// Reads an edited spreadsheet into the draft; nothing changes if it has problems.
  Future<bool> import(String name, List<int> bytes) async {
    var ok = false;
    await _act(() async {
      final json = await ref.read(apiClientProvider).postFiles('$_base/draft/import', [('file', name, bytes)]);
      _show(KCDraft.fromJson((json as Map<String, dynamic>)['draft'] as Map<String, dynamic>));
      ref.invalidate(kcDiffProvider(code));
      ok = true;
    });
    return ok;
  }

  Future<int?> publish(String note) async {
    int? version;
    await _act(() async {
      final json = await ref.read(apiClientProvider).postObject('$_base/publish', {'note': note});
      version = json['version'] as int;
      _show(null);
      ref.invalidate(kcOverviewProvider(code));
      ref.invalidate(teachCoursesProvider);
      ref.invalidate(teachCourseProvider(code));
    });
    return version;
  }

  // ------------------------------------------------------------------ local edits

  void select(int? index) => state = state.copyWith(selected: () => index);

  void _setRows(List<KCRow> rows, {int? Function()? selected}) =>
      state = state.copyWith(rows: rows, dirty: true, selected: selected);

  void update(int index, KCRow row) => _setRows([...state.rows]..[index] = row);

  void remove(int index) => _setRows([...state.rows]..removeAt(index), selected: () => null);

  /// A new objective in the same learning objective as [index] (LEA assigns its ID).
  void addAfter(int index) {
    final base = state.rows[index];
    final row = KCRow(
      week: base.week,
      weekTitle: base.weekTitle,
      loId: base.loId,
      loTitle: base.loTitle,
      loShortTitle: base.loShortTitle,
      skillName: 'New objective',
      cognitiveLevel: 'Understand',
      masteryThreshold: 0.75,
    );
    final rows = [...state.rows]..insert(index + 1, row);
    _setRows(rows, selected: () => index + 1);
  }

  /// Replaces [index] with two new parts that carry its mastery over when published.
  void split(int index) {
    final old = state.rows[index];
    if (old.goId == null) return;
    KCRow part(String n) =>
        old.copyWith(goId: () => null, skillName: '${old.skillName} ($n)', splitFrom: () => old.goId);
    final rows = [...state.rows]..replaceRange(index, index + 1, [part('part 1'), part('part 2')]);
    _setRows(rows, selected: () => index);
  }

  /// Replaces the rows at [indices] with one new objective (their average mastery).
  void merge(List<int> indices, String name) {
    final sources = [for (final i in indices) state.rows[i]];
    if (sources.length < 2 || sources.any((r) => r.goId == null)) return;
    final first = sources.first;
    final merged = first.copyWith(
      goId: () => null,
      skillName: name,
      mergedFrom: [for (final r in sources) r.goId!],
      splitFrom: () => null,
    );
    final keep = [
      for (final (i, r) in state.rows.indexed)
        if (!indices.contains(i)) r,
    ];
    final at = indices.reduce((a, b) => a < b ? a : b);
    _setRows([...keep]..insert(at.clamp(0, keep.length), merged), selected: () => at);
  }
}

final kcEditorProvider = NotifierProvider.autoDispose.family<KCEditor, KCEditState, String>(KCEditor.new);
