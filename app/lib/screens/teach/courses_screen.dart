import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../api/api_error.dart';
import '../../providers.dart';
import '../../teach/preview_state.dart';
import '../../teach/teach_models.dart';
import '../../teach/teach_shell.dart';
import '../../teach/teach_state.dart';
import '../../teach/teach_widgets.dart';
import '../../theme/lea_colors.dart';
import '../../theme/lea_type.dart';
import '../../widgets/ghost_button.dart';
import '../../widgets/meter.dart';
import '../../widgets/skeleton.dart';

/// Teacher home: one card per course, with its state and the next step (`home-*.png`).
class TeachCoursesScreen extends ConsumerWidget {
  const TeachCoursesScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final wide = MediaQuery.sizeOf(context).width >= 720;
    final courses = ref.watch(teachCoursesProvider);
    final admin = ref.watch(authProvider).user?.role == 'admin';
    final ended = ref.read(previewProvider.notifier).endedMessage;
    final count = courses.value?.length;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        TeachHeader(
          kicker: 'Teaching',
          title: 'Your courses',
          subtitle: count == null
              ? null
              : '$count ${count == 1 ? 'course' : 'courses'}${admin ? ' · admin view shows all' : ''}',
          actions: [
            if (wide) FilledButton(onPressed: () => showNewCourseDialog(context, ref), child: const Text('New course')),
          ],
        ),
        Expanded(
          child: ListView(
            padding: EdgeInsets.fromLTRB(wide ? 24 : 16, 18, wide ? 24 : 16, 24),
            children: [
              if (ended != null) ...[
                TeachBanner(tone: BannerTone.soft, child: Text(ended)),
                const SizedBox(height: 14),
              ],
              if (!wide) ...[const DesktopOnlyNote(), const SizedBox(height: 14)],
              switch (courses) {
                AsyncData(value: final list) when list.isEmpty => TeachBanner(
                  child: Text(
                    admin
                        ? 'No courses yet. Set one up with New course.'
                        : 'You don\'t own a course yet. Set one up with New course, or ask an admin to add you to one.',
                  ),
                ),
                AsyncData(value: final list) => _CourseGrid(courses: list, wide: wide),
                AsyncError(:final error) => TeachError(
                  error: error,
                  onRetry: () => ref.invalidate(teachCoursesProvider),
                ),
                _ => const SkeletonBox(height: 220),
              },
            ],
          ),
        ),
      ],
    );
  }
}

class _CourseGrid extends StatelessWidget {
  const _CourseGrid({required this.courses, required this.wide});

  final List<TeachCourse> courses;
  final bool wide;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final columns = constraints.maxWidth >= 900 ? 3 : (constraints.maxWidth >= 560 ? 2 : 1);
        final width = (constraints.maxWidth - (columns - 1) * 14) / columns;
        return Wrap(
          spacing: 14,
          runSpacing: 14,
          children: [
            for (final c in courses)
              SizedBox(
                width: width,
                child: CourseCard(course: c, wide: wide),
              ),
          ],
        );
      },
    );
  }
}

class CourseCard extends ConsumerWidget {
  const CourseCard({super.key, required this.course, required this.wide});

  final TeachCourse course;
  final bool wide;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.lea;
    final me = ref.watch(authProvider).user?.username;
    final owners = [for (final o in course.owners) o == me ? 'you' : o];
    final (String state, PillTone tone) = course.hasKcModel
        ? ('Live', PillTone.ok)
        : course.managed
        ? ('Setting up', PillTone.warn)
        : ('Not published', PillTone.outline);
    return TeachCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              TeachPill(state, tone: tone),
              const Spacer(),
              Flexible(
                child: Text(
                  owners.isEmpty ? 'No owners' : 'Owners: ${owners.join(', ')}',
                  style: LeaType.ui(12).copyWith(color: c.muted),
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          Text(course.code, style: LeaType.heading(19).copyWith(color: c.ink)),
          if (course.name != course.code) Text(course.name, style: LeaType.ui(12.5).copyWith(color: c.muted)),
          const SizedBox(height: 10),
          Wrap(
            spacing: 18,
            runSpacing: 8,
            children: [
              TeachStat(value: '${course.weeks}', label: 'weeks'),
              TeachStat(value: '${course.granularObjectives}', label: 'objectives'),
              if (course.managed) TeachStat(value: '${course.uploads}', label: 'files'),
            ],
          ),
          if (course.activeJob != null) ...[
            const SizedBox(height: 10),
            _JobLine(course: course.code, jobId: course.activeJob!),
          ] else if (!course.hasKcModel) ...[
            const SizedBox(height: 10),
            Text(
              'Students can\'t see this course until you publish its objectives.',
              style: LeaType.ui(12.5).copyWith(color: c.muted),
            ),
          ],
          const SizedBox(height: 12),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              if (course.managed && !course.hasKcModel)
                FilledButton(
                  onPressed: () => context.go(TeachSection.setup.path(course.code)),
                  child: const Text('Continue setup'),
                )
              else
                FilledButton(
                  onPressed: () => context.go(TeachSection.objectives.path(course.code)),
                  child: const Text('Objectives'),
                ),
              if (course.managed && course.hasKcModel)
                GhostButton(label: 'Materials', onPressed: () => context.go(TeachSection.setup.path(course.code))),
              if (course.hasKcModel && wide)
                GhostButton(label: 'Try as a student', onPressed: () => tryAsStudent(context, ref, course.code)),
            ],
          ),
        ],
      ),
    );
  }
}

