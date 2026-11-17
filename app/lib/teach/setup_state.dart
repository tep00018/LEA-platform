import 'dart:async';

import 'package:file_picker/file_picker.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/api_error.dart';
import '../providers.dart';
import 'teach_models.dart';
import 'teach_state.dart';

/// A file chosen for upload.
typedef PickedFile = ({String name, List<int> bytes});

/// Opens the system file picker (tests override this).
final filePickerProvider = Provider<Future<List<PickedFile>> Function()>(
  (ref) => () async {
    final files = await FilePicker.pickFiles(
      type: FileType.custom,
      allowedExtensions: ['pdf', 'docx', 'pptx', 'xlsx', 'md', 'txt', 'ipynb', 'mp3', 'mp4', 'wav'],
    );
    return [for (final f in files) (name: f.name, bytes: await f.xFile.readAsBytes())];
  },
);

/// The weekly objectives (null: none yet).
final planProvider = FutureProvider.autoDispose.family<List<WeekPlan>?, String>((ref, code) async {
  try {
    final json = await ref.watch(apiClientProvider).getObject('/teach/courses/$code/objectives');
    return [for (final w in json['weeks'] as List) WeekPlan.fromJson(w as Map<String, dynamic>)];
  } on ApiError catch (e) {
    if (e.status == 404) return null;
    rethrow;
  }
});

final uploadsProvider = FutureProvider.autoDispose.family<List<CourseUpload>, String>((ref, code) async {
  final json = await ref.watch(apiClientProvider).get('/teach/courses/$code/uploads');
  return [for (final u in json as List) CourseUpload.fromJson(u as Map<String, dynamic>)];
});

/// The course's linked materials folder, or null if none.
final materialsSourceProvider = FutureProvider.autoDispose.family<MaterialsSource?, String>((ref, code) async {
  final json = await ref.watch(apiClientProvider).get('/teach/courses/$code/materials-source');
  return json == null ? null : MaterialsSource.fromJson(json as Map<String, dynamic>);
});

/// Subfolders under the materials root, for the "link a folder" picker.
final materialsFoldersProvider = FutureProvider.autoDispose<List<MaterialsFolder>>((ref) async {
  final json = await ref.watch(apiClientProvider).get('/teach/materials-folders');
  return [for (final f in json as List) MaterialsFolder.fromJson(f as Map<String, dynamic>)];
});

/// What a Build job would pick up from the course's linked folder right now (empty list
/// with no linked source).
final syncPreviewProvider = FutureProvider.autoDispose.family<SyncPreview, String>((ref, code) async {
  final source = await ref.watch(materialsSourceProvider(code).future);
  if (source == null) {
    return const SyncPreview(entries: [], newCount: 0, changed: 0, unchanged: 0, removed: 0, rejected: 0);
  }
  final json = await ref.watch(apiClientProvider).getObject('/teach/courses/$code/materials-source/sync-preview');
  return SyncPreview.fromJson(json);
});

/// The course's latest job (null: none yet).
final latestJobProvider = FutureProvider.autoDispose.family<Job?, String>((ref, code) async {
  final json = await ref.watch(apiClientProvider).get('/teach/courses/$code/jobs');
  final list = [for (final j in json as List) Job.fromJson(j as Map<String, dynamic>)];
  return list.isEmpty ? null : list.first;
});

/// One job with its log, polled every 2 seconds while it's queued or running.
final jobProvider = FutureProvider.autoDispose.family<Job, String>((ref, id) async {
  final job = Job.fromJson(await ref.watch(apiClientProvider).getObject('/teach/jobs/$id'));
  if (job.active) {
    final timer = Timer(const Duration(seconds: 2), ref.invalidateSelf);
    ref.onDispose(timer.cancel);
  }
  return job;
});

/// Setup actions; each throws [ApiError] for the screen to show.
class SetupActions {
  SetupActions(this.ref, this.code);

  final WidgetRef ref;
  final String code;

  void _refresh() {
    ref.invalidate(uploadsProvider(code));
    ref.invalidate(latestJobProvider(code));
    ref.invalidate(teachCourseProvider(code));
    ref.invalidate(teachCoursesProvider);
  }

  Future<void> linkMaterialsSource(String path) async {
    await ref.read(apiClientProvider).postObject(
      '/teach/courses/$code/materials-source', {'type': 'folder', 'path': path});
    ref.invalidate(materialsSourceProvider(code));
    ref.invalidate(syncPreviewProvider(code));
  }

  Future<void> unlinkMaterialsSource() async {
    await ref.read(apiClientProvider).delete('/teach/courses/$code/materials-source');
    ref.invalidate(materialsSourceProvider(code));
    ref.invalidate(syncPreviewProvider(code));
  }

  Future<void> savePlan(List<WeekPlan> weeks) async {
    await ref.read(apiClientProvider).putObject('/teach/courses/$code/objectives', {
      'weeks': [for (final w in weeks) w.toJson()],
    });
    ref.invalidate(planProvider(code));
  }

  Future<void> upload(List<PickedFile> files, {int? week, String? kind}) async {
    await ref
        .read(apiClientProvider)
        .postFiles(
          '/teach/courses/$code/uploads',
          [for (final f in files) ('files', f.name, f.bytes)],
          {if (week != null) 'week': '$week', 'kind': ?kind},
        );
    _refresh();
  }

  Future<void> deleteUpload(String name) async {
    await ref.read(apiClientProvider).delete('/teach/courses/$code/uploads/${Uri.encodeComponent(name)}');
    _refresh();
  }

  /// Prepares and prices a build (nothing runs yet).
  Future<Job> prepareBuild() async {
    final job = Job.fromJson(await ref.read(apiClientProvider).postObject('/teach/courses/$code/jobs', {}));
    _refresh();
    return job;
  }

  Future<void> confirm(String id) async {
    await ref.read(apiClientProvider).post('/teach/jobs/$id/confirm');
    ref.invalidate(jobProvider(id));
    _refresh();
  }

  Future<void> cancel(String id) async {
    await ref.read(apiClientProvider).post('/teach/jobs/$id/cancel');
    ref.invalidate(jobProvider(id));
    _refresh();
  }
}
