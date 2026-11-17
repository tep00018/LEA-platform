import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../api/api_error.dart';
import '../api/models.dart';
import '../course/course_state.dart';
import '../providers.dart';
import '../shell/mode.dart';
import '../theme/lea_colors.dart';
import '../theme/lea_type.dart';
import '../widgets/lea_avatar.dart';
import '../widgets/offline_banner.dart';
import '../widgets/pressable.dart';
import 'preview_state.dart';
import 'teach_models.dart';
import 'teach_state.dart';
import 'video_state.dart';

/// The Teacher area's frame: the teaching rail on wide screens, a top bar with a course
/// picker on narrow ones (where the area is read-only).
class TeachShell extends ConsumerWidget {
  const TeachShell({super.key, required this.location, required this.child});

  final String location;
  final Widget child;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.lea;
    final (section, course) = TeachSection.fromLocation(location);
    final user = ref.watch(authProvider).user;
    final courses = ref.watch(teachCoursesProvider).value ?? const <TeachCourse>[];
    return Scaffold(
      backgroundColor: c.bg,
      body: LayoutBuilder(
        builder: (context, constraints) {
          final wide = constraints.maxWidth >= 720;
          if (wide) {
            return Row(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                TeachRail(section: section, course: course, courses: courses, user: user),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      const OfflineBanner(),
                      Expanded(child: child),
                    ],
                  ),
                ),
              ],
            );
          }
          return SafeArea(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                _TeachTopBar(section: section, course: course, courses: courses),
                const OfflineBanner(),
                Expanded(child: child),
              ],
            ),
          );
        },
      ),
    );
  }
}

/// Starts "Try as a student" for [course] and opens the student screens.
Future<void> tryAsStudent(BuildContext context, WidgetRef ref, String course) async {
  try {
    await ref.read(previewProvider.notifier).start(course);
    ref.read(selectionProvider.notifier).selectCourse(course);
    if (context.mounted) context.go(Mode.tutor.path);
  } on ApiError catch (e) {
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    }
  }
}

class TeachRail extends ConsumerWidget {
  const TeachRail({super.key, required this.section, required this.course, required this.courses, required this.user});

