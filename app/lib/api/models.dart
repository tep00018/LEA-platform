/// Hand-written models for the API's JSON, kept in step with `docs/api/openapi.json`.
///
/// Each model lists the JSON fields it reads in `fields`; `test/api/models_spec_test.dart`
/// checks those lists against the spec, so a renamed or new field fails a test.
library;

class UserProfile {
  const UserProfile({
    required this.username,
    this.fullName = '',
    this.enrolledCourses = const [],
    this.role = 'student',
  });

  final String username;
  final String fullName;
  final List<String> enrolledCourses;

  /// student, teacher or admin (the Teacher area is for teachers and admins).
  final String role;

  bool get isStaff => role == 'teacher' || role == 'admin';

  static const fields = ['username', 'full_name', 'enrolled_courses', 'role'];

  factory UserProfile.fromJson(Map<String, dynamic> json) => UserProfile(
    username: json['username'] as String,
    fullName: (json['full_name'] as String?) ?? '',
    enrolledCourses: [for (final c in (json['enrolled_courses'] as List?) ?? const []) c as String],
    role: (json['role'] as String?) ?? 'student',
  );

  /// What to call the student: their full name, or their username if they gave none.
  String get displayName => fullName.trim().isEmpty ? username : fullName.trim();

  /// The initial shown in the round avatar.
  String get initial => String.fromCharCode(displayName.runes.first).toUpperCase();
}

class LoginResult {
  const LoginResult({required this.token, required this.expiresIn, required this.user});

  final String token;
  final int expiresIn;
  final UserProfile user;

  static const fields = ['token', 'token_type', 'expires_in', 'user'];

  factory LoginResult.fromJson(Map<String, dynamic> json) => LoginResult(
    token: json['token'] as String,
    expiresIn: json['expires_in'] as int,
    user: UserProfile.fromJson(json['user'] as Map<String, dynamic>),
  );
}

/// Strips a leading prefix such as "DEMO101: " or "Week 1: " from an API title.
String _withoutPrefix(String text, RegExp prefix) {
  final stripped = text.replaceFirst(prefix, '').trim();
  return stripped.isEmpty ? text : stripped;
}

class CourseInfo {
  const CourseInfo({required this.code, required this.name});

  final String code;

  /// As the API sends it, e.g. "DEMO101: Introduction to AI/ML".
  final String name;

  static const fields = ['code', 'name'];

  factory CourseInfo.fromJson(Map<String, dynamic> json) =>
      CourseInfo(code: json['code'] as String, name: json['name'] as String);

  /// The name without the leading course code: "Introduction to AI/ML".
  String get title => _withoutPrefix(name, RegExp('^${RegExp.escape(code)}\\s*[:·\\-–]\\s*'));

  /// "DEMO101 · Introduction to AI/ML", as the course picker shows it.
  String get label => '$code · $title';

  @override
  bool operator ==(Object other) => other is CourseInfo && other.code == code && other.name == name;

  @override
  int get hashCode => Object.hash(code, name);
}

class LearningObjectiveInfo {
  const LearningObjectiveInfo({required this.id, required this.title, required this.conceptCount});

  final String id;
  final String title;
  final int conceptCount;

  static const fields = ['id', 'title', 'concept_count'];

  factory LearningObjectiveInfo.fromJson(Map<String, dynamic> json) => LearningObjectiveInfo(
    id: json['id'] as String,
    title: json['title'] as String,
    conceptCount: (json['concept_count'] as int?) ?? 0,
  );
}

class WeekOutline {
  const WeekOutline({
    required this.number,
    required this.title,
    required this.learningObjectives,
    required this.conceptCount,
  });

  final int number;

  /// As the API sends it, e.g. "Week 1: Introduction to AI".
  final String title;
  final List<LearningObjectiveInfo> learningObjectives;
  final int conceptCount;

  static const fields = ['number', 'title', 'learning_objectives', 'concept_count'];

  factory WeekOutline.fromJson(Map<String, dynamic> json) => WeekOutline(
    number: json['number'] as int,
    title: json['title'] as String,
    learningObjectives: [
      for (final lo in (json['learning_objectives'] as List?) ?? const [])
        LearningObjectiveInfo.fromJson(lo as Map<String, dynamic>),
    ],
    conceptCount: (json['concept_count'] as int?) ?? 0,
  );

  /// The week's topic without "Week N: ": "Introduction to AI".
  String get topic => _withoutPrefix(title, RegExp('^Week\\s*$number\\s*[:·\\-–]\\s*', caseSensitive: false));

