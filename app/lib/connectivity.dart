import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'providers.dart';

/// Whether the LEA server answered the last request.
///
/// Every request reports in (see `ApiClient.onReachability`). While the server can't be
/// reached, `/health` is checked every few seconds so the banner clears by itself when
/// the server is back.
class ConnectivityController extends Notifier<bool> {
  static const checkEvery = Duration(seconds: 5);

  Timer? _timer;

  @override
  bool build() {
    ref.onDispose(() => _timer?.cancel());
    return true;
  }

  void report(bool reachable) {
    if (reachable == state) return;
    state = reachable;
    _timer?.cancel();
    _timer = reachable ? null : Timer.periodic(checkEvery, (_) => check());
  }

  /// Asks the server now (the banner's "Try again").
  Future<void> check() async {
    try {
      await ref.read(apiClientProvider).get('/health');
    } catch (_) {
      // Reported through onReachability either way.
    }
  }
}

final connectivityProvider = NotifierProvider<ConnectivityController, bool>(ConnectivityController.new);
