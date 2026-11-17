import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/api_error.dart';
import '../../api/models.dart';
import '../../connectivity.dart';
import '../../course/course_state.dart';
import '../../providers.dart';
import '../../shell/app_shell.dart';
import '../../theme/lea_colors.dart';
import '../../theme/lea_type.dart';
import '../../widgets/lea_text_field.dart';
import '../../widgets/offline_banner.dart';
import '../../widgets/skeleton.dart';
import '../../widgets/underline_tabs.dart';
import 'board_panel.dart';

/// Log in and create an account (DESIGN.md, "Login"; `login-*.png`).
///
/// Wide: the board panel beside the form. Narrow: the panel shrinks to a header above it.
class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key});

  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

enum _Tab { login, register }

class _LoginScreenState extends ConsumerState<LoginScreen> {
  _Tab _tab = _Tab.login;
  bool _busy = false;
  String? _error;
  String? _success;

  final _loginUsername = TextEditingController();
  final _loginPassword = TextEditingController();
  final _regUsername = TextEditingController();
  final _regFullName = TextEditingController();
  final _regPassword = TextEditingController();
  final _regConfirm = TextEditingController();
  String? _regCourse;

  @override
  void dispose() {
    for (final c in [_loginUsername, _loginPassword, _regUsername, _regFullName, _regPassword, _regConfirm]) {
      c.dispose();
    }
    super.dispose();
  }

  void _switchTab(_Tab tab) {
    if (tab == _tab) return;
    setState(() {
      _tab = tab;
      _error = null;
      _success = null;
    });
  }

  Future<void> _run(Future<void> Function() action) async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _error = null;
      _success = null;
    });
    try {
      await action();
    } on ApiError catch (e) {
      if (mounted) setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _login() async {
    if (_loginUsername.text.trim().isEmpty || _loginPassword.text.isEmpty) {
      setState(() => _error = 'Enter your username and password.');
      return;
    }
    await _run(() async {
      await ref.read(authProvider.notifier).login(_loginUsername.text, _loginPassword.text);
      TextInput.finishAutofillContext();
    });
  }

  /// Checks what the API's schema would reject, so the student hears it in plain words.
  String? _registerProblem() {
    final username = _regUsername.text.trim();
    if (username.length < 3 || username.length > 32) return 'Choose a username of 3 to 32 characters.';
    if (_regFullName.text.trim().isEmpty) return 'Enter your full name.';
    if (_regPassword.text.length < 6) return 'Choose a password of at least 6 characters.';
    if (_regPassword.text != _regConfirm.text) return "The passwords don't match.";
    if (_regCourse == null) return 'Choose your course.';
    return null;
  }

  Future<void> _register() async {
    final problem = _registerProblem();
    if (problem != null) {
      setState(() {
        _error = problem;
        _success = null;
      });
      return;
    }
    await _run(() async {
      final request = RegisterRequest(
        username: _regUsername.text.trim(),
        fullName: _regFullName.text.trim(),
        password: _regPassword.text,
        courses: [_regCourse!],
      );
      final response = await ref.read(apiClientProvider).postObject('/auth/register', request.toJson());
      if (!mounted) return;
      setState(() {
        _loginUsername.text = request.username;
        _loginPassword.clear();
        _regPassword.clear();
        _regConfirm.clear();
        _tab = _Tab.login;
        _success = (response['message'] as String?) ?? 'Account created. You can log in now.';
      });
    });
  }

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    return Scaffold(
      backgroundColor: c.bg,
      body: Column(
        children: [
          const SafeArea(bottom: false, child: OfflineBanner()),
          Expanded(
            child: LayoutBuilder(
              builder: (context, constraints) {
                final wide = constraints.maxWidth >= ShellMetrics.breakpoint;
                final board = BoardPanel(wide: wide, appWidth: constraints.maxWidth);
                if (wide) {
                  return Row(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Expanded(flex: 105, child: board),
                      Expanded(
                        flex: 100,
                        child: LayoutBuilder(
                          builder: (context, side) => SingleChildScrollView(
                            child: ConstrainedBox(
                              constraints: BoxConstraints(minHeight: side.maxHeight),
                              child: Center(
                                child: Padding(
                                  padding: const EdgeInsets.symmetric(horizontal: 44, vertical: 40),
                                  child: ConstrainedBox(
                                    constraints: const BoxConstraints(maxWidth: 520),
                                    child: _form(context, wide: true),
                                  ),
                                ),
                              ),
                            ),
                          ),
                        ),
                      ),
                    ],
                  );
                }
                return SafeArea(
                  bottom: false,
                  child: SingleChildScrollView(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        board,
                        Padding(padding: const EdgeInsets.fromLTRB(20, 22, 20, 28), child: _form(context, wide: false)),
                      ],
                    ),
                  ),
                );
              },
            ),
          ),
        ],
      ),
    );
  }

  Widget _form(BuildContext context, {required bool wide}) {
    final c = context.lea;
    final notice = ref.watch(authProvider).message;
    final error = _error ?? (_success == null && _tab == _Tab.login ? notice : null);
    final login = _tab == _Tab.login;

    return AutofillGroup(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Semantics(
            header: true,
            child: Text(
              login ? 'Welcome back' : 'Create your account',
              style: LeaType.heading(24, weight: const FontWeight(750)).copyWith(color: c.ink),
            ),
          ),
          const SizedBox(height: 18),
          UnderlineTabs(
            labels: const ['Log in', 'Create account'],
            selected: _tab.index,
            onSelect: (i) => _switchTab(_Tab.values[i]),
            tabPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          ),
          const SizedBox(height: 18),
          if (login) ..._loginFields() else ..._registerFields(),
          const SizedBox(height: 18),
          FilledButton(
            onPressed: _busy ? null : (login ? _login : _register),
            child: Text(switch ((login, _busy)) {
              (true, false) => 'Log in',
              (true, true) => 'Logging in…',
              (false, false) => 'Create account',
              (false, true) => 'Creating your account…',
            }),
          ),
          if (error != null || _success != null) ...[
            const SizedBox(height: 14),
            Semantics(
              liveRegion: true,
              child: Text(
                error ?? _success!,
                style: LeaType.small().copyWith(color: error != null ? c.danger : c.success),
              ),
            ),
          ],
          const SizedBox(height: 18),
          Text(
            'Forgot your password? Ask your course tutor to reset it.',
            style: LeaType.ui(12.5, height: 1.5).copyWith(color: c.muted),
          ),
        ],
      ),
    );
  }

  List<Widget> _loginFields() => [
    LeaTextField(
      key: const ValueKey('login-username'),
      label: 'Username',
      controller: _loginUsername,
      autofillHints: const [AutofillHints.username],
      textInputAction: TextInputAction.next,
    ),
    const SizedBox(height: 18),
    LeaTextField(
      key: const ValueKey('login-password'),
      label: 'Password',
      controller: _loginPassword,
      obscureText: true,
      autofillHints: const [AutofillHints.password],
      onSubmitted: (_) => _login(),
    ),
  ];

  List<Widget> _registerFields() => [
    LeaTextField(
      key: const ValueKey('register-username'),
      label: 'Username',
      controller: _regUsername,
      helper: '3 to 32 characters',
      autofillHints: const [AutofillHints.newUsername],
      textInputAction: TextInputAction.next,
    ),
    const SizedBox(height: 14),
    LeaTextField(
      key: const ValueKey('register-full-name'),
      label: 'Full name',
      controller: _regFullName,
      autofillHints: const [AutofillHints.name],
      textInputAction: TextInputAction.next,
    ),
    const SizedBox(height: 14),
    LeaTextField(
      key: const ValueKey('register-password'),
      label: 'Password',
      controller: _regPassword,
      obscureText: true,
      helper: 'At least 6 characters',
      autofillHints: const [AutofillHints.newPassword],
      textInputAction: TextInputAction.next,
    ),
    const SizedBox(height: 14),
    LeaTextField(
      key: const ValueKey('register-confirm'),
      label: 'Confirm password',
      controller: _regConfirm,
      obscureText: true,
      autofillHints: const [AutofillHints.newPassword],
      textInputAction: TextInputAction.next,
    ),
    const SizedBox(height: 14),
    _CoursePicker(
      value: _regCourse,
      onChanged: (code) => setState(() => _regCourse = code),
      onLoaded: (courses) {
        // With one course on offer there's nothing to choose; otherwise the open course
        // is suggested when it's offered.
        final suggested = courses.length == 1
            ? courses.single.code
            : courses.where((c) => c.code == defaultCourse).firstOrNull?.code;
        if (_regCourse == null && suggested != null) {
          WidgetsBinding.instance.addPostFrameCallback((_) {
            if (mounted && _regCourse == null) setState(() => _regCourse = suggested);
          });
        }
      },
    ),
  ];
}

