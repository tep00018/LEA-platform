import 'package:flutter/material.dart';

import '../theme/lea_colors.dart';

/// LEA's round avatar with its 2 px ring (`accent` in the app, `chalk` on the login panel).
class LeaAvatar extends StatelessWidget {
  const LeaAvatar({super.key, required this.size, this.ring = true, this.ringColor, this.semanticLabel});

  final double size;
  final bool ring;
  final Color? ringColor;

  /// Null when the avatar is decoration next to LEA's name or message.
  final String? semanticLabel;

  static const asset = 'assets/images/lea_avatar.png';

  @override
  Widget build(BuildContext context) {
    final image = ClipOval(
      child: Image.asset(
        asset,
        width: size,
        height: size,
        fit: BoxFit.cover,
        semanticLabel: semanticLabel,
        excludeFromSemantics: semanticLabel == null,
        filterQuality: FilterQuality.medium,
      ),
    );
    if (!ring) return SizedBox.square(dimension: size, child: image);
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        border: Border.all(color: ringColor ?? context.lea.accent, width: 2),
      ),
      child: image,
    );
  }
}

/// A round avatar with the student's initial on `primary`.
class InitialAvatar extends StatelessWidget {
  const InitialAvatar({super.key, required this.initial, this.size = 32});

  final String initial;
  final double size;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    return ExcludeSemantics(
      child: Container(
        width: size,
        height: size,
        alignment: Alignment.center,
        decoration: BoxDecoration(color: c.primary, shape: BoxShape.circle),
        child: Text(
          initial,
          style: TextStyle(
            color: c.onPrimary,
            fontSize: size * 0.42,
            fontWeight: FontWeight.w600,
            fontVariations: const [FontVariation.weight(600)],
          ),
        ),
      ),
    );
  }
}
