import 'dart:convert';

/// An error from the LEA API, or from failing to reach it.
///
/// The API sends every error as `{"detail", "code"}` and `detail` is written for
/// students, so [message] is what the UI shows.
class ApiError implements Exception {
  const ApiError({required this.status, required this.code, required this.detail, this.retryAfter});

  /// HTTP status, or 0 when the server couldn't be reached.
  final int status;
  final String code;
  final String detail;

  /// From `Retry-After` on a 429.
  final Duration? retryAfter;

  static const unreachableDetail = "Can't reach LEA. Check that the LEA server is running.";
  static const sessionExpiredDetail = 'Please log in again.';
  static const busyDetail = 'Still working on your last request.';

  factory ApiError.unreachable() => const ApiError(status: 0, code: 'NetworkError', detail: unreachableDetail);

  /// Builds the error from a non-2xx response.
  factory ApiError.fromResponse(int status, String body, Map<String, String> headers) {
    String? detail;
    String? code;
    try {
      final json = jsonDecode(body);
      if (json is Map<String, dynamic>) {
        detail = json['detail'] is String ? json['detail'] as String : null;
        code = json['code'] is String ? json['code'] as String : null;
      }
    } on FormatException {
      // Not JSON (a proxy error page, say): fall back to a generic message below.
    }
    return ApiError(
      status: status,
      code: code ?? 'HTTP$status',
      detail: (detail == null || detail.trim().isEmpty) ? _fallback(status) : detail,
      retryAfter: _parseRetryAfter(headers['retry-after']),
    );
  }

  /// Builds the error carried by a streamed `error` event: `{"detail","code","status"}`.
  factory ApiError.fromEvent(Map<String, dynamic> json) {
    final status = json['status'] is int ? json['status'] as int : 500;
    final detail = json['detail'] is String ? json['detail'] as String : _fallback(status);
    return ApiError(
      status: status,
      code: json['code'] is String ? json['code'] as String : 'HTTP$status',
      detail: detail,
    );
  }

  bool get isUnauthorized => status == 401;
  bool get isUnreachable => status == 0;
  bool get isBusy => status == 409 && code == 'Busy';

  /// The text to show. A 409 `Busy` gets the design's wording; a 429 whose detail
  /// doesn't already say how long to wait gets the wait from `Retry-After`.
  String get message {
    if (isBusy) return busyDetail;
    final wait = retryAfter;
    if (status == 429 && wait != null && !RegExp(r'\d').hasMatch(detail)) {
      return '$detail (${describeWait(wait)})';
    }
    return detail;
  }

  static String describeWait(Duration wait) {
    final seconds = wait.inSeconds;
    if (seconds < 60) return 'wait $seconds second${seconds == 1 ? '' : 's'}';
    final minutes = (seconds / 60).ceil();
    return 'wait $minutes minute${minutes == 1 ? '' : 's'}';
  }

  static Duration? _parseRetryAfter(String? value) {
    final seconds = int.tryParse(value?.trim() ?? '');
    return seconds == null ? null : Duration(seconds: seconds);
  }

  static String _fallback(int status) => switch (status) {
    401 => sessionExpiredDetail,
    429 => 'Too many requests. Try again in a moment.',
    >= 500 => 'Something went wrong on the LEA server. Please try again.',
    _ => 'Something went wrong. Please try again.',
  };

  @override
  String toString() => 'ApiError($status $code: $detail)';
}
