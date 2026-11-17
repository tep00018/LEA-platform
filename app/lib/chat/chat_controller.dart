import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/api_error.dart';
import '../api/models.dart';
import '../api/sse.dart';
import '../providers.dart';

/// One bubble in the chat thread.
class ChatEntry {
  const ChatEntry({required this.fromStudent, required this.text, required this.time, this.streaming = false});

  final bool fromStudent;
  final String text;
  final DateTime time;

  /// LEA's reply while it's still arriving.
  final bool streaming;

  ChatEntry copyWith({String? text, bool? streaming}) =>
      ChatEntry(fromStudent: fromStudent, text: text ?? this.text, time: time, streaming: streaming ?? this.streaming);
}

class ChatState {
  const ChatState({this.entries = const [], this.loading = true, this.loadError, this.sending = false, this.sendError});

  final List<ChatEntry> entries;

  /// Loading the history.
  final bool loading;
  final ApiError? loadError;

  /// A reply is on its way; the composer waits.
  final bool sending;

  /// Why the last message didn't go through.
  final ApiError? sendError;

  /// Whether the student has asked anything yet (the suggestions show until they have).
  bool get started => entries.any((e) => e.fromStudent);

  ChatState copyWith({
    List<ChatEntry>? entries,
    bool? loading,
    ApiError? Function()? loadError,
    bool? sending,
    ApiError? Function()? sendError,
  }) {
    return ChatState(
      entries: entries ?? this.entries,
      loading: loading ?? this.loading,
      loadError: loadError == null ? this.loadError : loadError(),
      sending: sending ?? this.sending,
      sendError: sendError == null ? this.sendError : sendError(),
    );
  }
}

/// The chat for one course: history from `GET /chat/{code}/messages`, and new questions
/// sent to `POST /chat/{code}/messages/stream`.
class ChatController extends Notifier<ChatState> {
  ChatController(this.course);

  final String course;

  /// Replaceable in tests.
  DateTime Function() now = DateTime.now;

  @override
  ChatState build() {
    // Nothing to load for nobody (just after logging out).
    if (ref.watch(sessionProvider) != null) Future.microtask(load);
    return const ChatState();
  }

  Future<void> load() async {
    state = state.copyWith(loading: true, loadError: () => null);
    try {
      final json = await ref.read(apiClientProvider).get('/chat/$course/messages');
      if (!ref.mounted) return;
      final history = [for (final m in json as List) ChatMessage.fromJson(m as Map<String, dynamic>)]
          .where((m) => m.message.trim().isNotEmpty);
      state = state.copyWith(
        loading: false,
        entries: [
          for (final m in history) ChatEntry(fromStudent: m.fromStudent, text: m.message, time: m.time),
          // Keep anything sent while the history was loading.
          ...state.entries,
        ],
      );
    } on ApiError catch (e) {
      if (!ref.mounted) return;
      state = state.copyWith(loading: false, loadError: () => e);
    }
  }

  /// Sends [text] about [week] and streams LEA's reply into the thread.
  ///
  /// Returns false if it failed: the student's message and the partial reply are removed,
  /// [ChatState.sendError] says why, and the screen puts the text back in the input.
  Future<bool> send(String text, int week) async {
    final question = text.trim();
    if (question.isEmpty || state.sending) return false;

    final before = state.entries;
    final asked = ChatEntry(fromStudent: true, text: question, time: now());
    var reply = ChatEntry(fromStudent: false, text: '', time: now(), streaming: true);
    state = state.copyWith(entries: [...before, asked, reply], sending: true, sendError: () => null);

    final events = ref
        .read(apiClientProvider)
        .postStream('/chat/$course/messages/stream', ChatRequest(text: question, week: week).toJson());

    await for (final event in events) {
      if (!ref.mounted) return false;
      switch (event) {
        case ReplyToken(:final text):
          reply = reply.copyWith(text: reply.text + text);
          state = state.copyWith(entries: [...before, asked, reply]);
        case ReplyDone(:final body):
          final done = ChatReply.fromJson(body);
          reply = reply.copyWith(text: done.message.isEmpty ? reply.text : done.message, streaming: false);
          state = state.copyWith(entries: [...before, asked, reply], sending: false);
          return true;
        case ReplyFailed(:final error):
          state = state.copyWith(entries: before, sending: false, sendError: () => error);
          return false;
      }
    }
    return false; // decodeReplyEvents always ends in done or failed; kept for the analyzer.
  }

  void dismissError() => state = state.copyWith(sendError: () => null);
}

final chatProvider = NotifierProvider.family<ChatController, ChatState, String>(ChatController.new);
