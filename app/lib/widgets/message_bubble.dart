import 'package:flutter/material.dart';

import '../theme/lea_colors.dart';
import '../theme/lea_type.dart';
import 'lea_avatar.dart';
import 'markdown_text.dart';
import 'streaming_cursor.dart';

/// Bubbles are at most about 74 characters wide.
const bubbleMaxWidth = 600.0;

/// LEA's message: avatar (32 px) and a `surface` bubble with a 1 px `line` border,
/// radius 4/14/14/14. While [streaming], the blinking cursor follows the text.
class LeaBubble extends StatelessWidget {
  const LeaBubble({super.key, required this.text, this.streaming = false});

  final String text;
  final bool streaming;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final style = LeaType.ui(14.5, height: 1.55).copyWith(color: c.ink);
    return Align(
      alignment: Alignment.centerLeft,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: bubbleMaxWidth + 42),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const LeaAvatar(size: 32, ring: false),
            const SizedBox(width: 10),
            Flexible(
              child: Semantics(
                label: streaming && text.isEmpty ? 'LEA is writing' : 'LEA',
                liveRegion: !streaming,
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                  decoration: BoxDecoration(
                    color: c.surface,
                    border: Border.all(color: c.line),
                    borderRadius: const BorderRadius.only(
                      topLeft: Radius.circular(4),
                      topRight: Radius.circular(14),
                      bottomLeft: Radius.circular(14),
                      bottomRight: Radius.circular(14),
                    ),
                  ),
                  child: MarkdownText(
                    text,
                    style: style,
                    trailing: streaming
                        ? const WidgetSpan(alignment: PlaceholderAlignment.middle, child: StreamingCursor())
                        : null,
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// The student's message: `primary` fill, `on-primary` text, radius 14/4/14/14,
/// right-aligned, with a meta line under it (optional tag, then the time).
class StudentBubble extends StatelessWidget {
  const StudentBubble({super.key, required this.text, required this.time, this.tag});

  final String text;
  final String time;

  /// E.g. "Counted · correct" in Tutor.
  final Widget? tag;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    return Align(
      alignment: Alignment.centerRight,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: bubbleMaxWidth),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            Semantics(
              label: 'You',
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                decoration: BoxDecoration(
                  color: c.primary,
                  borderRadius: const BorderRadius.only(
                    topLeft: Radius.circular(14),
                    topRight: Radius.circular(4),
                    bottomLeft: Radius.circular(14),
                    bottomRight: Radius.circular(14),
                  ),
                ),
                child: Text(text, style: LeaType.ui(14.5, height: 1.55).copyWith(color: c.onPrimary)),
              ),
            ),
            const SizedBox(height: 5),
            Wrap(
              spacing: 8,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                ?tag,
                Text(time, style: LeaType.caption().copyWith(color: c.muted)),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
