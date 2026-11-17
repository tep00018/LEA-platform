import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http/http.dart' as http;

import 'api/api_client.dart';
import 'api/http_client.dart';
import 'auth/auth_controller.dart';
import 'auth/token_store.dart';
import 'config.dart';
import 'connectivity.dart';
import 'teach/preview_state.dart';

/// No automatic retries: a failed request shows the API's message and the screen offers
/// its own "Try again". Riverpod 3 would otherwise retry quietly and keep showing loading.
Duration? noRetry(int retryCount, Object error) => null;

/// App-wide providers. Tests override [httpClientProvider], [tokenStoreProvider] and
/// [apiBaseUrlProvider] to run against a fake API.

final apiBaseUrlProvider = Provider<String>((ref) => apiBaseUrl);

final httpClientProvider = Provider<http.Client>((ref) {
  final client = createHttpClient();
  ref.onDispose(client.close);
  return client;
});

final tokenStoreProvider = Provider<TokenStore>((ref) => SecureTokenStore());

final authProvider = NotifierProvider<AuthController, AuthState>(AuthController.new);

final apiClientProvider = Provider<ApiClient>((ref) {
  return ApiClient(
    baseUrl: ref.watch(apiBaseUrlProvider),
    httpClient: ref.watch(httpClientProvider),
    token: () => ref.read(authProvider).token,
    onUnauthorized: () => ref.read(authProvider.notifier).sessionExpired(),
    onReachability: (reachable) => ref.read(connectivityProvider.notifier).report(reachable),
    previewToken: () => ref.read(previewProvider)?.token,
    onPreviewUnauthorized: () => ref.read(previewProvider.notifier).expired(),
  );
});

/// Whose data the student screens show: the sandbox's while previewing, otherwise the
/// logged-in account's (null when logged out). Screens reload when it changes.
final sessionProvider = Provider<String?>((ref) {
  final token = ref.watch(authProvider.select((s) => s.token));
  if (token == null) return null;
  return ref.watch(previewProvider)?.token ?? token;
});
