import 'package:flutter/material.dart';

import '../api/api_error.dart';
import '../theme/lea_colors.dart';
import '../theme/lea_type.dart';

/// The Teacher area's small building blocks (docs/teacher/design/DESIGN.md).

/// The header band: an uppercase kicker, the title, one line of context, and actions.
class TeachHeader extends StatelessWidget {
  const TeachHeader({super.key, required this.kicker, required this.title, this.subtitle, this.actions = const []});

  final String kicker;
  final String title;
  final String? subtitle;
  final List<Widget> actions;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final wide = MediaQuery.sizeOf(context).width >= 720;
    final heading = Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(kicker.toUpperCase(), style: LeaType.label(11.5).copyWith(color: c.muted)),
        const SizedBox(height: 3),
        Semantics(
          header: true,
          child: Text(
            title,
            style: LeaType.screenTitle(wide: wide).copyWith(color: c.ink),
          ),
        ),
        if (subtitle != null) ...[
          const SizedBox(height: 2),
          Text(subtitle!, style: LeaType.ui(13).copyWith(color: c.muted)),
        ],
      ],
    );
    return Container(
      padding: EdgeInsets.fromLTRB(wide ? 24 : 16, 16, wide ? 24 : 16, 14),
      decoration: BoxDecoration(
        color: c.bg,
        border: Border(bottom: BorderSide(color: c.line)),
      ),
      child: wide
          ? Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Expanded(child: heading),
                const SizedBox(width: 16),
                Wrap(spacing: 8, runSpacing: 8, children: actions),
              ],
            )
          : Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                heading,
                if (actions.isNotEmpty) ...[
                  const SizedBox(height: 10),
                  Wrap(spacing: 8, runSpacing: 8, children: actions),
                ],
              ],
            ),
    );
  }
}

/// A `surface` card with a `line` border and 12 px corners.
class TeachCard extends StatelessWidget {
  const TeachCard({super.key, required this.child, this.padding = const EdgeInsets.fromLTRB(16, 14, 16, 14)});

  final Widget child;
  final EdgeInsetsGeometry padding;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    return Container(
      padding: padding,
      decoration: BoxDecoration(
        color: c.surface,
        border: Border.all(color: c.line),
        borderRadius: BorderRadius.circular(12),
      ),
      child: child,
    );
  }
}

enum PillTone { neutral, ok, bad, warn, outline, dashed }

/// A small rounded label. Status always has a word, never just a colour.
class TeachPill extends StatelessWidget {
  const TeachPill(this.label, {super.key, this.tone = PillTone.neutral});

  final String label;
  final PillTone tone;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final (Color? bg, Color fg, Color? border) = switch (tone) {
      PillTone.neutral => (c.surface2, c.ink, null),
      PillTone.ok => (c.successSoft, c.success, null),
      PillTone.bad => (c.dangerSoft, c.danger, null),
      PillTone.warn => (c.accentSoft, c.ink, null),
      PillTone.outline => (null, c.muted, c.line),
      PillTone.dashed => (null, c.muted, c.muted),
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 2),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(99),
        border: border == null ? null : Border.all(color: border),
      ),
      child: Text(label, style: LeaType.ui(11.5).copyWith(color: fg), maxLines: 1),
    );
  }
}

/// A big number with a caption ("42 · students").
class TeachStat extends StatelessWidget {
  const TeachStat({super.key, required this.value, required this.label});

  final String value;
  final String label;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    return Semantics(
      label: '$value $label',
      excludeSemantics: true,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            value,
            style: LeaType.heading(
              26,
              weight: const FontWeight(750),
              height: 1.1,
            ).copyWith(color: c.ink, fontFeatures: const [FontFeature.tabularFigures()]),
          ),
          Text(label, style: LeaType.ui(12).copyWith(color: c.muted)),
        ],
      ),
    );
  }
}

enum BannerTone { info, soft, bad, ok }

/// A one-line notice inside a card or screen.
class TeachBanner extends StatelessWidget {
  const TeachBanner({super.key, required this.child, this.tone = BannerTone.info});

  final Widget child;
  final BannerTone tone;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final bg = switch (tone) {
      BannerTone.info => c.surface2,
      BannerTone.soft => c.accentSoft,
      BannerTone.bad => c.dangerSoft,
      BannerTone.ok => c.successSoft,
    };
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(10)),
      child: DefaultTextStyle.merge(
        style: LeaType.ui(13).copyWith(color: c.ink),
        child: child,
      ),
    );
  }
}

/// A danger-outlined button ("Cancel after this file", "Discard draft").
class DangerButton extends StatelessWidget {
  const DangerButton({super.key, required this.label, required this.onPressed});

  final String label;
  final VoidCallback? onPressed;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    return OutlinedButton(
      onPressed: onPressed,
      style: OutlinedButton.styleFrom(
        foregroundColor: c.danger,
        side: BorderSide(color: c.danger, width: 1.5),
        minimumSize: const Size(0, 42),
        padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 10),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(9)),
        textStyle: LeaType.ui(14, weight: FontWeight.w600),
      ),
      child: Text(label),
    );
  }
}

/// A load failure with a way to try again.
class TeachError extends StatelessWidget {
  const TeachError({super.key, required this.error, required this.onRetry});

  final Object error;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final message = error is ApiError ? (error as ApiError).message : "Something went wrong. Please try again.";
    return TeachBanner(
      tone: BannerTone.bad,
      child: Row(
        children: [
          Expanded(child: Text(message)),
          TextButton(
            onPressed: onRetry,
            child: Text(
              'Try again',
              style: LeaType.ui(13, weight: FontWeight.w600).copyWith(color: c.ink),
            ),
          ),
        ],
      ),
    );
  }
}

/// On a phone the Teacher area is read-only (DESIGN.md, "Where it lives").
class DesktopOnlyNote extends StatelessWidget {
  const DesktopOnlyNote({super.key});

  @override
  Widget build(BuildContext context) =>
      const TeachBanner(child: Text('Open LEA on a computer to edit. On a phone you can follow progress.'));
}

/// Mono text for IDs (never editable).
class IdText extends StatelessWidget {
  const IdText(this.id, {super.key});

  final String id;

  @override
  Widget build(BuildContext context) => Text(id, style: LeaType.mono(11.5).copyWith(color: context.lea.muted));
}

/// A compact dropdown chip for a screen header (a week, a date range, who is shown).
class TeachFilter<T> extends StatelessWidget {
  const TeachFilter({
    super.key,
    required this.label,
    required this.value,
    required this.options,
    required this.onChanged,
  });

  final String label;
  final T value;
  final List<(T, String)> options;
  final ValueChanged<T> onChanged;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final current = options.where((o) => o.$1 == value).firstOrNull?.$2 ?? options.first.$2;
    return PopupMenuButton<int>(
      tooltip: label,
      onSelected: (i) => onChanged(options[i].$1),
      itemBuilder: (_) => [
        for (final (i, o) in options.indexed) CheckedPopupMenuItem(value: i, checked: o.$1 == value, child: Text(o.$2)),
      ],
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(
          color: c.surface,
          border: Border.all(color: c.line),
          borderRadius: BorderRadius.circular(99),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(current, style: LeaType.ui(12.5).copyWith(color: c.ink)),
            const SizedBox(width: 4),
            Icon(Icons.arrow_drop_down, size: 16, color: c.muted),
          ],
        ),
      ),
    );
  }
}