  /// "Week 1 · Introduction to AI".
  String get label => 'Week $number · $topic';
}

class CourseOutline {
  const CourseOutline({required this.code, required this.name, required this.weeks});

  final String code;
  final String name;
  final List<WeekOutline> weeks;

  static const fields = ['code', 'name', 'weeks'];

  factory CourseOutline.fromJson(Map<String, dynamic> json) => CourseOutline(
    code: json['code'] as String,
    name: json['name'] as String,
    weeks: [for (final w in (json['weeks'] as List?) ?? const []) WeekOutline.fromJson(w as Map<String, dynamic>)]
      ..sort((a, b) => a.number.compareTo(b.number)),
  );

  WeekOutline? week(int number) {
    for (final w in weeks) {
      if (w.number == number) return w;
    }
    return null;
  }
}

class ProgressSummary {
  const ProgressSummary({
    required this.course,
    this.currentWeek = 1,
    this.weekCompletion = 0,
    this.completedGos = const [],
    this.totalGos = 0,
    this.readyForNextWeek = false,
  });

  final String course;
  final int currentWeek;
  final double weekCompletion;
  final List<String> completedGos;
  final int totalGos;
  final bool readyForNextWeek;

  static const fields = [
    'course',
    'current_week',
    'week_completion',
    'completed_gos',
    'total_gos',
    'ready_for_next_week',
  ];

  factory ProgressSummary.fromJson(Map<String, dynamic> json) => ProgressSummary(
    course: json['course'] as String,
    currentWeek: (json['current_week'] as int?) ?? 1,
    weekCompletion: ((json['week_completion'] as num?) ?? 0).toDouble(),
    completedGos: [for (final g in (json['completed_gos'] as List?) ?? const []) g as String],
    totalGos: (json['total_gos'] as int?) ?? 0,
    readyForNextWeek: (json['ready_for_next_week'] as bool?) ?? false,
  );
}

class ObjectiveMastery {
  const ObjectiveMastery({
    required this.goId,
    required this.skillName,
    required this.mastery,
    required this.threshold,
    required this.mastered,
  });

  final String goId;
  final String skillName;

  /// Null until the student has a graded answer on it.
  final double? mastery;
  final double threshold;
  final bool mastered;

  static const fields = ['go_id', 'skill_name', 'mastery', 'threshold', 'mastered'];

  factory ObjectiveMastery.fromJson(Map<String, dynamic> json) => ObjectiveMastery(
    goId: json['go_id'] as String,
    skillName: json['skill_name'] as String,
    mastery: (json['mastery'] as num?)?.toDouble(),
    threshold: (json['threshold'] as num).toDouble(),
    mastered: json['mastered'] as bool,
  );
}

class LearningObjectiveMastery {
  const LearningObjectiveMastery({required this.loId, required this.title, required this.objectives});

  final String loId;
  final String title;
  final List<ObjectiveMastery> objectives;

  static const fields = ['lo_id', 'title', 'objectives'];

  factory LearningObjectiveMastery.fromJson(Map<String, dynamic> json) => LearningObjectiveMastery(
    loId: json['lo_id'] as String,
    title: json['title'] as String,
    objectives: [
      for (final o in (json['objectives'] as List?) ?? const []) ObjectiveMastery.fromJson(o as Map<String, dynamic>),
    ],
  );
}

class WeekMastery {
  const WeekMastery({
    required this.course,
    required this.week,
    required this.completion,
    required this.masteredCount,
    required this.total,
    required this.learningObjectives,
  });

  final String course;
  final int week;
  final double completion;
  final int masteredCount;
  final int total;
  final List<LearningObjectiveMastery> learningObjectives;

  static const fields = ['course', 'week', 'completion', 'mastered_count', 'total', 'learning_objectives'];

  factory WeekMastery.fromJson(Map<String, dynamic> json) => WeekMastery(
    course: json['course'] as String,
    week: json['week'] as int,
    completion: ((json['completion'] as num?) ?? 0).toDouble(),
    masteredCount: (json['mastered_count'] as int?) ?? 0,
    total: (json['total'] as int?) ?? 0,
    learningObjectives: [
      for (final lo in (json['learning_objectives'] as List?) ?? const [])
        LearningObjectiveMastery.fromJson(lo as Map<String, dynamic>),
    ],
  );
}

