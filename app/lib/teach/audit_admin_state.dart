import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../providers.dart';
import 'teach_models.dart';
import 'teach_state.dart';

// ---------------------------------------------------------------------------- content audit

/// The latest audit (null before the first run).
final auditProvider = FutureProvider.autoDispose.family<AuditRun?, String>((ref, code) async {
  final json = await ref.watch(apiClientProvider).get('/teach/courses/$code/audit');
  return json == null ? null : AuditRun.fromJson(json as Map<String, dynamic>);
});

/// What a run costs (only coverage and redundancy use OpenAI).
final auditEstimateProvider = FutureProvider.autoDispose.family<double, String>((ref, code) async {
  final json = await ref.watch(apiClientProvider).getObject('/teach/courses/$code/audit/estimate');
  return (json['usd'] as num).toDouble();
});

/// Runs the audit; throws [ApiError] for the screen to show.
Future<void> runAudit(WidgetRef ref, String code) async {
  await ref.read(apiClientProvider).postObject('/teach/courses/$code/audit/runs');
  ref.invalidate(auditProvider(code));
}

/// Accepts or dismisses a finding (with an optional note), or reopens it.
Future<void> decideFinding(WidgetRef ref, String code, String key, String status, [String note = '']) async {
  await ref.read(apiClientProvider).putObject('/teach/courses/$code/audit/findings/$key', {
    'status': status,
    'note': note,
  });
  ref.invalidate(auditProvider(code));
}

// ---------------------------------------------------------------------------- admin

final adminUsersProvider = FutureProvider.autoDispose<List<AdminUser>>((ref) async {
  final json = await ref.watch(apiClientProvider).get('/admin/users');
  return [for (final u in json as List) AdminUser.fromJson(u as Map<String, dynamic>)];
});

final ownersProvider = FutureProvider.autoDispose.family<List<String>, String>((ref, code) async {
  final json = await ref.watch(apiClientProvider).getObject('/admin/courses/$code/owners');
  return [for (final o in json['owners'] as List) o as String];
});

class AdminActions {
  AdminActions(this.ref);

  final WidgetRef ref;

  void _refresh() {
    ref.invalidate(adminUsersProvider);
    ref.invalidate(teachCoursesProvider);
  }

  Future<void> createStaff({
    required String username,
    required String fullName,
    required String password,
    String role = 'teacher',
  }) async {
    await ref.read(apiClientProvider).postObject('/admin/users', {
      'username': username,
      'full_name': fullName,
      'password': password,
      'role': role,
    });
    _refresh();
  }

  /// Changes an account's role, active state or session kind (only what's given).
  Future<void> update(String username, {String? role, bool? active, String? sessionKind}) async {
    await ref.read(apiClientProvider).patchObject('/admin/users/$username', {
      'role': ?role,
      'active': ?active,
      'session_kind': ?sessionKind,
    });
    _refresh();
  }

  Future<void> addOwner(String code, String username) async {
    await ref.read(apiClientProvider).putObject('/admin/courses/$code/owners/$username');
    ref.invalidate(ownersProvider(code));
    _refresh();
  }

  Future<void> addCourse(String username, String code) async {
    await ref.read(apiClientProvider).putObject('/admin/users/$username/courses/$code');
    _refresh();
  }

  Future<void> removeCourse(String username, String code) async {
    await ref.read(apiClientProvider).delete('/admin/users/$username/courses/$code');
    _refresh();
  }

  Future<void> removeOwner(String code, String username) async {
    await ref.read(apiClientProvider).delete('/admin/courses/$code/owners/$username');
    ref.invalidate(ownersProvider(code));
    _refresh();
  }
}
