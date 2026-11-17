import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/api_error.dart';
import '../connectivity.dart';
import '../theme/lea_colors.dart';
import '../theme/lea_type.dart';

/// "Can't reach LEA. Check that the LEA server is running." while the API is unreachable
/// (DESIGN.md, "States every screen needs"). Takes no space otherwise.
class OfflineBanner extends ConsumerWidget {
  const OfflineBanner({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (ref.watch(connectivityProvider)) return const SizedBox.shrink();
    final c = context.lea;
    return Semantics(
      liveRegion: true,
      container: true,
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
        decoration: BoxDecoration(
          color: c.dangerSoft,
          border: Border(bottom: BorderSide(color: c.danger)),
        ),
        child: Row(
          children: [
            ExcludeSemantics(child: Icon(Icons.wifi_off_rounded, size: 18, color: c.danger)),
            const SizedBox(width: 10),
            Expanded(
              child: Text(ApiError.unreachableDetail, style: LeaType.small().copyWith(color: c.ink)),
            ),
            const SizedBox(width: 10),
            TextButton(
              onPressed: () => ref.read(connectivityProvider.notifier).check(),
              style: TextButton.styleFrom(
                foregroundColor: c.ink,
                textStyle: LeaType.ui(13, weight: FontWeight.w600),
                visualDensity: VisualDensity.compact,
              ),
              child: const Text('Try again'),
            ),
          ],
        ),
      ),
    );
  }
}