/// The body of `POST /auth/register`.
class RegisterRequest {
  const RegisterRequest({
    required this.username,
    required this.fullName,
    required this.password,
    required this.courses,
  });

  final String username;
  final String fullName;
  final String password;
  final List<String> courses;

  static const fields = ['username', 'full_name', 'password', 'courses'];

  Map<String, dynamic> toJson() => {
    'username': username,
    'full_name': fullName,
    'password': password,
    'courses': courses,
  };
}

/// One message in a course's chat history.
class ChatMessage {
  const ChatMessage({required this.role, required this.message, required this.timestamp});

  /// `user` or `assistant`.
  final String role;
  final String message;

  /// Seconds since the epoch.
  final double timestamp;

  static const fields = ['role', 'message', 'timestamp'];

  factory ChatMessage.fromJson(Map<String, dynamic> json) => ChatMessage(
    role: json['role'] as String,
    message: json['message'] as String,
    timestamp: (json['timestamp'] as num).toDouble(),
  );

  bool get fromStudent => role == 'user';

  DateTime get time => DateTime.fromMillisecondsSinceEpoch((timestamp * 1000).round());
}

/// The body of `POST /chat/{code}/messages[/stream]`.
class ChatRequest {
  const ChatRequest({required this.text, required this.week});

  final String text;
  final int week;

  static const fields = ['text', 'week'];

  Map<String, dynamic> toJson() => {'text': text, 'week': week};
}

/// A chat reply: the non-streaming response, and the streamed `done` event's body.
class ChatReply {
  const ChatReply({required this.ok, required this.message});

  final bool ok;
  final String message;

  static const fields = ['ok', 'message'];

  factory ChatReply.fromJson(Map<String, dynamic> json) =>
      ChatReply(ok: (json['ok'] as bool?) ?? false, message: (json['message'] as String?) ?? '');
}

/// The objective the tutor is on.
class ObjectiveView {
  const ObjectiveView({required this.goId, required this.skillName, this.description = ''});

  final String goId;
  final String skillName;
  final String description;

  static const fields = ['go_id', 'skill_name', 'description'];

  factory ObjectiveView.fromJson(Map<String, dynamic> json) => ObjectiveView(
    goId: json['go_id'] as String,
    skillName: json['skill_name'] as String,
    description: (json['description'] as String?) ?? '',
  );
}

class TutorMessage {
  const TutorMessage({required this.role, required this.content, required this.timestamp});

  /// `student` or `tutor`.
  final String role;
  final String content;

  /// ISO 8601, in the server's local time.
  final String timestamp;

  static const fields = ['role', 'content', 'timestamp'];

  factory TutorMessage.fromJson(Map<String, dynamic> json) => TutorMessage(
    role: json['role'] as String,
    content: json['content'] as String,
    timestamp: (json['timestamp'] as String?) ?? '',
  );

  bool get fromStudent => role == 'student';

  DateTime? get time => DateTime.tryParse(timestamp);
}

/// A tutor session (`GET/POST /tutor`, and inside each reply).
class TutorView {
  const TutorView({
    required this.sessionId,
    required this.course,
    required this.week,
    required this.completed,
    required this.progressPercent,
    required this.objectiveIndex,
    required this.objectivesTotal,
    required this.currentObjective,
    required this.scaffoldingLevel,
    required this.scaffoldingStrategy,
    required this.messages,
    this.advancedToWeek,
    this.quizReview = false,
    this.currentObjectiveMastery,
    this.cognitiveLoad,
    this.zpdScore,
  });

  final String sessionId;
  final String course;
  final int week;
  final bool completed;
  final double progressPercent;

  /// 0-based index of the current objective.
  final int objectiveIndex;
  final int objectivesTotal;
  final ObjectiveView? currentObjective;

  /// very_high, high, medium, low or minimal.
  final String scaffoldingLevel;

  /// conceptual, procedural, strategic or metacognitive ("" from an older server).
  final String scaffoldingStrategy;
  final List<TutorMessage> messages;
  final int? advancedToWeek;

  /// The session is reviewing a quiz the student just took ("Review with the tutor").
  final bool quizReview;

  /// Debug/monitoring (temporary -- may go away): the current objective's mastery, 0-1.
  final double? currentObjectiveMastery;

  /// Debug/monitoring (temporary): the learner's cognitive load as of the last turn.
  final double? cognitiveLoad;

  /// Debug/monitoring (temporary): the learner's ZPD score as of the last turn.
  final double? zpdScore;