/// The running build's step and progress.
class _JobLine extends ConsumerWidget {
  const _JobLine({required this.course, required this.jobId});

  final String course;
  final String jobId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.lea;
    final job = ref.watch(_jobProvider(jobId)).value;
    if (job == null) return const SizedBox.shrink();
    final label = job.awaitingConfirmation ? 'Build waiting for you to start it' : 'Building · ${job.stepLabel}';
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          children: [
            Expanded(
              child: Text(label, style: LeaType.ui(12.5).copyWith(color: c.ink)),
            ),
            if (!job.awaitingConfirmation)
              Text('${job.percent.round()}%', style: LeaType.ui(12.5).copyWith(color: c.ink)),
          ],
        ),
        const SizedBox(height: 6),
        Meter(value: job.percent / 100, semanticLabel: 'Build progress'),
      ],
    );
  }
}

final _jobProvider = FutureProvider.autoDispose.family<Job, String>((ref, id) async {
  return Job.fromJson(await ref.watch(apiClientProvider).getObject('/teach/jobs/$id'));
});

/// "New course": code, name, discipline, Python code questions, weeks.
Future<void> showNewCourseDialog(BuildContext context, WidgetRef ref) async {
  final code = await showDialog<String>(context: context, builder: (_) => const _NewCourseDialog());
  if (code != null && context.mounted) context.go(TeachSection.setup.path(code));
}

class _NewCourseDialog extends ConsumerStatefulWidget {
  const _NewCourseDialog();

  @override
  ConsumerState<_NewCourseDialog> createState() => _NewCourseDialogState();
}

class _NewCourseDialogState extends ConsumerState<_NewCourseDialog> {
  final _code = TextEditingController();
  final _name = TextEditingController();
  final _language = TextEditingController(text: 'python');
  String _discipline = 'computing';
  bool _allowsCode = false;
  int _weeks = 6;
  String? _error;
  bool _busy = false;

  @override
  void dispose() {
    _code.dispose();
    _name.dispose();
    _language.dispose();
    super.dispose();
  }

  Future<void> _create() async {
    final code = _code.text.trim().toUpperCase();
    if (!RegExp(r'^[A-Z]{2,4}\d{3}[A-Z]?$').hasMatch(code)) {
      setState(() => _error = 'Course codes are 2-4 letters and 3 digits, like AIML101.');
      return;
    }
    if (_name.text.trim().isEmpty) {
      setState(() => _error = 'Give the course a name.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final created = await createCourse(
        ref,
        CourseCreateRequest(
          code: code,
          name: _name.text.trim(),
          discipline: _discipline,
          allowsCode: _allowsCode,
          codeLanguage: _language.text.trim(),
          weeks: _weeks,
        ),
      );
      if (mounted) Navigator.of(context).pop(created);
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
    InputDecoration deco(String label) => InputDecoration(labelText: label, border: const OutlineInputBorder());
    return AlertDialog(
      title: const Text('New course'),
      content: SizedBox(
        width: 440,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              TextField(key: const Key('course-code'), controller: _code, decoration: deco('Course code, e.g. BIO210')),
              const SizedBox(height: 12),
              TextField(key: const Key('course-name'), controller: _name, decoration: deco('Name')),
              const SizedBox(height: 12),
              DropdownButtonFormField<String>(
                initialValue: _discipline,
                decoration: deco('Subject area'),
                items: [for (final (v, label) in disciplines) DropdownMenuItem(value: v, child: Text(label))],
                onChanged: (v) => setState(() => _discipline = v ?? _discipline),
              ),
              const SizedBox(height: 12),
              DropdownButtonFormField<int>(
                initialValue: _weeks,
                decoration: deco('Weeks'),
                items: [for (var w = 1; w <= 20; w++) DropdownMenuItem(value: w, child: Text('$w'))],
                onChanged: (v) => setState(() => _weeks = v ?? _weeks),
              ),
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text('Code questions in quizzes'),
                value: _allowsCode,
                onChanged: (v) => setState(() => _allowsCode = v),
              ),
              if (_allowsCode) TextField(controller: _language, decoration: deco('Programming language')),
              if (_error != null) ...[
                const SizedBox(height: 10),
                Text(_error!, style: LeaType.small().copyWith(color: c.danger)),
              ],
            ],
          ),
        ),
      ),
      actions: [
        TextButton(onPressed: _busy ? null : () => Navigator.of(context).pop(), child: const Text('Cancel')),
        FilledButton(onPressed: _busy ? null : _create, child: const Text('Create course')),
      ],
    );
  }
}
