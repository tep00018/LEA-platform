import 'package:flutter/material.dart';

import '../theme/lea_colors.dart';
import '../theme/lea_type.dart';
import 'pressable.dart';

/// Text tabs over a 1 px `line` divider. Active: `ink`, 600 weight, 2.5 px `primary`
/// underline covering the divider; inactive: `muted`. Used for the mode tabs and the
/// login / create-account tabs.
class UnderlineTabs extends StatelessWidget {
  const UnderlineTabs({
    super.key,
    required this.labels,
    required this.selected,
    required this.onSelect,
    this.tabPadding = const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
    this.padding = EdgeInsets.zero,
    this.background,
    this.semanticLabel,
  });

  final List<String> labels;

  /// Index of the active tab, or null for none.
  final int? selected;
  final ValueChanged<int> onSelect;
  final EdgeInsets tabPadding;
  final EdgeInsets padding;
  final Color? background;
  final String? semanticLabel;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    return Semantics(
      container: true,
      label: semanticLabel,
      child: Container(
        width: double.infinity,
        padding: padding,
        decoration: BoxDecoration(
          color: background,
          border: Border(bottom: BorderSide(color: c.line)),
        ),
        // Shift down 1 px so the active underline covers the divider, as in the design.
        child: Transform.translate(
          offset: const Offset(0, 1),
          // Scrolls sideways when the tabs don't fit (large text on a phone).
          child: SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            clipBehavior: Clip.none,
            child: Row(
              children: [
                for (final (i, label) in labels.indexed) ...[
                  if (i > 0) const SizedBox(width: 4),
                  Pressable(
                    onTap: () => onSelect(i),
                    borderRadius: 6,
                    selected: i == selected,
                    semanticLabel: label,
                    excludeChildSemantics: true,
                    child: Container(
                      padding: tabPadding,
                      decoration: BoxDecoration(
                        border: Border(
                          bottom: BorderSide(color: i == selected ? c.primary : Colors.transparent, width: 2.5),
                        ),
                      ),
                      child: Text(
                        label,
                        style: LeaType.ui(
                          14,
                          weight: i == selected ? FontWeight.w600 : FontWeight.w400,
                          height: 1.5,
                        ).copyWith(color: i == selected ? c.ink : c.muted),
                      ),
                    ),
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}
