import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../chat/chat_controller.dart';
import '../connectivity.dart';
import '../course/course_state.dart';
import '../providers.dart';
import '../quiz/quiz_controller.dart';
import '../theme/lea_colors.dart';
import '../theme/lea_type.dart';
import '../tutor/tutor_controller.dart';
import '../teach/preview_panel.dart';
import '../teach/preview_state.dart';
import '../widgets/offline_banner.dart';
import 'bottom_nav.dart';
import 'course_panel.dart';
import 'mode.dart';
import 'mode_tabs.dart';
import 'rail.dart';
import 'top_bar.dart';

/// Layout facts screens need: which side of the 720 px breakpoint the app is on, and the
/// matching side padding (22 px wide, 16 px narrow).
class ShellMetrics extends InheritedWidget {
  const ShellMetrics({super.key, required this.wide, required super.child});

  /// The breakpoint is the app's width, not the device's.
  static const breakpoint = 720.0;

  final bool wide;

  double get sidePadding => wide ? 22 : 16;

  static ShellMetrics of(BuildContext context) {
    final metrics = context.dependOnInheritedWidgetOfExactType<ShellMetrics>();
    assert(metrics != null, 'ShellMetrics.of() called outside AppShell');
    return metrics!;
  }

  @override
  bool updateShouldNotify(ShellMetrics old) => old.wide != wide;
}

/// The responsive frame around the four modes: a left rail and tabs at 720 px and wider,
/// a top bar and bottom navigation below that.
class AppShell extends ConsumerWidget {
  const AppShell({super.key, required this.location, required this.child});

  final String location;
  final Widget child;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.lea;
    // Back online: load again whatever failed while the server was away.
    ref.listen(connectivityProvider, (was, now) {
      if (was != false || !now) return;
      if (ref.read(shellInfoProvider).hasError) retryCourse(ref);
      final course = ref.read(shellInfoProvider).value?.course.code;
      if (course != null && ref.read(chatProvider(course)).loadError != null) {
        ref.read(chatProvider(course).notifier).load();
      }
      if (ref.read(tutorProvider).loadError != null) ref.read(tutorProvider.notifier).load();
      if (ref.read(quizProvider).loadError != null) ref.read(quizProvider.notifier).load();
    });
    final infoAsync = ref.watch(shellInfoProvider);
    // Keep showing the last loaded course while a new week or course loads.
    final info = infoAsync.value;
    final error = infoAsync.hasError && info == null ? infoAsync.error : null;
    final user = ref.watch(authProvider).user;
    final preview = ref.watch(previewProvider);
    // The quiz results page shows no mode as active (results-*.png) and has its own title.
    final results = location == '/quiz/results';
    final mode = results ? null : Mode.fromLocation(location);
    final selection = ref.read(selectionProvider.notifier);
    void go(Mode m) => context.go(m.path);

    return Scaffold(
      backgroundColor: c.bg,
      body: LayoutBuilder(
        builder: (context, constraints) {
          final wide = constraints.maxWidth >= ShellMetrics.breakpoint;
          // Without course data no mode can work: say why, with a way to retry, instead of
          // leaving every screen on its loading placeholders.
          final content = ShellMetrics(
            wide: wide,
            child: error == null
                ? child
                : Padding(
                    padding: EdgeInsets.symmetric(horizontal: wide ? 22 : 16, vertical: 20),
                    child: Align(
                      alignment: Alignment.topLeft,
                      child: ConstrainedBox(
                        constraints: const BoxConstraints(maxWidth: 520),
                        child: CoursePanelError(error: error, onRetry: () => retryCourse(ref)),
                      ),
                    ),
                  ),
          );
          if (wide) {
            final body = Row(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Rail(
                  info: info,
                  error: error,
                  user: user,
                  progressActive: mode == Mode.progress,
                  onProgress: () => go(Mode.progress),
                  onLogout: () => ref.read(authProvider.notifier).logout(),
                  onSelectCourse: selection.selectCourse,
                  onSelectWeek: selection.selectWeek,
                  onRetry: () => retryCourse(ref),
                  onTeaching: (user?.isStaff ?? false) && preview == null ? () => context.go('/teach') : null,
                ),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      const OfflineBanner(),
                      ModeTabs(active: mode, onSelect: go),
                      Expanded(child: content),
                    ],
                  ),
                ),
                if (preview != null && constraints.maxWidth >= 1100) ExplainPanel(session: preview),
              ],
            );
            if (preview == null) return body;
            return Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                PreviewBar(session: preview),
                Expanded(child: body),
              ],
            );
          }
          return SafeArea(
            bottom: false,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                if (preview != null) PreviewBar(session: preview),
                TopBar(
                  title: results ? 'Quiz results' : (mode?.label ?? 'LEA'),
                  info: info,
                  onOpenCourse: () => showCourseSheet(context),
                ),
                const OfflineBanner(),
                Expanded(child: content),
                BottomNav(active: mode, onSelect: go),
              ],
            ),
          );
        },
      ),
    );
  }
}

/// Reloads everything the course panel shows, after an error.
void retryCourse(WidgetRef ref) {
  ref.invalidate(myCoursesProvider);
  ref.invalidate(outlineProvider);
  ref.invalidate(progressProvider);
  ref.invalidate(weekMasteryProvider);
}

/// On narrow screens the course and week pickers, and logging out, live in this sheet.
Future<void> showCourseSheet(BuildContext context) {
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    builder: (sheetContext) => Consumer(
      builder: (context, ref, _) {
        final c = context.lea;
        final infoAsync = ref.watch(shellInfoProvider);
        final info = infoAsync.value;
        final user = ref.watch(authProvider).user;
        final selection = ref.read(selectionProvider.notifier);
        return SafeArea(
          child: SingleChildScrollView(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                if (info != null) ...[
                  CourseBox(info: info, onSelect: selection.selectCourse),
                  const SizedBox(height: 16),
                  WeekList(
                    info: info,
                    onSelect: (week) {
                      selection.selectWeek(week);
                      Navigator.of(sheetContext).pop();
                    },
                  ),
                ] else if (infoAsync.hasError)
                  CoursePanelError(error: infoAsync.error!, onRetry: () => retryCourse(ref))
                else
                  const CoursePanelSkeleton(),
                const SizedBox(height: 16),
                if ((user?.isStaff ?? false) && ref.watch(previewProvider) == null) ...[
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    title: Text('Teaching', style: LeaType.small().copyWith(color: c.ink)),
                    trailing: Icon(Icons.arrow_forward, size: 16, color: c.ink),
                    onTap: () {
                      Navigator.of(sheetContext).pop();
                      GoRouter.of(context).go('/teach');
                    },
                  ),
                  const SizedBox(height: 8),
                ],
                Divider(color: c.line, height: 1),
                const SizedBox(height: 8),
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        user == null ? '' : 'Logged in as ${user.displayName}',
                        style: LeaType.small().copyWith(color: c.muted),
                      ),
                    ),
                    TextButton(
                      onPressed: () {
                        Navigator.of(sheetContext).pop();
                        ref.read(authProvider.notifier).logout();
                      },
                      child: Text('Log out', style: LeaType.small().copyWith(color: c.ink)),
                    ),
                  ],
                ),
              ],
            ),
          ),
        );
      },
    ),
  );
}
