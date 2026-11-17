import 'package:flutter_test/flutter_test.dart';
import 'package:lea_app/api/models.dart';
import 'package:lea_app/auth/auth_controller.dart';
import 'package:lea_app/router.dart';

void main() {
  const restoring = AuthState.restoring();
  const signedOut = AuthState.signedOut();
  const signedIn = AuthState.signedIn('t', UserProfile(username: 'alex.m'));

  String? go(AuthState s, String location) => authRedirect(s, Uri.parse(location));

  test('while checking a saved token, everything waits on /start and remembers where it was going', () {
    expect(go(restoring, '/quiz'), '/start?from=%2Fquiz');
    expect(go(restoring, '/start'), isNull);
    expect(go(restoring, '/login'), '/start');
  });

  test('logged out goes to /login', () {
    for (final path in ['/chat', '/tutor', '/quiz', '/progress', '/start']) {
      expect(go(signedOut, path), '/login', reason: path);
    }
    expect(go(signedOut, '/login'), isNull);
  });

  test('logged in leaves /login and /start for Chat, or where it was going', () {
    expect(go(signedIn, '/login'), '/chat');
    expect(go(signedIn, '/start'), '/chat');
    expect(go(signedIn, '/start?from=%2Fprogress'), '/progress');
    expect(go(signedIn, '/start?from=https%3A%2F%2Fevil.example'), '/chat');
    expect(go(signedIn, '/start?from=%2F%2Fevil.example%2Fchat'), '/chat');
    expect(go(signedIn, '/tutor'), isNull);
  });

  test('the Teacher area is for teachers and admins', () {
    const teacher = AuthState.signedIn('t', UserProfile(username: 'rivera', role: 'teacher'));
    const admin = AuthState.signedIn('t', UserProfile(username: 'root', role: 'admin'));
    expect(go(signedIn, '/teach'), '/chat');
    expect(go(signedIn, '/teach/courses/AIML101/setup'), '/chat');
    expect(go(teacher, '/teach'), isNull);
    expect(go(admin, '/teach/courses/AIML101/objectives'), isNull);
    expect(go(teacher, '/start?from=%2Fteach'), '/teach');
    expect(go(signedIn, '/start?from=%2Fteach'), '/chat');
  });
}
