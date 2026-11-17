import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/api_error.dart';
import '../../course/course_state.dart';
import '../../teach/audit_admin_state.dart';
import '../../teach/teach_models.dart';
import '../../teach/teach_state.dart';
import '../../teach/teach_widgets.dart';
import '../../theme/lea_colors.dart';
import '../../theme/lea_type.dart';
import '../../widgets/skeleton.dart';

/// Users and owners (`admin-*.png`, admins only): every account with its role and status,
/// course owners, and new teacher accounts.
class AdminScreen extends ConsumerStatefulWidget {
  const AdminScreen({super.key});

  @override
  ConsumerState<AdminScreen> createState() => _AdminScreenState();
}

class _AdminScreenState extends ConsumerState<AdminScreen> {
  String _filter = 'all';
  String _search = '';

  @override
  Widget build(BuildContext context) {
    final wide = MediaQuery.sizeOf(context).width >= 720;
    final users = ref.watch(adminUsersProvider);
    final list = users.value ?? const <AdminUser>[];
    final teachers = list.where((u) => u.role == 'teacher').length;
    final admins = list.where((u) => u.role == 'admin').length;
    final shown = [
      for (final u in list)
        if ((_filter == 'all' || (_filter == 'staff' && u.isStaff) || (_filter == 'test' && u.sessionKind == 'test')) &&
            (_search.isEmpty ||
                u.username.toLowerCase().contains(_search) ||
                u.fullName.toLowerCase().contains(_search)))
          u,
    ];
    final table = TeachCard(
      padding: EdgeInsets.zero,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(
            padding: const EdgeInsets.all(12),
            child: Wrap(
              spacing: 8,
              runSpacing: 8,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                SizedBox(
                  width: 240,
                  child: TextField(
                    key: const Key('user-search'),
                    decoration: const InputDecoration(
                      labelText: 'Search accounts',
                      isDense: true,
                      border: OutlineInputBorder(),
                    ),
                    onChanged: (v) => setState(() => _search = v.trim().toLowerCase()),
                  ),
                ),
                for (final (key, label) in [('all', 'All'), ('staff', 'Staff'), ('test', 'Test accounts')])
                  ChoiceChip(
                    label: Text(label),
                    selected: _filter == key,
                    onSelected: (_) => setState(() => _filter = key),
                  ),
              ],
            ),
          ),
          switch (users) {
            AsyncError(:final error) => Padding(
              padding: const EdgeInsets.all(12),
              child: TeachError(error: error, onRetry: () => ref.invalidate(adminUsersProvider)),
            ),
            AsyncData() => Column(
              children: [for (final u in shown) _UserRow(user: u, editable: wide)],
            ),
            _ => const Padding(padding: EdgeInsets.all(12), child: SkeletonBox(height: 120)),
          },
        ],
      ),
    );
    final side = Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _OwnersCard(editable: wide, users: list),
        if (wide) ...[const SizedBox(height: 12), const _NewTeacherCard()],
      ],
    );
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        TeachHeader(
          kicker: 'Admin',
          title: 'Users and owners',
          subtitle: users.hasValue
              ? '${list.length} accounts · $teachers ${teachers == 1 ? 'teacher' : 'teachers'} · '
                    '$admins ${admins == 1 ? 'admin' : 'admins'}'
              : null,
        ),
        Expanded(
          child: LayoutBuilder(
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
                children: [
                  if (!wide) ...[const DesktopOnlyNote(), const SizedBox(height: 12)],
                  table,
                  const SizedBox(height: 12),
                  side,
                ],
              );
            },
          ),
        ),
      ],
    );
  }
}

void _error(BuildContext context, ApiError e) =>
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));

class _UserRow extends ConsumerWidget {
  const _UserRow({required this.user, required this.editable});

