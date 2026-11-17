import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/api_error.dart';
import '../api/models.dart';
import '../course/course_state.dart';
import '../theme/lea_colors.dart';
import '../theme/lea_type.dart';
import '../widgets/meter.dart';
import '../widgets/pressable.dart';
import '../widgets/skeleton.dart';
import 'shell_info.dart';

const _addCourseValue = '__add_course__';
const _leavePrefix = '__leave__:';

/// The course box: "COURSE" label, course name and a ▾ that opens the course picker (and,
/// at the bottom, "Add a course").
class CourseBox extends ConsumerWidget {
  const CourseBox({super.key, required this.info, required this.onSelect});

  final ShellInfo info;
  final ValueChanged<String> onSelect;

  Future<void> _pick(BuildContext context, WidgetRef ref) async {
    final box = context.findRenderObject()! as RenderBox;
    final overlay = Overlay.of(context).context.findRenderObject()! as RenderBox;
    final rect = RelativeRect.fromRect(
      Rect.fromPoints(
        box.localToGlobal(Offset(0, box.size.height + 4), ancestor: overlay),
        box.localToGlobal(box.size.bottomRight(Offset.zero), ancestor: overlay),
      ),
      Offset.zero & overlay.size,
    );
    final c = context.lea;
    final code = await showMenu<String>(
      context: context,
      position: rect,
      color: c.surface,
      surfaceTintColor: Colors.transparent,
      constraints: BoxConstraints(minWidth: box.size.width, maxWidth: box.size.width.clamp(228, 360)),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(10),
        side: BorderSide(color: c.line),
      ),
      items: [
        for (final course in info.courses)
          PopupMenuItem<String>(
            value: course.code,
            child: Builder(
              builder: (menuContext) => Row(
                children: [
                  SizedBox(
                    width: 20,
                    child: course.code == info.course.code ? Icon(Icons.check, size: 16, color: c.ink) : null,
                  ),
                  Expanded(child: Text(course.label, style: LeaType.small().copyWith(color: c.ink))),
                  IconButton(
                    icon: Icon(Icons.close, size: 16, color: c.muted),
                    visualDensity: VisualDensity.compact,
                    tooltip: 'Leave ${course.label}',
                    onPressed: () => Navigator.of(menuContext).pop('$_leavePrefix${course.code}'),
                  ),
                ],
              ),
            ),
          ),
        const PopupMenuDivider(),
        PopupMenuItem<String>(
          value: _addCourseValue,
          child: Text('Add a course…', style: LeaType.small().copyWith(color: c.ink)),
        ),
      ],
    );
    if (code == null) return;
    if (code == _addCourseValue) {
      if (context.mounted) await showDialog<void>(context: context, builder: (_) => const _AddCourseDialog());
    } else if (code.startsWith(_leavePrefix)) {
      final leaving = info.courses.firstWhere((c) => c.code == code.substring(_leavePrefix.length));
      if (context.mounted) {
        await showDialog<void>(context: context, builder: (_) => _LeaveCourseDialog(course: leaving));
      }
    } else if (code != info.course.code) {
      onSelect(code);
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.lea;
    return Builder(
      builder: (context) => Pressable(
        onTap: () => _pick(context, ref),
        semanticLabel: 'Course: ${info.course.label}. Change or add a course',
        excludeChildSemantics: true,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 9),
          decoration: BoxDecoration(
            color: c.bg,
            border: Border.all(color: c.line),
            borderRadius: BorderRadius.circular(10),
          ),
          child: Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('COURSE', style: LeaType.label(11).copyWith(color: c.muted)),
                    const SizedBox(height: 2),
                    Text(
                      info.course.label,
                      style: LeaType.ui(13.5, weight: FontWeight.w500, height: 1.55).copyWith(color: c.ink),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              // Drawn as an icon: the bundled fonts have no ▾, and web would fetch a fallback.
              Icon(Icons.arrow_drop_down, size: 20, color: c.ink),
            ],
          ),
        ),
      ),
    );
  }
}

