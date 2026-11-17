import 'package:flutter/material.dart';

import '../api/models.dart';
import '../theme/lea_colors.dart';
import '../theme/lea_type.dart';
import '../widgets/lea_avatar.dart';
import '../widgets/pressable.dart';
import 'course_panel.dart';
import 'shell_info.dart';

/// The 260 px left rail on wide screens (DESIGN.md, "Layout").
class Rail extends StatelessWidget {
  const Rail({
    super.key,
    required this.info,
    required this.error,
    required this.user,
    required this.progressActive,
    required this.onProgress,
    required this.onLogout,
    required this.onSelectCourse,
    required this.onSelectWeek,
    required this.onRetry,
    this.onTeaching,
  });

  static const width = 260.0;

  /// Null while loading (or after an error with nothing loaded before).
  final ShellInfo? info;
  final Object? error;
  final UserProfile? user;
  final bool progressActive;
  final VoidCallback onProgress;
  final VoidCallback onLogout;
  final ValueChanged<String> onSelectCourse;
  final ValueChanged<int> onSelectWeek;
  final VoidCallback onRetry;

  /// Teachers and admins get a "Teaching" link to the Teacher area (null: hidden).
  final VoidCallback? onTeaching;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    return Container(
      width: width,
      decoration: BoxDecoration(
        color: c.surface,
        border: Border(right: BorderSide(color: c.line)),
      ),
      child: LayoutBuilder(
        builder: (context, constraints) => SingleChildScrollView(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 18),
          child: ConstrainedBox(
            constraints: BoxConstraints(minHeight: constraints.maxHeight - 36),
            child: IntrinsicHeight(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const _Brand(),
                  const SizedBox(height: 16),
                  ...switch ((info, error)) {
                    (final ShellInfo info, _) => [
                      CourseBox(info: info, onSelect: onSelectCourse),
                      const SizedBox(height: 16),
                      WeekList(info: info, onSelect: onSelectWeek),
                    ],
                    (null, final Object error) => [CoursePanelError(error: error, onRetry: onRetry)],
                    (null, null) => [const CoursePanelSkeleton()],
                  },
                  const SizedBox(height: 16),
                  _ProgressLink(active: progressActive, onTap: onProgress),
                  if (onTeaching != null) ...[
                    const SizedBox(height: 8),
                    _ProgressLink(active: false, onTap: onTeaching!, label: 'Teaching'),
                  ],
                  const Spacer(),
                  const SizedBox(height: 16),
                  _UserRow(user: user, onLogout: onLogout),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _Brand extends StatelessWidget {
  const _Brand();

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    return Semantics(
      header: true,
      label: 'LEA. Slide In. Study Up. Show Off.',
      excludeSemantics: true,
      child: Row(
        children: [
          const LeaAvatar(size: 44),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('LEA', style: LeaType.wordmark().copyWith(color: c.ink)),
                const SizedBox(height: 3),
                Text(
                  'Slide In. Study Up. Show Off.',
                  style: LeaType.ui(11.5).copyWith(color: c.muted),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _ProgressLink extends StatelessWidget {
  const _ProgressLink({required this.active, required this.onTap, this.label = 'Your progress'});

  final bool active;
  final VoidCallback onTap;
  final String label;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final style = LeaType.ui(13.5, weight: active ? FontWeight.w600 : FontWeight.w400).copyWith(color: c.ink);
    return Pressable(
      onTap: onTap,
      selected: active,
      semanticLabel: label,
      excludeChildSemantics: true,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 9),
        decoration: BoxDecoration(
          color: active ? c.surface2 : null,
          border: Border.all(color: active ? Colors.transparent : c.line),
          borderRadius: BorderRadius.circular(10),
        ),
        child: Row(
          children: [
            Expanded(child: Text(label, style: style)),
            Icon(Icons.arrow_forward, size: 15, color: c.ink),
          ],
        ),
      ),
    );
  }
}

class _UserRow extends StatelessWidget {
  const _UserRow({required this.user, required this.onLogout});

  final UserProfile? user;
  final VoidCallback onLogout;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final name = user?.displayName ?? '';
    return Container(
      padding: const EdgeInsets.only(top: 12),
      decoration: BoxDecoration(
        border: Border(top: BorderSide(color: c.line)),
      ),
      child: Row(
        children: [
          InitialAvatar(initial: user?.initial ?? '?'),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  name,
                  style: LeaType.ui(13).copyWith(color: c.ink),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
                Pressable(
                  onTap: onLogout,
                  borderRadius: 4,
                  semanticLabel: 'Log out',
                  excludeChildSemantics: true,
                  child: Text('Log out', style: LeaType.ui(11.5).copyWith(color: c.muted)),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