  final TeachSection section;
  final String? course;
  final List<TeachCourse> courses;
  final UserProfile? user;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.lea;
    final selected = courses.where((x) => x.code == course).firstOrNull;
    final selectedCode = course; // a local, so a null check promotes it
    final live = selected?.hasKcModel ?? false;
    Widget item(TeachSection s, IconData icon, {String? badge}) => _NavItem(
      label: s.label,
      icon: icon,
      active: section == s,
      badge: badge,
      onTap: !s.perCourse || course != null ? () => context.go(s.path(course)) : null,
    );
    return Container(
      width: 260,
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
                  Semantics(
                    header: true,
                    label: 'LEA teaching',
                    excludeSemantics: true,
                    child: Row(
                      children: [
                        const LeaAvatar(size: 44),
                        const SizedBox(width: 10),
                        Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text('LEA', style: LeaType.wordmark().copyWith(color: c.ink)),
                            const SizedBox(height: 3),
                            Text('Teaching', style: LeaType.ui(11.5).copyWith(color: c.muted)),
                          ],
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 16),
                  CoursePicker(section: section, course: course, courses: courses),
                  const SizedBox(height: 14),
                  item(TeachSection.courses, Icons.home_outlined),
                  item(TeachSection.setup, Icons.checklist_rtl),
                  item(TeachSection.objectives, Icons.hub_outlined),
                  item(
                    TeachSection.videos,
                    Icons.smart_display_outlined,
                    badge:
                        (selectedCode == null ? null : ref.watch(videosProvider(selectedCode)).value?.curatedObjectives)
                            ?.toString(),
                  ),
                  item(TeachSection.audit, Icons.fact_check_outlined),
                  item(TeachSection.analytics, Icons.bar_chart),
                  _NavItem(
                    label: 'Try as a student',
                    icon: Icons.visibility_outlined,
                    active: false,
                    onTap: course != null && live ? () => tryAsStudent(context, ref, course!) : null,
                  ),
                  if (user?.role == 'admin') ...[
                    const SizedBox(height: 12),
                    Text('ADMIN', style: LeaType.label(11).copyWith(color: c.muted)),
                    const SizedBox(height: 4),
                    item(TeachSection.admin, Icons.manage_accounts_outlined),
                  ],
                  const Spacer(),
                  const SizedBox(height: 16),
                  Pressable(
                    onTap: () => context.go(Mode.chat.path),
                    semanticLabel: 'Back to learning',
                    excludeChildSemantics: true,
                    child: Container(
                      padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 9),
                      decoration: BoxDecoration(
                        border: Border.all(color: c.line),
                        borderRadius: BorderRadius.circular(10),
                      ),
                      child: Row(
                        children: [
                          Expanded(
                            child: Text('Back to learning', style: LeaType.ui(13.5).copyWith(color: c.ink)),
                          ),
                          Icon(Icons.arrow_forward, size: 15, color: c.ink),
                        ],
                      ),
                    ),
                  ),
                  const SizedBox(height: 16),
                  Container(
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
                              Text(user?.displayName ?? '', style: LeaType.ui(13).copyWith(color: c.ink)),
                              Pressable(
                                onTap: () => ref.read(authProvider.notifier).logout(),
                                borderRadius: 4,
                                semanticLabel: 'Log out',
                                excludeChildSemantics: true,
                                child: Text(
                                  '${user?.role == 'admin' ? 'Admin' : 'Teacher'} · Log out',
                                  style: LeaType.ui(11.5).copyWith(color: c.muted),
                                ),
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _NavItem extends StatelessWidget {
  const _NavItem({required this.label, required this.icon, required this.active, required this.onTap, this.badge});

  final String label;
  final IconData icon;
  final bool active;
  final VoidCallback? onTap;
  final String? badge;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final color = onTap == null ? c.muted : c.ink;
    return Pressable(
      onTap: onTap,
      selected: active,
      semanticLabel: label,
      excludeChildSemantics: true,
      child: Container(
        margin: const EdgeInsets.only(bottom: 2),
        padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 8),
        decoration: BoxDecoration(color: active ? c.surface2 : null, borderRadius: BorderRadius.circular(10)),
        child: Row(
          children: [
            Icon(icon, size: 18, color: active ? c.ink : c.muted),
            const SizedBox(width: 10),
            Expanded(
              child: Text(
                label,
                style: LeaType.ui(13.5, weight: active ? FontWeight.w600 : FontWeight.w400).copyWith(color: color),
              ),
            ),
            if (badge != null) Text(badge!, style: LeaType.ui(11.5).copyWith(color: c.muted)),
          ],
        ),
      ),
    );
  }
}

/// The course picker: switching course keeps the section (Courses shows all).
class CoursePicker extends StatelessWidget {
  const CoursePicker({super.key, required this.section, required this.course, required this.courses});

  final TeachSection section;
  final String? course;
  final List<TeachCourse> courses;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final current = courses.where((x) => x.code == course).firstOrNull;
    return PopupMenuButton<String>(
      tooltip: 'Choose a course',
      enabled: courses.isNotEmpty,
      onSelected: (code) => context.go((section.perCourse ? section : TeachSection.setup).path(code)),
      itemBuilder: (context) => [for (final x in courses) PopupMenuItem(value: x.code, child: Text(x.label))],
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
                  Text(
                    current?.label ?? 'All courses',
                    style: LeaType.ui(13.5, weight: FontWeight.w500).copyWith(color: c.ink),
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                  ),
                ],
              ),
            ),
            Icon(Icons.arrow_drop_down, color: c.ink),
          ],
        ),
      ),
    );
  }
}

class _TeachTopBar extends StatelessWidget {
  const _TeachTopBar({required this.section, required this.course, required this.courses});

  final TeachSection section;
  final String? course;
  final List<TeachCourse> courses;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    return Container(
      padding: const EdgeInsets.fromLTRB(8, 6, 12, 6),
      decoration: BoxDecoration(
        color: c.surface,
        border: Border(bottom: BorderSide(color: c.line)),
      ),
      child: Row(
        children: [
          IconButton(
            tooltip: section == TeachSection.courses ? 'Back to learning' : 'Your courses',
            icon: Icon(Icons.arrow_back, color: c.ink),
            onPressed: () => context.go(section == TeachSection.courses ? Mode.chat.path : TeachSection.courses.path()),
          ),
          Expanded(
            child: Text(
              section == TeachSection.courses
                  ? 'Teaching'
                  : section.perCourse
                  ? '${course ?? ''} · ${section.label}'
                  : section.label,
              style: LeaType.ui(15, weight: FontWeight.w600).copyWith(color: c.ink),
              overflow: TextOverflow.ellipsis,
            ),
          ),
        ],
      ),
    );
  }
}
