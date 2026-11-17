import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:lea_app/api/api_client.dart';
import 'package:lea_app/api/api_error.dart';
import 'package:lea_app/api/sse.dart';

void main() {
  late List<http.BaseRequest> requests;
  late int unauthorizedCalls;
  String? token;

  ApiClient client(MockClient http) => ApiClient(
    baseUrl: 'http://127.0.0.1:8100/',
    httpClient: http,
    token: () => token,
    onUnauthorized: () => unauthorizedCalls++,
  );

  setUp(() {
    requests = [];
    unauthorizedCalls = 0;
    token = 'secret-token';
  });

  MockClient json(int status, Object body, {Map<String, String> headers = const {}}) => MockClient((r) async {
    requests.add(r);
    return http.Response(jsonEncode(body), status, headers: {'content-type': 'application/json', ...headers});
  });

  test('sends the bearer token and JSON body, and decodes the reply', () async {
    final api = client(json(200, {'ok': true}));
    final result = await api.postObject('/chat/DEMO101/messages', {'text': 'Hi', 'week': 1});
    expect(result, {'ok': true});
    final r = requests.single as http.Request;
    expect(r.url.toString(), 'http://127.0.0.1:8100/chat/DEMO101/messages');
    expect(r.headers['Authorization'], 'Bearer secret-token');
    expect(r.headers['Content-Type'], startsWith('application/json'));
    expect(jsonDecode(r.body), {'text': 'Hi', 'week': 1});
  });

  test('adds query parameters', () async {
    final api = client(json(200, {'weeks': []}));
    await api.get('/courses/DEMO101/mastery', query: {'week': '2'});
    expect(requests.single.url.toString(), 'http://127.0.0.1:8100/courses/DEMO101/mastery?week=2');
  });

  test('sends no Authorization header when logged out', () async {
    token = null;
    await client(json(200, [])).get('/courses');
    expect(requests.single.headers.containsKey('Authorization'), isFalse);
  });

  test('a 401 on a request with the token ends the session', () async {
    final api = client(json(401, {'detail': 'Your session has expired.', 'code': 'NotAuthenticated'}));
    await expectLater(api.get('/me/courses'), throwsA(isA<ApiError>().having((e) => e.status, 'status', 401)));
    expect(unauthorizedCalls, 1);
  });

  test('a 401 without a token (a wrong password) is just an error', () async {
    token = null;
    final api = client(json(401, {'detail': 'Wrong username or password.', 'code': 'NotAuthenticated'}));
    await expectLater(
      api.post('/auth/login', {'username': 'a', 'password': 'b'}),
      throwsA(isA<ApiError>().having((e) => e.message, 'message', 'Wrong username or password.')),
    );
    expect(unauthorizedCalls, 0);
  });

  test('a 401 on a start-up check with an explicit token is left to the caller', () async {
    final api = client(json(401, {'detail': 'Expired.', 'code': 'NotAuthenticated'}));
    await expectLater(api.get('/me', token: 'old-token'), throwsA(isA<ApiError>()));
    expect(unauthorizedCalls, 0);
    expect(requests.single.headers['Authorization'], 'Bearer old-token');
  });

  test('a server that can\'t be reached becomes an ApiError', () async {
    final api = client(MockClient((_) async => throw http.ClientException('Connection refused')));
    await expectLater(api.get('/me'), throwsA(isA<ApiError>().having((e) => e.isUnreachable, 'unreachable', true)));
  });

  group('postStream', () {
    MockClient streaming(int status, List<String> chunks, {Map<String, String> headers = const {}}) =>
        MockClient.streaming((request, body) async {
          requests.add(request);
          return http.StreamedResponse(
            Stream.fromIterable(chunks.map(utf8.encode)),
            status,
            headers: {'content-type': 'text/event-stream', ...headers},
          );
        });

    test('streams tokens then done, with the SSE Accept header', () async {
      final api = client(
        streaming(200, [
          'event: token\ndata: {"te',
          'xt": "Hel"}\n\nevent: token\ndata: {"text": "lo"}\n',
          '\nevent: done\ndata: {"ok": true, "message": "Hello"}\n\n',
        ]),
      );
      final events = await api.postStream('/chat/DEMO101/messages/stream', {'text': 'Hi', 'week': 1}).toList();
      expect(events.whereType<ReplyToken>().map((e) => e.text).join(), 'Hello');
      expect((events.last as ReplyDone).body['message'], 'Hello');
      expect(requests.single.headers['Accept'], 'text/event-stream');
      expect(requests.single.headers['Authorization'], 'Bearer secret-token');
    });

    test('an error status before streaming becomes ReplyFailed', () async {
      final api = client(
        streaming(
          429,
          [
            '{"detail": "You\'re going a bit fast. Try again in a moment.", '
                '"code": "RateLimited"}',
          ],
          headers: {'retry-after': '20'},
        ),
      );
      final events = await api.postStream('/tutor/replies/stream', {'text': 'x'}).toList();
      final error = (events.single as ReplyFailed).error;
      expect(error.status, 429);
      expect(error.retryAfter, const Duration(seconds: 20));
    });

    test('a 401 before streaming ends the session', () async {
      final api = client(streaming(401, ['{"detail": "Expired.", "code": "NotAuthenticated"}']));
      final events = await api.postStream('/tutor/replies/stream', {'text': 'x'}).toList();
      expect(events.single, isA<ReplyFailed>());
      expect(unauthorizedCalls, 1);
    });

    test('an unreachable server becomes ReplyFailed, not an exception', () async {
      final api = client(MockClient.streaming((_, _) async => throw http.ClientException('refused')));
      final events = await api.postStream('/tutor/replies/stream', {'text': 'x'}).toList();
      expect((events.single as ReplyFailed).error.isUnreachable, isTrue);
    });
  });
}
