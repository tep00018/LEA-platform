import 'package:flutter/material.dart';

import '../theme/lea_colors.dart';
import '../theme/lea_type.dart';

/// A labelled input as the design draws it: label above (13 px, 500), then a field with a
/// 1.5 px `line` border, radius 10, on `surface`. Focused: `primary` border plus a soft
/// 3 px `primary` glow.
class LeaTextField extends StatefulWidget {
  const LeaTextField({
    super.key,
    required this.label,
    required this.controller,
    this.obscureText = false,
    this.autofillHints,
    this.textInputAction,
    this.onSubmitted,
    this.keyboardType,
    this.helper,
    this.autofocus = false,
    this.enabled = true,
  });

  final String label;
  final TextEditingController controller;
  final bool obscureText;
  final Iterable<String>? autofillHints;
  final TextInputAction? textInputAction;
  final ValueChanged<String>? onSubmitted;
  final TextInputType? keyboardType;

  /// A short hint under the field ("At least 6 characters").
  final String? helper;
  final bool autofocus;
  final bool enabled;

  @override
  State<LeaTextField> createState() => _LeaTextFieldState();
}

class _LeaTextFieldState extends State<LeaTextField> {
  final _focus = FocusNode();

  @override
  void initState() {
    super.initState();
    _focus.addListener(() => setState(() {}));
  }

  @override
  void dispose() {
    _focus.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final focused = _focus.hasFocus;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        // The field itself carries the label for screen readers (see Semantics below).
        ExcludeSemantics(
          child: Text(
            widget.label,
            style: LeaType.ui(13, weight: FontWeight.w500).copyWith(color: c.ink),
          ),
        ),
        const SizedBox(height: 6),
        AnimatedContainer(
          duration: MediaQuery.disableAnimationsOf(context) ? Duration.zero : const Duration(milliseconds: 120),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(10),
            boxShadow: [if (focused) BoxShadow(color: c.primary.withValues(alpha: 0.22), spreadRadius: 3)],
          ),
          child: Semantics(
            label: widget.label,
            child: TextField(
              controller: widget.controller,
              focusNode: _focus,
              enabled: widget.enabled,
              autofocus: widget.autofocus,
              obscureText: widget.obscureText,
              obscuringCharacter: '•',
              autofillHints: widget.autofillHints,
              textInputAction: widget.textInputAction,
              keyboardType: widget.keyboardType,
              onSubmitted: widget.onSubmitted,
              autocorrect: false,
              enableSuggestions: !widget.obscureText,
              style: LeaType.ui(14, height: 1.4).copyWith(color: c.ink, letterSpacing: widget.obscureText ? 2.8 : null),
              decoration: InputDecoration(
                isDense: true,
                contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 11),
                filled: true,
                fillColor: c.surface,
              ),
            ),
          ),
        ),
        if (widget.helper != null) ...[
          const SizedBox(height: 4),
          Text(widget.helper!, style: LeaType.caption().copyWith(color: c.muted)),
        ],
      ],
    );
  }
}