/// The "WEEKS" label and list. The selected week sits on `surface-2` with its meter and
/// mastered count; weeks after the current one are locked and muted, and the next one
/// says when it opens.
class WeekList extends StatelessWidget {
  const WeekList({super.key, required this.info, required this.onSelect});

  final ShellInfo info;
  final ValueChanged<int> onSelect;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text('WEEKS', style: LeaType.label(11).copyWith(color: c.muted)),
        const SizedBox(height: 8),
        for (final (i, week) in info.weeks.indexed) ...[
          if (i > 0) const SizedBox(height: 4),
          _WeekItem(
            week: week,
            selected: week.number == info.selectedWeek,
            info: info,
            onTap: week.locked ? null : () => onSelect(week.number),
          ),
        ],
      ],
    );
  }
}

class _WeekItem extends StatelessWidget {
  const _WeekItem({required this.week, required this.selected, required this.info, required this.onTap});

  final WeekSummary week;
  final bool selected;
  final ShellInfo info;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final semantics = [
      week.label,
      if (selected) 'selected, ${info.masteredCount} of ${info.total} objectives mastered',
      if (week.locked) 'locked',
      if (week.lockNote != null) week.lockNote!,
    ].join(', ');

    final body = Container(
      padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 9),
      decoration: BoxDecoration(color: selected ? c.surface2 : null, borderRadius: BorderRadius.circular(10)),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Text(
                  week.label,
                  style: LeaType.ui(
                    13.5,
                    weight: selected ? FontWeight.w600 : FontWeight.w400,
                    height: 1.5,
                  ).copyWith(color: week.locked ? c.muted : c.ink),
                ),
              ),
              if (selected) ...[
                const SizedBox(width: 8),
                Padding(
                  padding: const EdgeInsets.only(top: 1),
                  child: Text(
                    info.count,
                    style: LeaType.ui(12).copyWith(color: c.muted, fontFeatures: LeaType.tabular),
                  ),
                ),
              ],
            ],
          ),
          if (selected) ...[const SizedBox(height: 6), Meter(value: info.fraction)],
          if (week.lockNote != null) ...[
            const SizedBox(height: 6),
            Text(week.lockNote!, style: LeaType.caption().copyWith(color: c.muted)),
          ],
        ],
      ),
    );

    if (onTap == null) {
      return Semantics(label: semantics, selected: selected, excludeSemantics: true, child: body);
    }
    return Pressable(
      onTap: onTap,
      selected: selected,
      semanticLabel: semantics,
      excludeChildSemantics: true,
      child: body,
    );
  }
}

/// "Add a course": picks from what's open for enrollment, excluding courses already taken.
class _AddCourseDialog extends ConsumerStatefulWidget {
  const _AddCourseDialog();

  @override
  ConsumerState<_AddCourseDialog> createState() => _AddCourseDialogState();
}

class _AddCourseDialogState extends ConsumerState<_AddCourseDialog> {
  String? _code;
  bool _busy = false;
  String? _error;

