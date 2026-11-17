import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'auth/auth_controller.dart';
import 'providers.dart';
import 'screens/chat/chat_screen.dart';
import 'screens/login/login_screen.dart';
import 'screens/progress/progress_screen.dart';
import 'screens/quiz/quiz_screen.dart';
import 'screens/tutor/tutor_screen.dart';
import 'screens/start_screen.dart';
import 'screens/teach/admin_screen.dart';
import 'screens/teach/analytics_screen.dart';
import 'screens/teach/audit_screen.dart';
import 'screens/teach/objective_analytics_screen.dart';
import 'screens/teach/video_editor_screen.dart';
import 'screens/teach/videos_screen.dart';
import 'screens/teach/courses_screen.dart';
import 'screens/teach/objectives_screen.dart';
import 'screens/teach/review_screen.dart';
import 'screens/teach/setup_screen.dart';
import 'shell/app_shell.dart';
import 'shell/mode.dart';
import 'teach/teach_shell.dart';

/// Where the app goes for a given login state, or null to stay put.
///
/// - While a saved token is being checked, everything waits on `/start`.
/// - Logged out: `/login`.
/// - Logged in: `/login` and `/start` move on to where the student was headed, or Chat.
/// - The Teacher area (`/teach`) is for teachers and admins; anyone else goes to Chat.
///   `/admin` is for admins only (teachers go to their courses).
@visibleForTesting
String? authRedirect(AuthState auth, Uri uri) {
  final path = uri.path;
  final from = uri.queryParameters['from'];
  switch (auth.status) {
    case AuthStatus.restoring:
      if (path == '/start') return null;
      return Uri(path: '/start', queryParameters: path == '/login' ? null : {'from': uri.toString()}).toString();
    case AuthStatus.signedOut:
      return path == '/login' ? null : '/login';
    case AuthStatus.signedIn:
      if (path == '/login' || path == '/start') {
        // Only ever continue to one of the app's own screens, rebuilt from its path.
        final target = from == null ? null : Uri.tryParse(from);
        if (target != null && (Mode.fromLocation(target.path) != null || _isTeach(target.path))) {
          final denied = _staffOnly(auth, target.path);
          if (denied != null) return denied;
          return Uri(path: target.path, query: target.hasQuery ? target.query : null).toString();
        }
        return Mode.chat.path;
      }
      return _staffOnly(auth, path);
  }
}

bool _isTeach(String path) =>
    path == '/teach' || path.startsWith('/teach/') || path == '/admin' || path.startsWith('/admin/');

/// Where someone who may not see [path] goes instead (null: they may).
String? _staffOnly(AuthState auth, String path) {
  if (!_isTeach(path)) return null;
  final role = auth.user?.role ?? 'student';
  if (role == 'student') return Mode.chat.path;
  if (path.startsWith('/admin') && role != 'admin') return '/teach';
  return null;
}

