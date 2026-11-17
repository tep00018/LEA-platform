import 'dart:async';

import 'package:flutter/material.dart';

import '../theme/lea_colors.dart';

/// The `accent` block that blinks after a reply while it streams (8×15, radius 2, one
/// blink a second). Holds still when the system asks for reduced motion.
class StreamingCursor extends StatefulWidget {
  const StreamingCursor({super.key});

  @override
  State<StreamingCursor> createState() => _StreamingCursorState();
}

class _StreamingCursorState extends State<StreamingCursor> {
  Timer? _timer;
  bool _visible = true;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _timer?.cancel();
    _visible = true;
    if (!MediaQuery.disableAnimationsOf(context)) {
      _timer = Timer.periodic(const Duration(milliseconds: 500), (_) => setState(() => _visible = !_visible));
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return ExcludeSemantics(
      child: Padding(
        padding: const EdgeInsets.only(left: 2),
        child: Opacity(
          opacity: _visible ? 1 : 0,
          child: Container(
            width: 8,
            height: 15,
            decoration: BoxDecoration(color: context.lea.accent, borderRadius: BorderRadius.circular(2)),
          ),
        ),
      ),
    );
  }
}
