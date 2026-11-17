import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/api_error.dart';
import '../api/models.dart';
import '../providers.dart';

enum AuthStatus {
  /// Checking a saved token at start-up.
  restoring,
  signedOut,
  signedIn,
}

class AuthState {
  const AuthState._(this.status, {this.token, this.user, this.message});

  const AuthState.restoring() : this._(AuthStatus.restoring);

  /// [message] is shown on the login screen ("Please log in again.").
  const AuthState.signedOut({String? message}) : this._(AuthStatus.signedOut, message: message);

  const AuthState.signedIn(String token, UserProfile user) : this._(AuthStatus.signedIn, token: token, user: user);

  final AuthStatus status;
  final String? token;
  final UserProfile? user;
  final String? message;
}

/// Who is logged in. Restores a saved token on start (validated with `GET /me`), logs in
/// and out, and ends the session when the API answers 401.
class AuthController extends Notifier<AuthState> {
  @override
  AuthState build() {
    Future.microtask(_restore);
    return const AuthState.restoring();
  }

  Future<void> _restore() async {
    final store = ref.read(tokenStoreProvider);
    final token = await store.read();
    if (!ref.mounted) return;
    if (token == null) {
      state = const AuthState.signedOut();
      return;
    }
    try {
      final me = await ref.read(apiClientProvider).getObject('/me', token: token);
      if (!ref.mounted) return;
      state = AuthState.signedIn(token, UserProfile.fromJson(me));
    } on ApiError catch (e) {
      if (!ref.mounted) return;
      if (e.isUnauthorized) {
        await store.clear();
        state = const AuthState.signedOut(message: ApiError.sessionExpiredDetail);
      } else {
        // Keep the token: once the server is back, logging in again isn't needed.
        state = AuthState.signedOut(message: e.message);
      }
    }
  }

  /// Logs in; throws [ApiError] for the login screen to show.
  Future<void> login(String username, String password) async {
    final json = await ref.read(apiClientProvider).postObject('/auth/login', {
      'username': username.trim(),
      'password': password,
    });
    final result = LoginResult.fromJson(json);
    await ref.read(tokenStoreProvider).write(result.token);
    state = AuthState.signedIn(result.token, result.user);
  }

  /// Ends the session on the server (best effort) and forgets the token.
  Future<void> logout() async {
    if (state.token != null) {
      try {
        await ref.read(apiClientProvider).post('/auth/logout');
      } on ApiError {
        // Already expired or unreachable: forgetting it locally is what matters.
      }
    }
    await ref.read(tokenStoreProvider).clear();
    state = const AuthState.signedOut();
  }

  /// Called when any request with the token gets a 401.
  Future<void> sessionExpired() async {
    if (state.status != AuthStatus.signedIn) return;
    state = const AuthState.signedOut(message: ApiError.sessionExpiredDetail);
    await ref.read(tokenStoreProvider).clear();
  }
}
