/// The app's four areas. Chat, Tutor and Quiz are tabs on wide screens; Progress is
/// reached from the rail there, and all four are in the bottom navigation on narrow ones.
enum Mode {
  chat('/chat', 'Chat'),
  tutor('/tutor', 'Tutor'),
  quiz('/quiz', 'Quiz'),
  progress('/progress', 'Progress');

  const Mode(this.path, this.label);

  final String path;
  final String label;

  static const tabs = [chat, tutor, quiz];

  /// The mode for a location such as `/quiz` or `/quiz/results`.
  static Mode? fromLocation(String location) {
    for (final m in values) {
      if (location == m.path || location.startsWith('${m.path}/')) return m;
    }
    return null;
  }
}
