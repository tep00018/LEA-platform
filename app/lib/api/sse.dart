import 'dart:async';
import 'dart:convert';

import 'api_error.dart';

/// One server-sent event: its `event:` name (default `message`) and joined `data:` lines.
class SseEvent {
  const SseEvent(this.event, this.data);

  final String event;
  final String data;

  @override
  bool operator ==(Object other) => other is SseEvent && other.event == event && other.data == data;

  @override
  int get hashCode => Object.hash(event, data);

  @override
  String toString() => 'SseEvent($event, $data)';
}

/// Parses a `text/event-stream` body into events.
///
/// Follows the WHATWG event-stream rules that matter here: bytes may split anywhere
/// (even inside a UTF-8 character or a line ending), lines end in LF, CRLF or CR, a blank
/// line dispatches the event, several `data:` lines join with `\n`, one space after the
/// colon is dropped, `:` lines are comments, and an unfinished event at the end is dropped.
Stream<SseEvent> parseSse(Stream<List<int>> bytes) async* {
  var event = '';
  final data = <String>[];
  var hasData = false;

  await for (final line in bytes.transform(utf8.decoder).transform(const LineSplitter())) {
    if (line.isEmpty) {
      if (hasData) yield SseEvent(event.isEmpty ? 'message' : event, data.join('\n'));
      event = '';
      data.clear();
      hasData = false;
      continue;
    }
    if (line.startsWith(':')) continue;

    final colon = line.indexOf(':');
    final field = colon == -1 ? line : line.substring(0, colon);
    var value = colon == -1 ? '' : line.substring(colon + 1);
    if (value.startsWith(' ')) value = value.substring(1);

    switch (field) {
      case 'event':
        event = value;
      case 'data':
        data.add(value);
        hasData = true;
      default:
        // `id`, `retry` and unknown fields don't matter for a one-shot POST stream.
        break;
    }
  }
}

/// A streamed chat or tutor reply, as the app sees it.
sealed class ReplyEvent {
  const ReplyEvent();
}

/// More reply text to append.
class ReplyToken extends ReplyEvent {
  const ReplyToken(this.text);
  final String text;
}

/// The reply finished; [body] is what the non-streaming endpoint would have returned.
class ReplyDone extends ReplyEvent {
  const ReplyDone(this.body);
  final Map<String, dynamic> body;
}

/// The reply failed; the streamed text so far should be discarded.
class ReplyFailed extends ReplyEvent {
  const ReplyFailed(this.error);
  final ApiError error;
}

/// Turns LEA's SSE events into [ReplyEvent]s: `token` (`{"text"}`), then `done` or `error`.
///
/// Always ends with exactly one [ReplyDone] or [ReplyFailed]: a stream that closes early,
/// or sends something unreadable, ends in a [ReplyFailed].
Stream<ReplyEvent> decodeReplyEvents(Stream<SseEvent> events) async* {
  try {
    await for (final e in events) {
      final Object? json;
      try {
        json = jsonDecode(e.data);
      } on FormatException {
        yield ReplyFailed(_broken());
        return;
      }
      if (json is! Map<String, dynamic>) {
        yield ReplyFailed(_broken());
        return;
      }
      switch (e.event) {
        case 'token':
          final text = json['text'];
          if (text is String && text.isNotEmpty) yield ReplyToken(text);
        case 'done':
          yield ReplyDone(json);
          return;
        case 'error':
          yield ReplyFailed(ApiError.fromEvent(json));
          return;
        default:
          break; // Unknown events are ignored so the server can add new ones.
      }
    }
    yield ReplyFailed(_cutOff());
  } on ApiError catch (e) {
    yield ReplyFailed(e);
  } catch (_) {
    // The connection dropped mid-stream.
    yield ReplyFailed(_cutOff());
  }
}

ApiError _cutOff() => const ApiError(
  status: 0,
  code: 'StreamEnded',
  detail: 'The reply was cut off before it finished. Please try again.',
);

ApiError _broken() => const ApiError(
  status: 0,
  code: 'StreamInvalid',
  detail: "LEA sent a reply the app couldn't read. Please try again.",
);
