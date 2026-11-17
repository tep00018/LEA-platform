/// Student analytics (`/teach/courses/{code}/analytics...`). Figures from fewer than 5
/// students arrive as null and are shown as "< 5" or "Not enough students yet".
library;

double? _d(Object? v) => (v as num?)?.toDouble();

int? _i(Object? v) => (v as num?)?.toInt();

List<Map<String, dynamic>> _list(Object? v) => [for (final e in (v as List?) ?? const []) e as Map<String, dynamic>];

/// Band labels, in the summary's order.
const analyticsBands = [
  ('struggling', 'struggling'),
  ('developing', 'developing'),
  ('mastered', 'mastered'),
  ('insufficient', 'not enough evidence'),
];

String bandLabel(String band) => switch (band) {
  'mastered' => 'Mastered',
  'developing' => 'Developing',
  'struggling' => 'Struggling',
  _ => 'Not enough evidence',
};

/// "0.38", or "—" when withheld.
String ratio(double? v) => v == null ? '—' : v.toStringAsFixed(2);

/// "31", or "< 5" when withheld.
String studentCount(int? n) => n == null ? '< 5' : '$n';

String percent(double v) => '${(v * 100).round()}%';

class CurvePoint {
  const CurvePoint({required this.opportunity, required this.students, this.errorRate});

  final int opportunity;
  final int students;
  final double? errorRate;

  static const fields = ['opportunity', 'students', 'error_rate'];

  factory CurvePoint.fromJson(Map<String, dynamic> json) => CurvePoint(
    opportunity: _i(json['opportunity']) ?? 0,
    students: _i(json['students']) ?? 0,
    errorRate: _d(json['error_rate']),
  );
}

class Attention {
  const Attention({this.score, this.level, this.driver, this.factors = const {}});

  final double? score;
  final String? level;
  final String? driver;
  final Map<String, double> factors;

  static const fields = ['score', 'level', 'driver', 'factors'];

  factory Attention.fromJson(Map<String, dynamic>? json) => Attention(
    score: _d(json?['score']),
    level: json?['level'] as String?,
    driver: json?['driver'] as String?,
    factors: {
      for (final MapEntry(:key, :value) in ((json?['factors'] as Map<String, dynamic>?) ?? const {}).entries)
        key: (value as num).toDouble(),
    },
  );

  /// "High: a flat learning curve", "Low", or null when there is not enough evidence.
  String? get label {
    if (level == null) return null;
    final l = '${level![0].toUpperCase()}${level!.substring(1)}';
    return level == 'low' || driver == null ? l : '$l: $driver';
  }
}

class ObjectiveStats {
  const ObjectiveStats({
    required this.goId,
    required this.skillName,
    required this.week,
    required this.loId,
    required this.threshold,
    required this.band,
    required this.suppressed,
    required this.attention,
    this.students,
    this.gradedAttempts,
    this.firstAttemptAccuracy,
    this.attemptsToMaster,
    this.curveVerdict,
  });

  final String goId;
  final String skillName;
  final int week;
  final String loId;
  final double threshold;
  final String band;
  final bool suppressed;
  final Attention attention;
  final int? students;
  final int? gradedAttempts;
  final double? firstAttemptAccuracy;
  final double? attemptsToMaster;
  final String? curveVerdict;

  static const fields = [
    'go_id',
    'skill_name',
    'week',
    'lo_id',
    'threshold',
    'band',
    'students',
    'suppressed',
    'graded_attempts',
    'first_attempt_accuracy',
    'attempts_to_master',
    'curve_verdict',
    'attention',
  ];

  factory ObjectiveStats.fromJson(Map<String, dynamic> json) => ObjectiveStats(
    goId: json['go_id'] as String,
    skillName: (json['skill_name'] as String?) ?? '',
    week: _i(json['week']) ?? 0,
    loId: (json['lo_id'] as String?) ?? '',
    threshold: _d(json['threshold']) ?? 0,
    band: (json['band'] as String?) ?? 'insufficient',
    suppressed: (json['suppressed'] as bool?) ?? true,
    attention: Attention.fromJson(json['attention'] as Map<String, dynamic>?),
    students: _i(json['students']),
    gradedAttempts: _i(json['graded_attempts']),
    firstAttemptAccuracy: _d(json['first_attempt_accuracy']),
    attemptsToMaster: _d(json['attempts_to_master']),
    curveVerdict: json['curve_verdict'] as String?,
  );
}

class Usage {
  const Usage({required this.suppressed, this.activeStudents, this.sessions, this.chatQuestions, this.hours});

