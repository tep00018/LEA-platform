import 'package:flutter/widgets.dart';

import 'mode.dart';

/// The bottom-navigation icons, drawn from the mockup's 24×24 SVG paths
/// (1.8 stroke, round caps and joins): speech bubble, mortarboard, star, bar chart.
class NavIcon extends StatelessWidget {
  const NavIcon(this.mode, {super.key, this.size = 22, required this.color});

  final Mode mode;
  final double size;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return SizedBox.square(
      dimension: size,
      child: CustomPaint(painter: _NavIconPainter(mode, color)),
    );
  }
}

class _NavIconPainter extends CustomPainter {
  _NavIconPainter(this.mode, this.color);

  final Mode mode;
  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    canvas.scale(size.width / 24, size.height / 24);
    final paint = Paint()
      ..color = color
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.8
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round;
    for (final path in _paths(mode)) {
      canvas.drawPath(path, paint);
    }
  }

  static List<Path> _paths(Mode mode) => switch (mode) {
    // M4 5h16v11H9l-5 4z
    Mode.chat => [
      Path()
        ..moveTo(4, 5)
        ..lineTo(20, 5)
        ..lineTo(20, 16)
        ..lineTo(9, 16)
        ..lineTo(4, 20)
        ..close(),
    ],
    // M3 9l9-5 9 5-9 5z   M7 11v5c3 2 7 2 10 0v-5
    Mode.tutor => [
      Path()
        ..moveTo(3, 9)
        ..lineTo(12, 4)
        ..lineTo(21, 9)
        ..lineTo(12, 14)
        ..close(),
      Path()
        ..moveTo(7, 11)
        ..lineTo(7, 16)
        ..cubicTo(10, 18, 14, 18, 17, 16)
        ..lineTo(17, 11),
    ],
    // M12 3l2.6 5.5 6 .8-4.4 4.2 1.1 6L12 16.6 6.7 19.5l1.1-6L3.4 9.3l6-.8z
    Mode.quiz => [
      Path()
        ..moveTo(12, 3)
        ..lineTo(14.6, 8.5)
        ..lineTo(20.6, 9.3)
        ..lineTo(16.2, 13.5)
        ..lineTo(17.3, 19.5)
        ..lineTo(12, 16.6)
        ..lineTo(6.7, 19.5)
        ..lineTo(7.8, 13.5)
        ..lineTo(3.4, 9.3)
        ..lineTo(9.4, 8.5)
        ..close(),
    ],
    // M4 20V10 M10 20V4 M16 20v-7 M22 20H2
    Mode.progress => [
      Path()
        ..moveTo(4, 20)
        ..lineTo(4, 10)
        ..moveTo(10, 20)
        ..lineTo(10, 4)
        ..moveTo(16, 20)
        ..lineTo(16, 13)
        ..moveTo(22, 20)
        ..lineTo(2, 20),
    ],
  };

  @override
  bool shouldRepaint(_NavIconPainter old) => old.mode != mode || old.color != color;
}