  final AdminUser user;
  final bool editable;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.lea;
    final u = user;
    final (String role, PillTone tone) = switch (u.role) {
      'admin' => ('Admin', PillTone.ok),
      'teacher' => ('Teacher', PillTone.neutral),
      _ => ('Student', PillTone.outline),
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
      decoration: BoxDecoration(
        border: Border(top: BorderSide(color: c.line)),
      ),
      child: Row(
        children: [
          Expanded(
            flex: 3,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  u.displayName,
                  style: LeaType.ui(13, weight: FontWeight.w500).copyWith(color: c.ink),
                ),
                IdText(u.username),
              ],
            ),
          ),
          Expanded(
            flex: 2,
            child: Align(
              alignment: Alignment.centerLeft,
              child: TeachPill(role, tone: tone),
            ),
          ),
          Expanded(
            flex: 3,
            child: Text(
              u.ownedCourses.isEmpty ? '—' : u.ownedCourses.join(', '),
              style: LeaType.ui(12.5).copyWith(color: u.ownedCourses.isEmpty ? c.muted : c.ink),
            ),
          ),
          Expanded(
            flex: 2,
            child: Align(
              alignment: Alignment.centerLeft,
              child: !u.active
                  ? Text('Deactivated', style: LeaType.ui(12.5).copyWith(color: c.danger))
                  : u.sessionKind == 'test'
                  ? const TeachPill('Test', tone: PillTone.dashed)
                  : Text('Active', style: LeaType.ui(12.5).copyWith(color: c.ink)),
            ),
          ),
          if (editable)
            TextButton(
              onPressed: () => showDialog<void>(
                context: context,
                builder: (_) => _EditUserDialog(user: u),
              ),
              child: Text('Edit', semanticsLabel: 'Edit ${u.username}'),
            ),
        ],
      ),
    );
  }
}

class _EditUserDialog extends ConsumerStatefulWidget {
  const _EditUserDialog({required this.user});

  final AdminUser user;

  @override
  ConsumerState<_EditUserDialog> createState() => _EditUserDialogState();
}

class _EditUserDialogState extends ConsumerState<_EditUserDialog> {
  late String _role = widget.user.role;
  late bool _active = widget.user.active;
  late bool _test = widget.user.sessionKind == 'test';
  late List<String> _courses = List.of(widget.user.enrolledCourses);
  String? _addCourse;
  String? _error;

  Future<void> _addEnrollment() async {
    final code = _addCourse;
    if (code == null) return;
    try {
      await AdminActions(ref).addCourse(widget.user.username, code);
      if (mounted) {
        setState(() {
          _courses = List.of(_courses)..add(code)..sort();
          _addCourse = null;
        });
      }
    } on ApiError catch (e) {
      if (mounted) setState(() => _error = e.message);
    }
  }

  Future<void> _removeEnrollment(String code) async {
    try {
      await AdminActions(ref).removeCourse(widget.user.username, code);
      if (mounted) setState(() => _courses = _courses.where((c) => c != code).toList());
    } on ApiError catch (e) {
      if (mounted) setState(() => _error = e.message);
    }
  }