  final bool suppressed;
  final int? activeStudents;
  final int? sessions;
  final int? chatQuestions;
  final double? hours;

  static const fields = ['active_students', 'sessions', 'chat_questions', 'hours', 'suppressed'];

  factory Usage.fromJson(Map<String, dynamic>? json) => Usage(
    suppressed: (json?['suppressed'] as bool?) ?? true,
    activeStudents: _i(json?['active_students']),
    sessions: _i(json?['sessions']),
    chatQuestions: _i(json?['chat_questions']),
    hours: _d(json?['hours']),
  );
}

class AnalyticsOverview {
  const AnalyticsOverview({
    required this.course,
    required this.kind,
    required this.minStudents,
    required this.suppressed,
    required this.bands,
    required this.objectives,
    required this.usage,
    required this.kcVersion,
    this.week,
    this.students,
  });

  final String course;
  final String kind;
  final int minStudents;
  final bool suppressed;
  final Map<String, int> bands;
  final List<ObjectiveStats> objectives;
  final Usage usage;
  final int kcVersion;
  final int? week;
  final int? students;

  static const fields = [
    'course',
    'kind',
    'week',
    'min_students',
    'students',
    'suppressed',
    'bands',
    'objectives',
    'usage',
    'kc_version',
  ];

  factory AnalyticsOverview.fromJson(Map<String, dynamic> json) => AnalyticsOverview(
    course: (json['course'] as String?) ?? '',
    kind: (json['kind'] as String?) ?? 'real',
    minStudents: _i(json['min_students']) ?? 5,
    suppressed: (json['suppressed'] as bool?) ?? true,
    bands: {
      for (final MapEntry(:key, :value) in ((json['bands'] as Map<String, dynamic>?) ?? const {}).entries)
        key: (value as num).toInt(),
    },
    objectives: [for (final o in _list(json['objectives'])) ObjectiveStats.fromJson(o)],
    usage: Usage.fromJson(json['usage'] as Map<String, dynamic>?),
    kcVersion: _i(json['kc_version']) ?? 0,
    week: _i(json['week']),
    students: _i(json['students']),
  );
}

class WrongAnswer {
  const WrongAnswer({required this.answer, required this.share, required this.count});

  final String answer;
  final double share;
  final int count;

  static const fields = ['answer', 'share', 'count'];

  factory WrongAnswer.fromJson(Map<String, dynamic> json) => WrongAnswer(
    answer: (json['answer'] as String?) ?? '',
    share: _d(json['share']) ?? 0,
    count: _i(json['count']) ?? 0,
  );
}

class WrongAnswers {
  const WrongAnswers({required this.suppressed, required this.answers, this.students});

  final bool suppressed;
  final List<WrongAnswer> answers;
  final int? students;

  static const fields = ['suppressed', 'students', 'answers'];

  factory WrongAnswers.fromJson(Map<String, dynamic>? json) => WrongAnswers(
    suppressed: (json?['suppressed'] as bool?) ?? true,
    answers: [for (final a in _list(json?['answers'])) WrongAnswer.fromJson(a)],
    students: _i(json?['students']),
  );
}

class Struggle {
  const Struggle({required this.suppressed, this.streakStudents, this.videoStudents, this.sessionsLeftStuck});

  final bool suppressed;
  final int? streakStudents;
  final int? videoStudents;
  final int? sessionsLeftStuck;

  static const fields = ['streak_students', 'video_students', 'sessions_left_stuck', 'suppressed'];

  factory Struggle.fromJson(Map<String, dynamic>? json) => Struggle(
    suppressed: (json?['suppressed'] as bool?) ?? true,
    streakStudents: _i(json?['streak_students']),
    videoStudents: _i(json?['video_students']),
    sessionsLeftStuck: _i(json?['sessions_left_stuck']),
  );
}

class ChatTopic {
  const ChatTopic({
    required this.label,
    required this.students,
    required this.questions,
    required this.paraphrases,
    this.goId,
  });

  final String label;
  final int students;
  final int questions;
  final List<String> paraphrases;
  final String? goId;

  static const fields = ['label', 'go_id', 'students', 'questions', 'paraphrases'];

  factory ChatTopic.fromJson(Map<String, dynamic> json) => ChatTopic(
    label: (json['label'] as String?) ?? '',
    students: _i(json['students']) ?? 0,
    questions: _i(json['questions']) ?? 0,
    paraphrases: [for (final p in (json['paraphrases'] as List?) ?? const []) p as String],
    goId: json['go_id'] as String?,
  );
}

