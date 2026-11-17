import 'package:flutter/material.dart';

import '../theme/lea_colors.dart';
import '../theme/lea_type.dart';
import '../widgets/lea_avatar.dart';
import '../widgets/pressable.dart';
import '../widgets/skeleton.dart';
import 'shell_info.dart';

/// The narrow-screen top bar: avatar, mode title, course · week line, mastered chip.
/// Tapping it opens the course and week sheet.
class TopBar extends StatelessWidget {
  const TopBar({super.key, required this.title, required this.info, required this.onOpenCourse});

  final String title;

  /// Null while the course is loading.
  final ShellInfo? info;
  final VoidCallback onOpenCourse;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final info = this.info;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      decoration: BoxDecoration(
        color: c.surface,
        border: Border(bottom: BorderSide(color: c.line)),
      ),
      child: Pressable(
        onTap: onOpenCourse,
        borderRadius: 8,
        semanticLabel: info == null
            ? '$title. Course and week'
            : '$title. ${info.subtitle}. ${info.masteredCount} of ${info.total} objectives mastered. '
                  'Change course or week',
        excludeChildSemantics: true,
        child: Row(
          children: [
            const LeaAvatar(size: 34),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    title,
                    style: LeaType.ui(14, weight: FontWeight.w600, height: 1.5).copyWith(color: c.ink),
                  ),
                  if (info == null)
                    const Padding(
                      padding: EdgeInsets.only(top: 3, bottom: 3),
                      child: SkeletonBox(width: 180, height: 12),
                    )
                  else
                    Text(
                      info.subtitle,
                      maxLines: 1,
                      softWrap: false,
                      overflow: TextOverflow.ellipsis,
                      style: LeaType.ui(12, height: 1.5).copyWith(color: c.muted),
                    ),
                ],
              ),
            ),
            const SizedBox(width: 10),
            if (info == null)
              const SkeletonBox(width: 46, height: 24, radius: 99)
            else
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 4),
                decoration: BoxDecoration(color: c.surface2, borderRadius: BorderRadius.circular(99)),
                child: Text(
                  info.count,
                  style: LeaType.ui(12, weight: FontWeight.w600).copyWith(color: c.ink, fontFeatures: LeaType.tabular),
                ),
              ),
          ],
        ),
      ),
    );
  }
}