  Future<void> _save() async {
    final u = widget.user;
    try {
      await AdminActions(ref).update(
        u.username,
        role: _role == u.role ? null : _role,
        active: _active == u.active ? null : _active,
        sessionKind: _test == (u.sessionKind == 'test') ? null : (_test ? 'test' : 'real'),
      );
      if (mounted) Navigator.of(context).pop();
    } on ApiError catch (e) {
      if (mounted) setState(() => _error = e.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    return AlertDialog(
      title: Text('Edit ${widget.user.displayName}'),
      content: SizedBox(
        width: 400,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            DropdownButtonFormField<String>(
              initialValue: _role,
              decoration: const InputDecoration(labelText: 'Role', border: OutlineInputBorder()),
              items: const [
                DropdownMenuItem(value: 'student', child: Text('Student')),
                DropdownMenuItem(value: 'teacher', child: Text('Teacher')),
                DropdownMenuItem(value: 'admin', child: Text('Admin')),
              ],
              onChanged: (v) => setState(() => _role = v ?? _role),
            ),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('Active'),
              subtitle: const Text('Deactivating signs them out everywhere'),
              value: _active,
              onChanged: (v) => setState(() => _active = v),
            ),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('Test account'),
              subtitle: const Text('Its activity stays out of research data and analytics'),
              value: _test,
              onChanged: (v) => setState(() => _test = v),
            ),
            const SizedBox(height: 10),
            Text('Enrolled courses', style: LeaType.label(11).copyWith(color: c.muted)),
            const SizedBox(height: 6),
            if (_courses.isEmpty) Text('Not enrolled in any course.', style: LeaType.small().copyWith(color: c.muted)),
            Wrap(
              spacing: 6,
              runSpacing: 6,
              children: [
                for (final code in _courses)
                  InputChip(
                    key: Key('enrolled-$code'),
                    label: Text(code),
                    onDeleted: () => _removeEnrollment(code),
                  ),
              ],
            ),
            const SizedBox(height: 8),
            Consumer(
              builder: (context, ref, _) {
                final available = ref.watch(availableCoursesProvider);
                final options = [
                  for (final c in available.value ?? const []) if (!_courses.contains(c.code)) c.code,
                ];
                return Row(
                  children: [
                    Expanded(
                      child: DropdownButtonFormField<String>(
                        key: const Key('add-enrollment'),
                        initialValue: _addCourse,
                        isExpanded: true,
                        decoration: const InputDecoration(
                          labelText: 'Add a course',
                          border: OutlineInputBorder(),
                          isDense: true,
                        ),
                        items: [for (final code in options) DropdownMenuItem(value: code, child: Text(code))],
                        onChanged: (v) => setState(() => _addCourse = v),
                      ),
                    ),
                    const SizedBox(width: 8),
                    FilledButton(onPressed: _addCourse == null ? null : _addEnrollment, child: const Text('Add')),
                  ],
                );
              },
            ),
            const SizedBox(height: 10),
            if (_error != null) Text(_error!, style: LeaType.small().copyWith(color: c.danger)),
          ],
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.of(context).pop(), child: const Text('Cancel')),
        FilledButton(onPressed: _save, child: const Text('Save')),
      ],
    );
  }
}

class _OwnersCard extends ConsumerStatefulWidget {
  const _OwnersCard({required this.editable, required this.users});

  final bool editable;
  final List<AdminUser> users;

  @override
  ConsumerState<_OwnersCard> createState() => _OwnersCardState();
}

class _OwnersCardState extends ConsumerState<_OwnersCard> {
  String? _course;
  String? _add;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final courses = ref.watch(teachCoursesProvider).value ?? const <TeachCourse>[];
    final course = _course ?? (courses.isEmpty ? null : courses.first.code);
    final owners = course == null ? null : ref.watch(ownersProvider(course));
    final staff = [
      for (final u in widget.users)
        if (u.isStaff && !(owners?.value ?? const []).contains(u.username)) u,
    ];
    final roles = {for (final u in widget.users) u.username: u.role};
    Future<void> act(Future<void> Function() f) async {
      try {
        await f();
      } on ApiError catch (e) {
        if (context.mounted) _error(context, e);
      }
    }