  static const fields = [
    'session_id',
    'course',
    'week',
    'completed',
    'progress_percent',
    'objective_index',
    'objectives_total',
    'current_objective',
    'scaffolding_level',
    'scaffolding_strategy',
    'messages',
    'advanced_to_week',
    'quiz_review',
    'current_objective_mastery',
    'cognitive_load',
    'zpd_score',
  ];

  factory TutorView.fromJson(Map<String, dynamic> json) => TutorView(
    sessionId: json['session_id'] as String,
    course: json['course'] as String,
    week: json['week'] as int,
    completed: json['completed'] as bool,
    progressPercent: ((json['progress_percent'] as num?) ?? 0).toDouble(),
    objectiveIndex: json['objective_index'] as int,
    objectivesTotal: json['objectives_total'] as int,
    currentObjective: json['current_objective'] == null
        ? null
        : ObjectiveView.fromJson(json['current_objective'] as Map<String, dynamic>),
    scaffoldingLevel: (json['scaffolding_level'] as String?) ?? '',
    scaffoldingStrategy: (json['scaffolding_strategy'] as String?) ?? '',
    messages: [
      for (final m in (json['messages'] as List?) ?? const []) TutorMessage.fromJson(m as Map<String, dynamic>),
    ],
    advancedToWeek: json['advanced_to_week'] as int?,
    quizReview: (json['quiz_review'] as bool?) ?? false,
    currentObjectiveMastery: (json['current_objective_mastery'] as num?)?.toDouble(),
    cognitiveLoad: (json['cognitive_load'] as num?)?.toDouble(),
    zpdScore: (json['zpd_score'] as num?)?.toDouble(),
  );
}

/// The body of `POST /tutor/replies[/stream]`'s answer, and the streamed `done` event.
class TutorReplyResult {
  const TutorReplyResult({
    required this.message,
    required this.graded,
    required this.correct,
    required this.achievements,
    required this.session,
  });

  final String message;

  /// Whether the reply counted towards mastery.
  final bool graded;

  /// Null when not graded.
  final bool? correct;
  final List<String> achievements;
  final TutorView session;

  static const fields = ['message', 'graded', 'correct', 'achievements', 'session'];

  factory TutorReplyResult.fromJson(Map<String, dynamic> json) => TutorReplyResult(
    message: (json['message'] as String?) ?? '',
    graded: (json['graded'] as bool?) ?? false,
    correct: json['correct'] as bool?,
    achievements: [for (final a in (json['achievements'] as List?) ?? const []) a as String],
    session: TutorView.fromJson(json['session'] as Map<String, dynamic>),
  );
}

/// `POST /tutor/end`.
class TutorSummary {
  const TutorSummary({
    required this.totalGos,
    required this.gosCompleted,
    required this.gosMastered,
    required this.accuracy,
    required this.interactionCount,
    this.advancedToWeek,
  });

  final int totalGos;
  final int gosCompleted;
  final int gosMastered;

  /// Share of the session's replies that were correct, 0–1.
  final double accuracy;
  final int interactionCount;
  final int? advancedToWeek;

  static const fields = [
    'total_gos',
    'gos_completed',
    'gos_mastered',
    'accuracy',
    'interaction_count',
    'advanced_to_week',
  ];

  factory TutorSummary.fromJson(Map<String, dynamic> json) => TutorSummary(
    totalGos: (json['total_gos'] as int?) ?? 0,
    gosCompleted: (json['gos_completed'] as int?) ?? 0,
    gosMastered: (json['gos_mastered'] as int?) ?? 0,
    accuracy: ((json['accuracy'] as num?) ?? 0).toDouble(),
    interactionCount: (json['interaction_count'] as int?) ?? 0,
    advancedToWeek: json['advanced_to_week'] as int?,
  );

  int get accuracyPercent => (accuracy * 100).round();
}

/// A quiz question. Never carries the answer.
class QuizQuestion {
  const QuizQuestion({
    required this.number,
    required this.type,
    required this.text,
    this.options = const [],
    this.hasCode = false,
    this.skillName = '',
  });

  final int number;

  /// multiple_choice, true_false, fill_in_blank or open_ended.
  final String type;
  final String text;

  /// As sent, e.g. "A) The AI needs more computing power".
  final List<String> options;
  final bool hasCode;
  final String skillName;

  static const fields = ['number', 'type', 'text', 'options', 'has_code', 'skill_name'];

