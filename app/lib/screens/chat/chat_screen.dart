import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../chat/chat_controller.dart';
import '../../course/course_state.dart';
import '../../shell/app_shell.dart';
import '../../shell/shell_info.dart';
import '../../theme/lea_colors.dart';
import '../../theme/lea_type.dart';
import '../../util/time_format.dart';
import '../../widgets/composer.dart';
import '../../widgets/message_bubble.dart';
import '../../widgets/skeleton.dart';

/// Chat (DESIGN.md, "Chat"; `chat-*.png`): the course's chat history, streamed replies,
/// and suggestions from the week's learning objectives until the first question.
class ChatScreen extends ConsumerWidget {
  const ChatScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final info = ref.watch(shellInfoProvider).value;
    if (info == null) return const _ThreadSkeleton();
    return _Chat(key: ValueKey(info.course.code), info: info);
  }
}

class _Chat extends ConsumerStatefulWidget {
  const _Chat({super.key, required this.info});

  final ShellInfo info;

  @override
  ConsumerState<_Chat> createState() => _ChatState();
}

class _ChatState extends ConsumerState<_Chat> {
  final _input = TextEditingController();
  final _focus = FocusNode();

  static const hint = "Chat doesn't count towards mastery. Use Tutor or Quiz for that.";

  @override
  void dispose() {
    _input.dispose();
    _focus.dispose();
    super.dispose();
  }

  String get _course => widget.info.course.code;

  /// What the student typed, until the reply arrives; put back in the box if it fails.
  String? _pending;

  Future<void> _send([String? suggestion]) async {
    final text = (suggestion ?? _input.text).trim();
    if (text.isEmpty) return;
    if (suggestion == null) {
      _pending = text;
      _input.clear();
    }
    await ref.read(chatProvider(_course).notifier).send(text, widget.info.selectedWeek);
  }

  /// When a send ends in an error, the question goes back in the box so nothing typed is
  /// lost. Done in the same update that ends the send, so it can't lag behind the screen.
  void _onChatChange(ChatState? before, ChatState after) {
    if (before?.sending != true || after.sending) return;
    final text = _pending;
    _pending = null;
    if (after.sendError != null && text != null && _input.text.isEmpty) {
      _input.value = TextEditingValue(
        text: text,
        selection: TextSelection.collapsed(offset: text.length),
      );
    }
  }

  /// Three suggestions from the selected week's learning objectives.
  List<String> _suggestions() {
    final outline = ref.watch(outlineProvider(_course)).value;
    final week = outline?.week(widget.info.selectedWeek);
    return [for (final lo in (week?.learningObjectives ?? const []).take(3)) lo.title];
  }

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final metrics = ShellMetrics.of(context);
    ref.listen(chatProvider(_course), _onChatChange);
    final chat = ref.watch(chatProvider(_course));
    final info = widget.info;
    final greeting = "Hey, I'm LEA. Got questions on ${info.course.code} Week ${info.selectedWeek}? I'm here to help!";
    final suggestions = chat.started || chat.loading ? const <String>[] : _suggestions();

    Widget thread;
    if (chat.loading && chat.entries.isEmpty) {
      thread = const _ThreadSkeleton();
    } else if (chat.loadError != null && chat.entries.isEmpty) {
      thread = _LoadError(
        message: chat.loadError!.message,
        onRetry: () => ref.read(chatProvider(_course).notifier).load(),
      );
    } else {
      // Newest at the bottom; a reversed list keeps the view pinned there as replies stream in.
      final items = <Widget>[
        if (!chat.started) LeaBubble(text: greeting),
        for (final e in chat.entries)
          e.fromStudent
              ? StudentBubble(text: e.text, time: clockTime(e.time))
              : LeaBubble(text: e.text, streaming: e.streaming),
      ];
      thread = SelectionArea(
        child: ListView.separated(
          reverse: true,
          padding: EdgeInsets.symmetric(horizontal: metrics.sidePadding, vertical: 18),
          itemCount: items.length,
          separatorBuilder: (_, _) => const SizedBox(height: 14),
          itemBuilder: (_, i) => items[items.length - 1 - i],
        ),
      );
    }

    return ColoredBox(
      color: c.bg,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Expanded(child: thread),
          Composer(
            controller: _input,
            focusNode: _focus,
            placeholder: 'Ask anything about ${info.course.code}…',
            onSend: _send,
            wide: metrics.wide,
            busy: chat.sending,
            hint: hint,
            error: chat.sendError?.message,
            above: suggestions.isEmpty
                ? null
                : SuggestionChips(
                    suggestions: suggestions,
                    enabled: !chat.sending,
                    onTap: (title) => _send('Tell me about $title.'),
                  ),
          ),
        ],
      ),
    );
  }
}

class _ThreadSkeleton extends StatelessWidget {
  const _ThreadSkeleton();

  @override
  Widget build(BuildContext context) {
    final pad = ShellMetrics.of(context).sidePadding;
    return Semantics(
      label: 'Loading the chat',
      child: Padding(
        padding: EdgeInsets.symmetric(horizontal: pad, vertical: 18),
        child: const Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Align(alignment: Alignment.centerRight, child: SkeletonBox(width: 220, height: 42, radius: 14)),
            SizedBox(height: 14),
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SkeletonBox(width: 32, height: 32, radius: 16),
                SizedBox(width: 10),
                Expanded(child: SkeletonBox(height: 96, radius: 14)),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _LoadError extends StatelessWidget {
  const _LoadError({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final pad = ShellMetrics.of(context).sidePadding;
    return Padding(
      padding: EdgeInsets.symmetric(horizontal: pad, vertical: 20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Semantics(
            liveRegion: true,
            child: Text(message, style: LeaType.bodyText().copyWith(color: c.ink)),
          ),
          const SizedBox(height: 10),
          OutlinedButton(
            onPressed: onRetry,
            style: OutlinedButton.styleFrom(
              foregroundColor: c.ink,
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(9)),
            ),
            child: const Text('Try again'),
          ),
        ],
      ),
    );
  }
}