class ObjectiveDetail {
  const ObjectiveDetail({
    required this.stats,
    required this.description,
    required this.curve,
    required this.courseCurve,
    required this.wrongAnswers,
    required this.struggle,
    required this.chatTopics,
    this.suggestion,
  });

  final ObjectiveStats stats;
  final String description;
  final List<CurvePoint> curve;
  final List<CurvePoint> courseCurve;
  final WrongAnswers wrongAnswers;
  final Struggle struggle;
  final List<ChatTopic> chatTopics;
  final String? suggestion;

  static const fields = [
    'go_id',
    'skill_name',
    'description',
    'kind',
    'week',
    'threshold',
    'band',
    'students',
    'suppressed',
    'graded_attempts',
    'first_attempt_accuracy',
    'attempts_to_master',
    'curve',
    'course_curve',
    'curve_verdict',
    'attention',
    'wrong_answers',
    'struggle',
    'chat_topics',
    'suggestion',
  ];

  factory ObjectiveDetail.fromJson(Map<String, dynamic> json) => ObjectiveDetail(
    stats: ObjectiveStats.fromJson({'lo_id': '', ...json}),
    description: (json['description'] as String?) ?? '',
    curve: [for (final p in _list(json['curve'])) CurvePoint.fromJson(p)],
    courseCurve: [for (final p in _list(json['course_curve'])) CurvePoint.fromJson(p)],
    wrongAnswers: WrongAnswers.fromJson(json['wrong_answers'] as Map<String, dynamic>?),
    struggle: Struggle.fromJson(json['struggle'] as Map<String, dynamic>?),
    chatTopics: [for (final t in _list(json['chat_topics'])) ChatTopic.fromJson(t)],
    suggestion: json['suggestion'] as String?,
  );

  /// One sentence reading the curve, e.g. "Flat at about 60%: practice isn't reducing errors."
  String? get curveReading {
    final shown = [
      for (final p in curve)
        if (p.errorRate != null) p.errorRate!,
    ];
    if (shown.isEmpty) return null;
    final mean = shown.reduce((a, b) => a + b) / shown.length;
    return switch (stats.curveVerdict) {
      'flat' => "Flat at about ${percent(mean)}: practice isn't reducing errors.",
      'rising' =>
        'Rising: errors grow with practice, which often means later questions are harder or the '
            'objective mixes two skills.',
      'declining' => 'Falling from ${percent(shown.first)} to ${percent(shown.last)}: practice is working.',
      _ => 'Too few practice opportunities yet to read a trend.',
    };
  }
}

class ChatTopicsResult {
  const ChatTopicsResult({
    required this.ranAt,
    required this.model,
    required this.questions,
    required this.topics,
    this.agreement,
  });

  final String ranAt;
  final String model;
  final int questions;
  final List<ChatTopic> topics;
  final double? agreement;

  static const fields = ['ran_at', 'kind', 'model', 'questions', 'agreement', 'topics'];

  factory ChatTopicsResult.fromJson(Map<String, dynamic> json) => ChatTopicsResult(
    ranAt: (json['ran_at'] as String?) ?? '',
    model: (json['model'] as String?) ?? '',
    questions: _i(json['questions']) ?? 0,
    topics: [for (final t in _list(json['topics'])) ChatTopic.fromJson(t)],
    agreement: _d(json['agreement']),
  );

  String get date => ranAt.length >= 10 ? ranAt.substring(0, 10) : ranAt;
}

class ChatTopicsStatus {
  const ChatTopicsStatus({
    required this.questions,
    required this.usd,
    required this.canRun,
    this.result,
    this.students,
  });

  final int questions;
  final double usd;
  final bool canRun;
  final ChatTopicsResult? result;
  final int? students;

  static const fields = ['result', 'questions', 'students', 'usd', 'can_run'];

  factory ChatTopicsStatus.fromJson(Map<String, dynamic> json) => ChatTopicsStatus(
    questions: _i(json['questions']) ?? 0,
    usd: _d(json['usd']) ?? 0,
    canRun: (json['can_run'] as bool?) ?? false,
    result: json['result'] == null ? null : ChatTopicsResult.fromJson(json['result'] as Map<String, dynamic>),
    students: _i(json['students']),
  );
}

class Explainer {
  const Explainer({required this.text, required this.note});

  final String text;
  final String note;

  static const fields = ['go_id', 'text', 'model', 'note'];

  factory Explainer.fromJson(Map<String, dynamic> json) =>
      Explainer(text: (json['text'] as String?) ?? '', note: (json['note'] as String?) ?? '');
}