  Future<void> _add() async {
    final code = _code;
    if (code == null) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await addMyCourse(ref, code);
      if (mounted) Navigator.of(context).pop();
    } on ApiError catch (e) {
      if (mounted) setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final available = ref.watch(availableCoursesProvider);
    final mine = ref.watch(myCoursesProvider).value ?? const [];
    final mineCodes = {for (final m in mine) m.code};
    final options = [
      for (final course in available.value ?? const []) if (!mineCodes.contains(course.code)) course,
    ];
    return AlertDialog(
      title: const Text('Add a course'),
      content: SizedBox(
        width: 360,
        child: switch (available) {
          AsyncError(:final error) => Text(
            error is ApiError ? error.message : "Couldn't load the course list.",
            style: LeaType.small().copyWith(color: c.danger),
          ),
          AsyncData() when options.isEmpty => Text(
            "You're already enrolled in every open course.",
            style: LeaType.small().copyWith(color: c.muted),
          ),
          AsyncData() => Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              DropdownButtonFormField<String>(
                key: const Key('add-course-picker'),
                initialValue: _code,
                isExpanded: true,
                decoration: const InputDecoration(labelText: 'Course', border: OutlineInputBorder(), isDense: true),
                items: [for (final course in options) DropdownMenuItem(value: course.code, child: Text(course.label))],
                onChanged: (v) => setState(() => _code = v),
              ),
              if (_error != null) ...[
                const SizedBox(height: 8),
                Text(_error!, style: LeaType.small().copyWith(color: c.danger)),
              ],
            ],
          ),
          _ => const SkeletonBox(height: 40),
        },
      ),
      actions: [
        TextButton(onPressed: () => Navigator.of(context).pop(), child: const Text('Cancel')),
        FilledButton(onPressed: _busy || _code == null ? null : _add, child: const Text('Add')),
      ],
    );
  }
}

/// Stands in for the course box and week list while they load.
/// Confirms before leaving a course: your progress in it stays, so re-adding it later
/// resumes where you left off.
class _LeaveCourseDialog extends ConsumerStatefulWidget {
  const _LeaveCourseDialog({required this.course});

  final CourseInfo course;

  @override
  ConsumerState<_LeaveCourseDialog> createState() => _LeaveCourseDialogState();
}

class _LeaveCourseDialogState extends ConsumerState<_LeaveCourseDialog> {
  bool _busy = false;
  String? _error;

  Future<void> _leave() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await removeMyCourse(ref, widget.course.code);
      if (mounted) Navigator.of(context).pop();
    } on ApiError catch (e) {
      if (mounted) setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    return AlertDialog(
      title: Text('Leave ${widget.course.label}?'),
      content: SizedBox(
        width: 360,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('Your progress in this course is kept. Add it back later to pick up where you left off.'),
            if (_error != null) ...[
              const SizedBox(height: 8),
              Text(_error!, style: LeaType.small().copyWith(color: c.danger)),
            ],
          ],
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.of(context).pop(), child: const Text('Cancel')),
        FilledButton(
          style: FilledButton.styleFrom(backgroundColor: c.danger),
          onPressed: _busy ? null : _leave,
          child: const Text('Leave course'),
        ),
      ],
    );
  }
}

/// Stands in for the course box and week list while they load.
class CoursePanelSkeleton extends StatelessWidget {
  const CoursePanelSkeleton({super.key});

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: 'Loading your course',
      child: const Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          SkeletonBox(height: 58, radius: 10),
          SizedBox(height: 16),
          SkeletonBox(width: 48, height: 11),
          SizedBox(height: 10),
          SkeletonBox(height: 62, radius: 10),
          SizedBox(height: 8),
          SkeletonBox(height: 40, radius: 10),
          SizedBox(height: 8),
          SkeletonBox(height: 40, radius: 10),
        ],
      ),
    );
  }
}

/// Shown instead of the course panel when it couldn't load.
class CoursePanelError extends StatelessWidget {
  const CoursePanelError({super.key, required this.error, required this.onRetry});

  final Object error;
  final VoidCallback onRetry;

  static String messageFor(Object error) => switch (error) {
    ApiError e => e.message,
    NoCoursesError e => e.message,
    _ => "Couldn't load your course. Please try again.",
  };

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: c.surface,
        border: Border.all(color: c.line),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Semantics(
            liveRegion: true,
            child: Text(messageFor(error), style: LeaType.small().copyWith(color: c.ink)),
          ),
          if (error is! NoCoursesError) ...[
            const SizedBox(height: 8),
            Pressable(
              onTap: onRetry,
              borderRadius: 6,
              semanticLabel: 'Try again',
              excludeChildSemantics: true,
              child: Text(
                'Try again',
                style: LeaType.small().copyWith(
                  color: c.ink,
                  decoration: TextDecoration.underline,
                  decorationColor: c.muted,
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }
}
