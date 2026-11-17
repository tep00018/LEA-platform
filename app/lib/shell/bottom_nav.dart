import 'package:flutter/material.dart';

import '../theme/lea_colors.dart';
import '../theme/lea_type.dart';
import '../widgets/pressable.dart';
import 'mode.dart';
import 'nav_icons.dart';

/// Narrow-screen bottom navigation: Chat, Tutor, Quiz, Progress. The active item gets a
/// `surface-2` pill behind its icon.
class BottomNav extends StatelessWidget {
  const BottomNav({super.key, required this.active, required this.onSelect});

  final Mode? active;
  final ValueChanged<Mode> onSelect;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    return Container(
      decoration: BoxDecoration(
        color: c.surface,
        border: Border(top: BorderSide(color: c.line)),
      ),
      child: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(4, 8, 4, 12),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.spaceAround,
            children: [
              for (final mode in Mode.values) _NavItem(mode: mode, active: mode == active, onTap: () => onSelect(mode)),
            ],
          ),
        ),
      ),
    );
  }
}

class _NavItem extends StatelessWidget {
  const _NavItem({required this.mode, required this.active, required this.onTap});

  final Mode mode;
  final bool active;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    return Pressable(
      onTap: onTap,
      selected: active,
      semanticLabel: mode.label,
      excludeChildSemantics: true,
      borderRadius: 12,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 3),
            decoration: BoxDecoration(color: active ? c.surface2 : null, borderRadius: BorderRadius.circular(99)),
            child: NavIcon(mode, color: active ? c.primary : c.muted),
          ),
          const SizedBox(height: 3),
          Text(
            mode.label,
            style: LeaType.ui(
              11.5,
              weight: active ? FontWeight.w600 : FontWeight.w400,
            ).copyWith(color: active ? c.ink : c.muted),
          ),
        ],
      ),
    );
  }
}