  factory QuizQuestion.fromJson(Map<String, dynamic> json) => QuizQuestion(
    number: json['number'] as int,
    type: json['type'] as String,
    text: json['text'] as String,
    options: [for (final o in (json['options'] as List?) ?? const []) o as String],
    hasCode: (json['has_code'] as bool?) ?? false,
    skillName: (json['skill_name'] as String?) ?? '',
  );

  /// "Multiple choice", as the kicker shows it.
  String get typeLabel => switch (type) {
    'multiple_choice' => 'Multiple choice',
    'true_false' => 'True or false',
    'fill_in_blank' => 'Fill in the blank',
    'open_ended' => 'Open answer',
    _ => 'Question',
  };

  static final _prefix = RegExp(r'^\s*\(?([A-Fa-f])[\).:\-]\s*');

  /// The options as (letter, text): "A) text" → ("A", "text"); unlabelled ones get A, B, …
  List<({String letter, String text})> get choices => [
    for (final (i, o) in options.indexed)
      () {
        final m = _prefix.firstMatch(o);
        return m == null
            ? (letter: String.fromCharCode(65 + i), text: o.trim())
            : (letter: m.group(1)!.toUpperCase(), text: o.substring(m.end).trim());
      }(),
  ];
}

/// Feedback on one answer; also each entry in the results.
class QuizFeedback {
  const QuizFeedback({
    required this.graded,
    required this.correct,
    required this.score,
    required this.explanation,
    this.yourAnswer = '',
    this.correctAnswer,
    this.achievements = const [],
    this.goId,
  });

  final bool graded;

  /// Null when the answer couldn't be graded (it doesn't count).
  final bool? correct;
  final double? score;
  final String explanation;
  final String yourAnswer;

  /// The right option letter (multiple choice) or "True"/"False"; null for free text.
  final String? correctAnswer;
  final List<String> achievements;

  /// The objective the question tested.
  final String? goId;

  static const fields = [
    'graded',
    'correct',
    'score',
    'explanation',
    'your_answer',
    'correct_answer',
    'achievements',
    'go_id',
  ];

  factory QuizFeedback.fromJson(Map<String, dynamic> json) => QuizFeedback(
    graded: (json['graded'] as bool?) ?? false,
    correct: json['correct'] as bool?,
    score: (json['score'] as num?)?.toDouble(),
    explanation: (json['explanation'] as String?) ?? '',
    yourAnswer: (json['your_answer'] as String?) ?? '',
    correctAnswer: json['correct_answer'] as String?,
    achievements: [for (final a in (json['achievements'] as List?) ?? const []) a as String],
    goId: json['go_id'] as String?,
  );
}

/// A quiz (`GET/POST /quiz` and every quiz action).
class QuizView {
  const QuizView({
    required this.quizId,
    required this.course,
    required this.week,
    required this.status,
    required this.position,
    required this.total,
    required this.correctCount,
    required this.gradedCount,
    this.question,
    this.feedback,
    this.results = const [],
    this.advancedToWeek,
  });

  final String quizId;
  final String course;
  final int week;

  /// question, feedback or completed.
  final String status;

  /// 1-based number of the current question.
  final int position;
  final int total;
  final int correctCount;
  final int gradedCount;
  final QuizQuestion? question;
  final QuizFeedback? feedback;
  final List<QuizFeedback> results;
  final int? advancedToWeek;

  static const fields = [
    'quiz_id',
    'course',
    'week',
    'status',
    'position',
    'total',
    'correct_count',
    'graded_count',
    'question',
    'feedback',
    'results',
    'advanced_to_week',
  ];

  factory QuizView.fromJson(Map<String, dynamic> json) => QuizView(
    quizId: json['quiz_id'] as String,
    course: json['course'] as String,
    week: json['week'] as int,
    status: json['status'] as String,
    position: json['position'] as int,
    total: json['total'] as int,
    correctCount: (json['correct_count'] as int?) ?? 0,
    gradedCount: (json['graded_count'] as int?) ?? 0,
    question: json['question'] == null ? null : QuizQuestion.fromJson(json['question'] as Map<String, dynamic>),
    feedback: json['feedback'] == null ? null : QuizFeedback.fromJson(json['feedback'] as Map<String, dynamic>),
    results: [for (final r in (json['results'] as List?) ?? const []) QuizFeedback.fromJson(r as Map<String, dynamic>)],
    advancedToWeek: json['advanced_to_week'] as int?,
  );

  bool get asking => status == 'question';
  bool get showingFeedback => status == 'feedback';
  bool get completed => status == 'completed';
}