/// The course picker on "Create account", from `GET /courses`.
/// The course suggested on "Create account" when several are offered: LEA's open course.
const defaultCourse = 'AIML101';

class _CoursePicker extends ConsumerWidget {
  const _CoursePicker({required this.value, required this.onChanged, required this.onLoaded});

  final String? value;
  final ValueChanged<String?> onChanged;
  final ValueChanged<List<CourseInfo>> onLoaded;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.lea;
    // Back online: fetch the list again rather than waiting for "Try again".
    ref.listen(connectivityProvider, (was, now) {
      if (was == false && now && ref.read(availableCoursesProvider).hasError) ref.invalidate(availableCoursesProvider);
    });
    final courses = ref.watch(availableCoursesProvider);
    final label = ExcludeSemantics(
      child: Text(
        'Course',
        style: LeaType.ui(13, weight: FontWeight.w500).copyWith(color: c.ink),
      ),
    );

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        label,
        const SizedBox(height: 6),
        switch (courses) {
          AsyncData(value: final list) => Builder(
            builder: (context) {
              onLoaded(list);
              return Semantics(
                label: 'Course',
                child: DropdownButtonFormField<String>(
                  key: const ValueKey('register-course'),
                  initialValue: value,
                  isExpanded: true,
                  hint: Text('Choose your course', style: LeaType.ui(14).copyWith(color: c.muted)),
                  dropdownColor: c.surface,
                  borderRadius: BorderRadius.circular(10),
                  style: LeaType.ui(14).copyWith(color: c.ink),
                  iconEnabledColor: c.ink,
                  decoration: const InputDecoration(
                    isDense: true,
                    contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 11),
                  ),
                  items: [
                    for (final course in list)
                      DropdownMenuItem(
                        value: course.code,
                        child: Text(course.label, overflow: TextOverflow.ellipsis),
                      ),
                  ],
                  onChanged: onChanged,
                ),
              );
            },
          ),
          AsyncError(error: final error) => Row(
            children: [
              Expanded(
                child: Text(
                  error is ApiError ? error.message : "Couldn't load the course list.",
                  style: LeaType.small().copyWith(color: c.danger),
                ),
              ),
              TextButton(
                onPressed: () => ref.invalidate(availableCoursesProvider),
                child: Text('Try again', style: LeaType.small().copyWith(color: c.ink)),
              ),
            ],
          ),
          _ => const SkeletonBox(height: 44, radius: 10),
        },
      ],
    );
  }
}
