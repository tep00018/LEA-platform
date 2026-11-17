import 'package:flutter/material.dart';

import '../theme/lea_colors.dart';

/// A loading placeholder block in `surface-2` (DESIGN.md: skeletons, not spinners).
/// Static, so it needs no reduced-motion handling.
class SkeletonBox extends StatelessWidget {
  const SkeletonBox({super.key, this.width, required this.height, this.radius = 6});

  final double? width;
  final double height;
  final double radius;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: width,
      height: height,
      decoration: BoxDecoration(color: context.lea.surface2, borderRadius: BorderRadius.circular(radius)),
    );
  }
}
