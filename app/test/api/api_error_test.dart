import 'package:flutter_test/flutter_test.dart';
import 'package:lea_app/api/api_error.dart';

void main() {
  test('reads detail and code from the API error body', () {
    final e = ApiError.fromResponse(403, '{"detail": "You are not enrolled in DEMO102.", "code": "NotEnrolled"}', {});
    expect(e.status, 403);
    expect(e.code, 'NotEnrolled');
    expect(e.message, 'You are not enrolled in DEMO102.');
  });

  test('falls back to a plain message when the body is not JSON', () {
    final e = ApiError.fromResponse(502, '<html>Bad gateway</html>', {});
    expect(e.code, 'HTTP502');
    expect(e.message, 'Something went wrong on the LEA server. Please try again.');
  });

  test('a 429 without a wait in its detail gets the Retry-After wait', () {
    final e = ApiError.fromResponse(
      429,
      '{"detail": "Too many failed logins from this device. Try again later.", "code": "RateLimited"}',
      {'retry-after': '600'},
    );
    expect(e.retryAfter, const Duration(minutes: 10));
    expect(e.message, 'Too many failed logins from this device. Try again later. (wait 10 minutes)');
  });

  test('a 429 that already says how long to wait is left as it is', () {
    final e = ApiError.fromResponse(
      429,
      '{"detail": "Too many login attempts. Try again in 12 minutes.", "code": "RateLimited"}',
      {'retry-after': '700'},
    );
    expect(e.message, 'Too many login attempts. Try again in 12 minutes.');
  });

  test('short waits are given in seconds', () {
    expect(ApiError.describeWait(const Duration(seconds: 1)), 'wait 1 second');
    expect(ApiError.describeWait(const Duration(seconds: 42)), 'wait 42 seconds');
    expect(ApiError.describeWait(const Duration(seconds: 61)), 'wait 2 minutes');
  });

  test('409 Busy uses the design wording; other 409s keep their detail', () {
    expect(
      ApiError.fromResponse(409, '{"detail": "Busy.", "code": "Busy"}', {}).message,
      'Still working on your last request.',
    );
    expect(
      ApiError.fromResponse(409, '{"detail": "Answer the question first.", "code": "WrongState"}', {}).message,
      'Answer the question first.',
    );
  });

  test('unreachable server', () {
    final e = ApiError.unreachable();
    expect(e.isUnreachable, isTrue);
    expect(e.message, "Can't reach LEA. Check that the LEA server is running.");
  });
}