final routerProvider = Provider<GoRouter>((ref) {
  final refresh = ValueNotifier(0);
  ref.listen(authProvider, (_, _) => refresh.value++);

  final router = GoRouter(
    initialLocation: Mode.chat.path,
    refreshListenable: refresh,
    redirect: (context, state) => authRedirect(ref.read(authProvider), state.uri),
    onException: (context, state, router) => router.go(Mode.chat.path),
    routes: [
      GoRoute(
        path: '/start',
        pageBuilder: (context, state) => const NoTransitionPage(child: StartScreen()),
      ),
      GoRoute(
        path: '/login',
        pageBuilder: (context, state) => const NoTransitionPage(child: LoginScreen()),
      ),
      ShellRoute(
        builder: (context, state, child) => AppShell(location: state.uri.path, child: child),
        routes: [
          GoRoute(
            path: Mode.chat.path,
            pageBuilder: (context, state) => const NoTransitionPage(key: ValueKey(Mode.chat), child: ChatScreen()),
          ),
          GoRoute(
            path: Mode.tutor.path,
            pageBuilder: (context, state) => const NoTransitionPage(key: ValueKey(Mode.tutor), child: TutorScreen()),
          ),
          GoRoute(
            path: Mode.quiz.path,
            pageBuilder: (context, state) => const NoTransitionPage(key: ValueKey(Mode.quiz), child: QuizScreen()),
          ),
          GoRoute(
            path: quizResultsPath,
            pageBuilder: (context, state) =>
                const NoTransitionPage(key: ValueKey(quizResultsPath), child: QuizScreen()),
          ),
          GoRoute(
            path: Mode.progress.path,
            pageBuilder: (context, state) =>
                const NoTransitionPage(key: ValueKey(Mode.progress), child: ProgressScreen()),
          ),
        ],
      ),
      ShellRoute(
        builder: (context, state, child) => TeachShell(location: state.uri.path, child: child),
        routes: [
          GoRoute(
            path: '/teach',
            pageBuilder: (context, state) => const NoTransitionPage(child: TeachCoursesScreen()),
          ),
          GoRoute(
            path: '/teach/courses/:code/setup',
            pageBuilder: (context, state) => NoTransitionPage(
              key: ValueKey('setup-${state.pathParameters['code']}'),
              child: SetupScreen(code: state.pathParameters['code']!),
            ),
          ),
          GoRoute(
            path: '/teach/courses/:code/objectives',
            pageBuilder: (context, state) => NoTransitionPage(
              key: ValueKey('objectives-${state.pathParameters['code']}'),
              child: ObjectivesScreen(code: state.pathParameters['code']!, from: state.uri.queryParameters['from']),
            ),
          ),
          GoRoute(
            path: '/teach/courses/:code/audit',
            pageBuilder: (context, state) => NoTransitionPage(
              key: ValueKey('audit-${state.pathParameters['code']}'),
              child: AuditScreen(code: state.pathParameters['code']!),
            ),
          ),
          GoRoute(
            path: '/teach/courses/:code/videos',
            pageBuilder: (context, state) => NoTransitionPage(
              key: ValueKey('videos-${state.pathParameters['code']}'),
              child: VideosScreen(code: state.pathParameters['code']!),
            ),
          ),
          GoRoute(
            path: '/teach/courses/:code/videos/:go',
            pageBuilder: (context, state) => NoTransitionPage(
              key: ValueKey('videos-${state.pathParameters['code']}-${state.pathParameters['go']}'),
              child: VideoEditorScreen(code: state.pathParameters['code']!, go: state.pathParameters['go']!),
            ),
          ),
          GoRoute(
            path: '/teach/courses/:code/analytics',
            pageBuilder: (context, state) => NoTransitionPage(
              key: ValueKey('analytics-${state.pathParameters['code']}'),
              child: AnalyticsScreen(code: state.pathParameters['code']!),
            ),
          ),
          GoRoute(
            path: '/teach/courses/:code/analytics/:go',
            pageBuilder: (context, state) => NoTransitionPage(
              key: ValueKey('analytics-${state.pathParameters['code']}-${state.pathParameters['go']}'),
              child: ObjectiveAnalyticsScreen(code: state.pathParameters['code']!, go: state.pathParameters['go']!),
            ),
          ),
          GoRoute(path: '/admin', redirect: (context, state) => '/admin/users'),
          GoRoute(
            path: '/admin/users',
            pageBuilder: (context, state) => const NoTransitionPage(child: AdminScreen()),
          ),
          GoRoute(
            path: '/teach/courses/:code/objectives/review',
            pageBuilder: (context, state) => NoTransitionPage(
              key: ValueKey('review-${state.pathParameters['code']}'),
              child: ReviewScreen(code: state.pathParameters['code']!),
            ),
          ),
        ],
      ),
    ],
  );
  ref.onDispose(() {
    router.dispose();
    refresh.dispose();
  });
  return router;
});
