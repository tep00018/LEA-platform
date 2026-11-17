import 'package:flutter/material.dart';

import '../../theme/lea_colors.dart';
import '../../theme/lea_type.dart';
import '../../widgets/lea_avatar.dart';

/// The green `board` panel of the login screen: avatar, "LEA", the tagline set large with
/// a hand-drawn `chalk` underline under "Study Up.", and (wide only) a one-line description.
/// Secondary text on the board is at 92% (the mockup's 80% measured 4.1:1, under AA).
class BoardPanel extends StatelessWidget {
  const BoardPanel({super.key, required this.wide, required this.appWidth});

  final bool wide;

  /// The tagline scales with the app's width on wide screens, as in the mockup.
  final double appWidth;

  static const description =
      "An AI tutor that adapts to how you're doing: chat about your course, work through each "
      'week with a tutor, and check yourself with quizzes.';

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final onBoard = c.onBoard;
    final headingSize = wide ? (appWidth * 0.042).clamp(30.0, 46.0) : 30.0;
    final heading = LeaType.heading(
      headingSize,
      weight: FontWeight.w800,
      height: 1.18,
      letterSpacing: -0.015 * headingSize,
    ).copyWith(color: onBoard);

    final top = Row(
      children: [
        LeaAvatar(size: 56, ringColor: c.chalk),
        const SizedBox(width: 12),
        Flexible(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'LEA',
                style: LeaType.heading(26, weight: FontWeight.w800, height: 1).copyWith(color: onBoard),
              ),
              const SizedBox(height: 4),
              Text(
                'Learning Engagement Assistant',
                style: LeaType.ui(12.5).copyWith(color: onBoard.withValues(alpha: 0.92)),
              ),
            ],
          ),
        ),
      ],
    );

    final tagline = Semantics(
      header: true,
      label: 'Slide In. Study Up. Show Off.',
      excludeSemantics: true,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Slide In.', style: heading),
          Stack(
            clipBehavior: Clip.none,
            children: [
              Text('Study Up.', style: heading),
              Positioned(
                left: 0,
                right: 0,
                bottom: -3,
                height: 12,
                child: CustomPaint(painter: ChalkUnderlinePainter(c.chalk)),
              ),
            ],
          ),
          Text('Show Off.', style: heading),
        ],
      ),
    );

    return Container(
      color: c.board,
      child: Stack(
        children: [
          // Two faint light pools, like chalk dust on a board.
          const Positioned.fill(child: IgnorePointer(child: _ChalkDust())),
          Padding(
            padding: wide
                ? const EdgeInsets.symmetric(horizontal: 44, vertical: 40)
                : const EdgeInsets.fromLTRB(20, 24, 20, 24),
            child: wide
                ? Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      top,
                      tagline,
                      ConstrainedBox(
                        constraints: const BoxConstraints(maxWidth: 310),
                        child: Text(
                          description,
                          style: LeaType.ui(12.5, height: 1.5).copyWith(color: onBoard.withValues(alpha: 0.92)),
                        ),
                      ),
                    ],
                  )
                : Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [top, const SizedBox(height: 20), tagline],
                  ),
          ),
        ],
      ),
    );
  }
}

class _ChalkDust extends StatelessWidget {
  const _ChalkDust();

  @override
  Widget build(BuildContext context) {
    return const Stack(
      fit: StackFit.expand,
      children: [
        DecoratedBox(
          decoration: BoxDecoration(
            gradient: RadialGradient(
              center: Alignment(-0.6, 1.2),
              radius: 1.1,
              colors: [Color(0x12FFFFFF), Color(0x00FFFFFF)],
              stops: [0, 0.6],
            ),
          ),
        ),
        DecoratedBox(
          decoration: BoxDecoration(
            gradient: RadialGradient(
              center: Alignment(0.8, -1.2),
              radius: 0.7,
              colors: [Color(0x0FFFFFFF), Color(0x00FFFFFF)],
              stops: [0, 0.6],
            ),
          ),
        ),
      ],
    );
  }
}

/// The hand-drawn underline from the mockup's SVG
/// (`M2 9 C 40 3, 80 12, 120 6 S 180 4, 198 8` in a 200×14 box), stretched to 104% of
/// the word's width and starting 2% before it.
class ChalkUnderlinePainter extends CustomPainter {
  ChalkUnderlinePainter(this.color);

  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final width = size.width * 1.04;
    final left = -size.width * 0.02;
    double x(double v) => left + v / 200 * width;
    double y(double v) => v / 14 * size.height;
    final path = Path()
      ..moveTo(x(2), y(9))
      ..cubicTo(x(40), y(3), x(80), y(12), x(120), y(6))
      // "S 180 4, 198 8": the first control point mirrors (80, 12) about (120, 6).
      ..cubicTo(x(160), y(0), x(180), y(4), x(198), y(8));
    canvas.drawPath(
      path,
      Paint()
        ..color = color
        ..style = PaintingStyle.stroke
        ..strokeWidth = 3
        ..strokeCap = StrokeCap.round,
    );
  }

  @override
  bool shouldRepaint(ChalkUnderlinePainter old) => old.color != color;
}
