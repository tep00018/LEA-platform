import 'package:flutter/material.dart';

import '../theme/lea_colors.dart';
import '../theme/lea_type.dart';

/// "★ Week 1 complete. Week 2 · Machine Learning Basics is now open." on `accent-soft`.
class WeekCompleteBanner extends StatelessWidget {
  const WeekCompleteBanner({super.key, required this.week, required this.nextWeek, this.nextTopic});

  final int week;
  final int nextWeek;
  final String? nextTopic;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final next = nextTopic == null ? 'Week $nextWeek' : 'Week $nextWeek · $nextTopic';
    return Semantics(
      liveRegion: true,
      label: 'Week $week complete. $next is now open.',
      excludeSemantics: true,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        decoration: BoxDecoration(color: c.accentSoft, borderRadius: BorderRadius.circular(12)),
        child: Row(
          children: [
            Icon(Icons.star_rounded, size: 20, color: c.ink),
            const SizedBox(width: 12),
            Expanded(
              child: Text.rich(
                TextSpan(
                  style: LeaType.ui(14, height: 1.45).copyWith(color: c.ink),
                  children: [
                    TextSpan(
                      text: 'Week $week complete. ',
                      style: LeaType.heading(16, weight: FontWeight.w700).copyWith(color: c.ink),
                    ),
                    TextSpan(text: '$next is now open.'),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