    return TeachCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text('Course owners', style: LeaType.heading(16).copyWith(color: c.ink)),
          const SizedBox(height: 10),
          DropdownButtonFormField<String>(
            key: const Key('owners-course'),
            initialValue: course,
            isExpanded: true,
            decoration: const InputDecoration(labelText: 'Course', border: OutlineInputBorder(), isDense: true),
            items: [
              for (final x in courses)
                DropdownMenuItem(
                  value: x.code,
                  child: Text(x.label, overflow: TextOverflow.ellipsis),
                ),
            ],
            onChanged: (v) => setState(() {
              _course = v;
              _add = null;
            }),
          ),
          const SizedBox(height: 8),
          for (final o in owners?.value ?? const <String>[])
            Row(
              children: [
                Expanded(
                  child: Text(roles[o] == 'admin' ? '$o (admin)' : o, style: LeaType.ui(13).copyWith(color: c.ink)),
                ),
                if (widget.editable)
                  TextButton(
                    onPressed: () => act(() => AdminActions(ref).removeOwner(course!, o)),
                    child: Text(
                      'Remove',
                      semanticsLabel: 'Remove $o',
                      style: TextStyle(color: c.danger),
                    ),
                  ),
              ],
            ),
          if ((owners?.value ?? const []).isEmpty && owners?.hasValue == true)
            Text('No owners yet.', style: LeaType.small().copyWith(color: c.muted)),
          if (widget.editable && course != null) ...[
            const SizedBox(height: 8),
            Row(
              children: [
                Expanded(
                  child: DropdownButtonFormField<String>(
                    key: const Key('owners-add'),
                    initialValue: _add,
                    isExpanded: true,
                    decoration: const InputDecoration(
                      labelText: 'Add a teacher',
                      border: OutlineInputBorder(),
                      isDense: true,
                    ),
                    items: [for (final u in staff) DropdownMenuItem(value: u.username, child: Text(u.displayName))],
                    onChanged: (v) => setState(() => _add = v),
                  ),
                ),
                const SizedBox(width: 8),
                FilledButton(
                  onPressed: _add == null
                      ? null
                      : () => act(() async {
                          await AdminActions(ref).addOwner(course, _add!);
                          if (mounted) setState(() => _add = null);
                        }),
                  child: const Text('Add'),
                ),
              ],
            ),
          ],
          const SizedBox(height: 6),
          Text('Only teachers and admins can own courses.', style: LeaType.ui(12).copyWith(color: c.muted)),
        ],
      ),
    );
  }
}

class _NewTeacherCard extends ConsumerStatefulWidget {
  const _NewTeacherCard();

  @override
  ConsumerState<_NewTeacherCard> createState() => _NewTeacherCardState();
}

class _NewTeacherCardState extends ConsumerState<_NewTeacherCard> {
  final _name = TextEditingController();
  final _username = TextEditingController();
  final _password = TextEditingController();
  String _role = 'teacher';
  String? _error;
  String? _done;

  @override
  void dispose() {
    _name.dispose();
    _username.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _create() async {
    setState(() {
      _error = null;
      _done = null;
    });
    if (_password.text.length < 8) {
      setState(() => _error = 'Temporary passwords must be at least 8 characters.');
      return;
    }
    try {
      await AdminActions(ref).createStaff(
        username: _username.text.trim(),
        fullName: _name.text.trim(),
        password: _password.text,
        role: _role,
      );
      setState(() {
        _done = 'Created ${_username.text.trim()}. Give them the temporary password in person.';
        _name.clear();
        _username.clear();
        _password.clear();
      });
    } on ApiError catch (e) {
      setState(() => _error = e.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    InputDecoration deco(String label) =>
        InputDecoration(labelText: label, border: const OutlineInputBorder(), isDense: true);
    return TeachCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text('New teacher account', style: LeaType.heading(16).copyWith(color: c.ink)),
          const SizedBox(height: 10),
          TextField(key: const Key('new-name'), controller: _name, decoration: deco('Name')),
          const SizedBox(height: 8),
          TextField(key: const Key('new-username'), controller: _username, decoration: deco('Username')),
          const SizedBox(height: 8),
          TextField(
            key: const Key('new-password'),
            controller: _password,
            obscureText: true,
            decoration: deco('Temporary password'),
          ),
          const SizedBox(height: 8),
          DropdownButtonFormField<String>(
            initialValue: _role,
            decoration: deco('Role'),
            items: const [
              DropdownMenuItem(value: 'teacher', child: Text('Teacher')),
              DropdownMenuItem(value: 'admin', child: Text('Admin')),
            ],
            onChanged: (v) => setState(() => _role = v ?? _role),
          ),
          if (_error != null) ...[
            const SizedBox(height: 8),
            Text(_error!, style: LeaType.small().copyWith(color: c.danger)),
          ],
          if (_done != null) ...[const SizedBox(height: 8), TeachBanner(tone: BannerTone.ok, child: Text(_done!))],
          const SizedBox(height: 10),
          Align(
            alignment: Alignment.centerLeft,
            child: FilledButton(onPressed: _create, child: const Text('Create account')),
          ),
        ],
      ),
    );
  }
}
