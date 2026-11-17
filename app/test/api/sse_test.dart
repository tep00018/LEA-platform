import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:lea_app/api/sse.dart';

/// Splits [text]'s UTF-8 bytes into chunks of [size] bytes, so chunk edges fall inside
/// lines, field names, `\r\n` pairs and multi-byte characters.
Stream<List<int>> chunked(String text, int size) async* {
  final bytes = utf8.encode(text);
  for (var i = 0; i < bytes.length; i += size) {
    yield bytes.sublist(i, i + size > bytes.length ? bytes.length : i + size);
  }
}

String sse(String event, Object data) => 'event: $event\ndata: ${jsonEncode(data)}\n\n';

void main() {
  group('parseSse', () {
    final body =
        sse('token', {'text': 'Supervised learning '}) +
        sse('token', {'text': 'uses labelled data — “like this” 😀.'}) +
        sse('done', {'ok': true, 'message': 'Supervised learning uses labelled data.'});

    final expected = [
      SseEvent('token', jsonEncode({'text': 'Supervised learning '})),
      SseEvent('token', jsonEncode({'text': 'uses labelled data — “like this” 😀.'})),
      SseEvent('done', jsonEncode({'ok': true, 'message': 'Supervised learning uses labelled data.'})),
    ];

    test('reads a whole body in one chunk', () async {
      expect(await parseSse(Stream.value(utf8.encode(body))).toList(), expected);
    });

    test('gives the same events whatever the chunk size, including 1 byte', () async {
      for (final size in [1, 2, 3, 5, 7, 13, 64]) {
        expect(await parseSse(chunked(body, size)).toList(), expected, reason: 'chunk size $size');
      }
    });

    test('accepts CRLF and CR line endings, even split between chunks', () async {
      final crlf = body.replaceAll('\n', '\r\n');
      final cr = body.replaceAll('\n', '\r');
      for (final size in [1, 2, 3, 64]) {
        expect(await parseSse(chunked(crlf, size)).toList(), expected, reason: 'CRLF, chunk size $size');
      }
      expect(await parseSse(chunked(cr, 4)).toList(), expected);
    });

    test('joins several data lines with newlines and drops one leading space', () async {
      const text = 'event: token\ndata: line one\ndata:line two\ndata:  indented\n\n';
      expect(await parseSse(chunked(text, 3)).toList(), [const SseEvent('token', 'line one\nline two\n indented')]);
    });

    test('ignores comments, unknown fields and blank lines between events', () async {
      const text = ': keep-alive\n\n\nid: 7\nretry: 1000\nevent: done\nfoo: bar\ndata: {}\n\n';
      expect(await parseSse(chunked(text, 2)).toList(), [const SseEvent('done', '{}')]);
    });

    test('names an event with no event field "message"', () async {
      expect(await parseSse(chunked('data: hi\n\n', 1)).toList(), [const SseEvent('message', 'hi')]);
    });

    test('drops an event the stream ends in the middle of', () async {
      const text = 'event: token\ndata: {"text": "a"}\n\nevent: done\ndata: {"ok": true}';
      expect(await parseSse(chunked(text, 4)).toList(), [const SseEvent('token', '{"text": "a"}')]);
    });
  });

  group('decodeReplyEvents', () {
    Future<List<ReplyEvent>> decode(String body, {int chunk = 3}) =>
        decodeReplyEvents(parseSse(chunked(body, chunk))).toList();

    test('tokens split across chunks, then done', () async {
      final events = await decode(
        sse('token', {'text': 'Hel'}) + sse('token', {'text': 'lo'}) + sse('done', {'ok': true, 'message': 'Hello'}),
        chunk: 1,
      );
      expect(events.whereType<ReplyToken>().map((e) => e.text).join(), 'Hello');
      expect(events.last, isA<ReplyDone>());
      expect((events.last as ReplyDone).body['message'], 'Hello');
    });

    test('an error event ends the stream with its detail, code and status', () async {
      final events = await decode(
        sse('token', {'text': 'Partial'}) +
            sse('error', {'detail': 'Still working on your last request.', 'code': 'Busy', 'status': 409}),
      );
      final failed = events.last as ReplyFailed;
      expect(failed.error.detail, 'Still working on your last request.');
      expect(failed.error.code, 'Busy');
      expect(failed.error.status, 409);
      expect(failed.error.isBusy, isTrue);
    });

    test('nothing after done is delivered', () async {
      final events = await decode(sse('done', {'ok': true}) + sse('token', {'text': 'late'}));
      expect(events, hasLength(1));
      expect(events.single, isA<ReplyDone>());
    });

    test('a stream that ends without done or error fails as cut off', () async {
      final events = await decode(sse('token', {'text': 'Half a rep'}));
      expect(events.first, isA<ReplyToken>());
      expect((events.last as ReplyFailed).error.code, 'StreamEnded');
    });

    test('unreadable data fails the reply', () async {
      final events = await decode('event: token\ndata: {not json\n\n');
      expect((events.single as ReplyFailed).error.code, 'StreamInvalid');
    });

    test('unknown events and empty tokens are skipped', () async {
      final events = await decode(
        sse('progress', {'step': 1}) + sse('token', {'text': ''}) + sse('done', {'ok': true, 'message': 'x'}),
      );
      expect(events.single, isA<ReplyDone>());
    });

    test('a connection that drops mid-stream fails as cut off', () async {
      final controller = StreamController<List<int>>();
      final result = decodeReplyEvents(parseSse(controller.stream)).toList();
      controller.add(utf8.encode(sse('token', {'text': 'Hi'})));
      controller.addError(Exception('connection reset'));
      await controller.close();
      final events = await result;
      expect(events.first, isA<ReplyToken>());
      expect((events.last as ReplyFailed).error.code, 'StreamEnded');
    });
  });
}
