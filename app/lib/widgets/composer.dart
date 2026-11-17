import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../theme/lea_colors.dart';
import '../theme/lea_type.dart';

/// The message box under a chat or tutor thread: a `surface` box (1.5 px `line`,
/// radius 12) holding the text field and a small Send button, and an optional hint
/// under it on wide screens. Enter sends; Shift+Enter starts a new line.
class Composer extends StatelessWidget {
  const Composer({
    super.key,
    required this.controller,
    required this.placeholder,
    required this.onSend,
    required this.wide,
    this.busy = false,
    this.hint,
    this.error,
    this.above,
    this.focusNode,
  });

  final TextEditingController controller;
  final String placeholder;
  final VoidCallback onSend;
  final bool wide;

  /// A reply is on its way: Send is disabled (typing is still allowed).
  final bool busy;

  /// Shown under the box on wide screens only, as in the design.
  final String? hint;

  /// Why the last message didn't go through.
  final String? error;

  /// Shown above the box, e.g. suggestion chips.
  final Widget? above;
  final FocusNode? focusNode;

  /// The API's limit on a question or reply.
  static const maxLength = 4000;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    return Container(
      padding: wide ? const EdgeInsets.fromLTRB(22, 12, 22, 16) : const EdgeInsets.fromLTRB(12, 10, 12, 10),
      decoration: BoxDecoration(
        color: c.bg,
        border: Border(top: BorderSide(color: c.line)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        mainAxisSize: MainAxisSize.min,
        children: [
          if (above != null) ...[above!, const SizedBox(height: 10)],
          if (error != null) ...[
            Semantics(
              liveRegion: true,
              child: Text(error!, style: LeaType.small().copyWith(color: c.danger)),
            ),
            const SizedBox(height: 8),
          ],
          Container(
            padding: const EdgeInsets.fromLTRB(14, 6, 6, 6),
            decoration: BoxDecoration(
              color: c.surface,
              border: Border.all(color: c.line, width: 1.5),
              borderRadius: BorderRadius.circular(12),
            ),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Expanded(
                  child: CallbackShortcuts(
                    bindings: {
                      const SingleActivator(LogicalKeyboardKey.enter): () {
                        if (!busy) onSend();
                      },
                    },
                    child: TextField(
                      controller: controller,
                      focusNode: focusNode,
                      minLines: 1,
                      maxLines: 5,
                      maxLength: maxLength,
                      maxLengthEnforcement: MaxLengthEnforcement.enforced,
                      // No counter row: it would make the box taller than the design.
                      buildCounter: (_, {required currentLength, required isFocused, maxLength}) => null,
                      keyboardType: TextInputType.multiline,
                      textInputAction: TextInputAction.newline,
                      style: LeaType.ui(14, height: 1.45).copyWith(color: c.ink),
                      decoration: InputDecoration(
                        hintText: placeholder,
                        hintMaxLines: 1,
                        hintStyle: LeaType.ui(14).copyWith(color: c.muted, overflow: TextOverflow.ellipsis),
                        isDense: true,
                        filled: false,
                        contentPadding: const EdgeInsets.symmetric(vertical: 9),
                        border: InputBorder.none,
                        enabledBorder: InputBorder.none,
                        focusedBorder: InputBorder.none,
                      ),
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                ListenableBuilder(
                  listenable: controller,
                  builder: (context, _) => FilledButton(
                    onPressed: busy || controller.text.trim().isEmpty ? null : onSend,
                    style: FilledButton.styleFrom(
                      minimumSize: const Size(0, 36),
                      tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
                      textStyle: LeaType.ui(13.5, weight: FontWeight.w600),
                    ),
                    child: const Text('Send'),
                  ),
                ),
              ],
            ),
          ),
          if (wide && hint != null) ...[
            const SizedBox(height: 6),
            Text(hint!, style: LeaType.caption().copyWith(color: c.muted)),
          ],
        ],
      ),
    );
  }
}

/// Suggestion chips above the composer: 13 px text, 1.5 px `line` border, pill-shaped,
/// on `surface`.
class SuggestionChips extends StatelessWidget {
  const SuggestionChips({super.key, required this.suggestions, required this.onTap, this.enabled = true});

  final List<String> suggestions;
  final ValueChanged<String> onTap;
  final bool enabled;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    return Semantics(
      container: true,
      label: 'Suggestions',
      child: Wrap(
        spacing: 8,
        runSpacing: 8,
        children: [
          for (final s in suggestions)
            ActionChip(
              label: Text(s),
              onPressed: enabled ? () => onTap(s) : null,
              labelStyle: LeaType.ui(13).copyWith(color: c.ink),
              backgroundColor: c.surface,
              disabledColor: c.surface,
              side: BorderSide(color: c.line, width: 1.5),
              shape: const StadiumBorder(),
              padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 0),
              labelPadding: const EdgeInsets.symmetric(horizontal: 8),
              visualDensity: VisualDensity.compact,
              materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
            ),
        ],
      ),
    );
  }
}
