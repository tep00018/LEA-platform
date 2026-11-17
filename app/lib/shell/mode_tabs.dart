import 'package:flutter/material.dart';

import '../theme/lea_colors.dart';
import '../widgets/underline_tabs.dart';
import 'mode.dart';

/// Chat / Tutor / Quiz tabs across the top of the work area on wide screens.
class ModeTabs extends StatelessWidget {
  const ModeTabs({super.key, required this.active, required this.onSelect});

  /// Null on screens that aren't one of the tabs (Progress).
  final Mode? active;
  final ValueChanged<Mode> onSelect;

  @override
  Widget build(BuildContext context) {
    final index = active == null ? -1 : Mode.tabs.indexOf(active!);
    return UnderlineTabs(
      labels: [for (final m in Mode.tabs) m.label],
      selected: index < 0 ? null : index,
      onSelect: (i) => onSelect(Mode.tabs[i]),
      padding: const EdgeInsets.fromLTRB(22, 14, 22, 0),
      background: context.lea.bg,
      semanticLabel: 'Modes',
    );
  }
}
