import 'package:flutter/material.dart';

import '../theme/lea_colors.dart';

/// A thin progress meter: `line` track, `accent` fill (DESIGN.md: "Progress meters").
class Meter extends StatelessWidget {
  const Meter({super.key, required this.value, this.height = 6, this.color, this.semanticLabel});

  /// 0–1.
  final double value;
  final double height;
  final Color? color;
  final String? semanticLabel;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final v = value.clamp(0.0, 1.0);
    return Semantics(
      label: semanticLabel,
      value: '${(v * 100).round()}%',
      child: ClipRRect(
        borderRadius: BorderRadius.circular(99),
        child: SizedBox(
          height: height,
          child: ColoredBox(
            color: c.line,
            child: Align(
              alignment: Alignment.centerLeft,
              child: FractionallySizedBox(
                widthFactor: v,
                heightFactor: 1,
                child: DecoratedBox(
                  decoration: BoxDecoration(color: color ?? c.accent, borderRadius: BorderRadius.circular(99)),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
