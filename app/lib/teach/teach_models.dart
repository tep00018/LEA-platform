/// The Teacher area's API models (`/teach/...`). Each has `fields`, the property names it
/// reads, which `test/api/models_spec_test.dart` checks against the API spec.
library;

double _d(Object? v, [double fallback = 0]) => (v as num?)?.toDouble() ?? fallback;
List<String> _strings(Object? v) => [for (final s in (v as List?) ?? const []) s as String];

/// `TeachCourseOut`: one course in the Teacher area.
class TeachCourse {
  const TeachCourse({
    required this.code,
    required this.name,
    required this.owners,
    required this.managed,
    required this.uploads,
    required this.activeJob,
    required this.hasKcModel,
    required this.hasContent,
    required this.weeks,
    required this.learningObjectives,
    required this.granularObjectives,
  });

  final String code;
  final String name;
  final List<String> owners;

  /// Set up in the Teacher area (uploads and builds); false for courses onboarded by hand.
  final bool managed;
  final int uploads;
  final String? activeJob;

  /// A published KC model is installed (students can use the course).
  final bool hasKcModel;
  final bool hasContent;
  final int weeks;
  final int learningObjectives;
  final int granularObjectives;

  static const fields = [
    'code',
    'name',
    'owners',
    'managed',
    'uploads',
    'active_job',
    'has_kc_model',
    'has_content',
    'weeks',
    'learning_objectives',
    'granular_objectives',
  ];

  factory TeachCourse.fromJson(Map<String, dynamic> json) => TeachCourse(
    code: json['code'] as String,
    name: json['name'] as String,
    owners: _strings(json['owners']),
    managed: (json['managed'] as bool?) ?? false,
    uploads: (json['uploads'] as int?) ?? 0,
    activeJob: json['active_job'] as String?,
    hasKcModel: (json['has_kc_model'] as bool?) ?? false,
    hasContent: (json['has_content'] as bool?) ?? false,
    weeks: (json['weeks'] as int?) ?? 0,
    learningObjectives: (json['learning_objectives'] as int?) ?? 0,
    granularObjectives: (json['granular_objectives'] as int?) ?? 0,
  );

  /// "AIML101 · Introduction to AI and Machine Learning".
  String get label => name.isEmpty || name == code ? code : '$code · $name';
}

/// `CourseCreateIn`: a new course.
class CourseCreateRequest {
  const CourseCreateRequest({
    required this.code,
    required this.name,
    required this.discipline,
    required this.allowsCode,
    required this.codeLanguage,
    required this.weeks,
  });

  final String code;
  final String name;
  final String discipline;
  final bool allowsCode;
  final String? codeLanguage;
  final int weeks;

  static const fields = ['code', 'name', 'discipline', 'allows_code', 'code_language', 'weeks'];

  Map<String, dynamic> toJson() => {
    'code': code,
    'name': name,
    'discipline': discipline,
    'allows_code': allowsCode,
    'code_language': allowsCode ? codeLanguage : null,
    'weeks': weeks,
  };
}

const disciplines = [
  ('computing', 'Computing'),
  ('mathematics', 'Mathematics'),
  ('science', 'Science'),
  ('engineering', 'Engineering'),
  ('social_science', 'Social science'),
  ('humanities', 'Humanities'),
  ('business', 'Business'),
  ('health', 'Health'),
  ('education', 'Education'),
  ('arts', 'Arts'),
  ('other', 'Other'),
];

/// `WeekPlanOut` / `WeekPlanIn`: one week's title and learning objectives.
class WeekPlan {
  const WeekPlan({required this.week, required this.title, required this.objectives});

  final int week;
  final String title;
  final List<String> objectives;

  static const fields = ['week', 'title', 'objectives'];

  factory WeekPlan.fromJson(Map<String, dynamic> json) =>
      WeekPlan(week: json['week'] as int, title: json['title'] as String, objectives: _strings(json['objectives']));

  Map<String, dynamic> toJson() => {'week': week, 'title': title, 'objectives': objectives};
}

/// `UploadOut`: an uploaded course file.
class CourseUpload {
  const CourseUpload({
    required this.name,
    required this.size,
    required this.week,
    required this.kind,
    this.linkedRelpath,
  });

  final String name;
  final int size;
  final int? week;
  final String? kind;

  /// Set when this upload came from a linked materials source, its path there.
  final String? linkedRelpath;

  bool get isLinked => linkedRelpath != null;

  static const fields = ['name', 'size', 'sha256', 'week', 'kind', 'uploaded_by', 'uploaded_at', 'linked_relpath'];

  factory CourseUpload.fromJson(Map<String, dynamic> json) => CourseUpload(
    name: json['name'] as String,
    size: json['size'] as int,
    week: json['week'] as int?,
    kind: json['kind'] as String?,
    linkedRelpath: json['linked_relpath'] as String?,
  );

  /// "18.2 MB", "12 KB".
  String get sizeLabel {
    if (size >= 1000000) return '${(size / 1000000).toStringAsFixed(1)} MB';
    return '${(size / 1000).ceil()} KB';
  }
}

/// `MaterialsSourceOut` / `MaterialsSourceIn`: a course's linked (read-only) materials folder.
class MaterialsSource {
  const MaterialsSource({required this.type, required this.path});

  final String type;
  final String path;

  static const fields = ['type', 'path'];

  factory MaterialsSource.fromJson(Map<String, dynamic> json) =>
      MaterialsSource(type: json['type'] as String, path: json['path'] as String);

  Map<String, dynamic> toJson() => {'type': type, 'path': path};
}

/// `MaterialsFolderOut`: one subfolder under the materials root.
class MaterialsFolder {
  const MaterialsFolder({required this.name});

  final String name;

  static const fields = ['name'];

  factory MaterialsFolder.fromJson(Map<String, dynamic> json) => MaterialsFolder(name: json['name'] as String);
}

/// `SyncPreviewEntryOut`: one candidate file in a materials-source sync preview.
class SyncPreviewEntry {
  const SyncPreviewEntry({
    required this.relpath,
    required this.name,
    required this.size,
    required this.status,
    this.reason,
  });

  final String relpath;
  final String name;
  final int size;

  /// new, changed, unchanged, removed or rejected.
  final String status;
  final String? reason;

  static const fields = ['relpath', 'name', 'size', 'status', 'reason'];

  factory SyncPreviewEntry.fromJson(Map<String, dynamic> json) => SyncPreviewEntry(
    relpath: json['relpath'] as String,
    name: json['name'] as String,
    size: (json['size'] as int?) ?? 0,
    status: json['status'] as String,
    reason: json['reason'] as String?,
  );
}

/// `SyncPreviewOut`: what the next Build job would pick up from a linked folder.
class SyncPreview {
  const SyncPreview({
    required this.entries,
    required this.newCount,
    required this.changed,
    required this.unchanged,
    required this.removed,
    required this.rejected,
  });

  final List<SyncPreviewEntry> entries;
  final int newCount;
  final int changed;
  final int unchanged;
  final int removed;
  final int rejected;

  static const fields = ['entries', 'new', 'changed', 'unchanged', 'removed', 'rejected'];

  factory SyncPreview.fromJson(Map<String, dynamic> json) => SyncPreview(
    entries: [
      for (final e in (json['entries'] as List?) ?? const []) SyncPreviewEntry.fromJson(e as Map<String, dynamic>),
    ],
    newCount: (json['new'] as int?) ?? 0,
    changed: (json['changed'] as int?) ?? 0,
    unchanged: (json['unchanged'] as int?) ?? 0,
    removed: (json['removed'] as int?) ?? 0,
    rejected: (json['rejected'] as int?) ?? 0,
  );
}

const uploadKinds = ['Lecture', 'Lab', 'Reading', 'Assignment', 'Transcript', 'Video', 'Audio', 'Other'];

/// `CostEstimateOut`.
class CostEstimate {
  const CostEstimate({
    required this.usd,
    required this.perStep,
    required this.documents,
    required this.media,
    required this.images,
    required this.modelCalls,
    required this.notes,
  });

  final double usd;
  final Map<String, double> perStep;
  final int documents;
  final int media;
  final int images;
  final int modelCalls;
  final List<String> notes;

  static const fields = ['usd', 'per_step', 'files', 'documents', 'media', 'images', 'model_calls', 'notes'];

  factory CostEstimate.fromJson(Map<String, dynamic> json) => CostEstimate(
    usd: _d(json['usd']),
    perStep: {for (final e in ((json['per_step'] as Map?) ?? const {}).entries) e.key as String: _d(e.value)},
    documents: (json['documents'] as int?) ?? 0,
    media: (json['media'] as int?) ?? 0,
    images: (json['images'] as int?) ?? 0,
    modelCalls: (json['model_calls'] as int?) ?? 0,
    notes: _strings(json['notes']),
  );
}

/// "$0.41" (or "$0.003" for amounts under a cent).
String dollars(double usd) => usd > 0 && usd < 0.01 ? '\$${usd.toStringAsFixed(3)}' : '\$${usd.toStringAsFixed(2)}';

const jobSteps = [
  ('convert', 'Converting uploads'),
  ('transcribe', 'Transcribing audio and video'),
  ('embed', 'Chunking and embedding'),
  ('kc_draft', 'Drafting the objectives (GPT-4o)'),
  ('profile', 'Writing the course profile'),
  ('verify', 'Checking content for each objective'),
];

/// `JobOut`: an onboarding run.
class Job {
  const Job({
    required this.id,
    required this.course,
    required this.status,
    required this.step,
    required this.stepLabel,
    required this.percent,
    required this.steps,
    required this.estimate,
    required this.result,
    required this.error,
    required this.createdBy,
    required this.log,
  });

  final String id;
  final String course;

  /// awaiting_confirmation, queued, running, succeeded, failed or cancelled.
  final String status;
  final String? step;
  final String stepLabel;
  final double percent;
  final List<String> steps;
  final CostEstimate estimate;
  final Map<String, dynamic> result;
  final String? error;
  final String createdBy;
  final List<String> log;

  static const fields = [
    'id',
    'course',
    'status',
    'step',
    'step_label',
    'percent',
    'steps',
    'estimate',
    'result',
    'error',
    'created_by',
    'created_at',
    'started_at',
    'finished_at',
    'log',
  ];

  factory Job.fromJson(Map<String, dynamic> json) => Job(
    id: json['id'] as String,
    course: json['course'] as String,
    status: json['status'] as String,
    step: (json['step'] as String?)?.isEmpty ?? true ? null : json['step'] as String,
    stepLabel: (json['step_label'] as String?) ?? '',
    percent: _d(json['percent']),
    steps: _strings(json['steps']),
    estimate: CostEstimate.fromJson((json['estimate'] as Map<String, dynamic>?) ?? const {}),
    result: (json['result'] as Map<String, dynamic>?) ?? const {},
    error: (json['error'] as String?)?.isEmpty ?? true ? null : json['error'] as String,
    createdBy: (json['created_by'] as String?) ?? '',
    log: _strings(json['log']),
  );

  bool get awaitingConfirmation => status == 'awaiting_confirmation';
  bool get active => status == 'queued' || status == 'running';
  bool get finished => status == 'succeeded' || status == 'failed' || status == 'cancelled';
}

/// `KCRow`: one granular objective in a KC draft.
class KCRow {
  const KCRow({
    this.goId,
    required this.week,
    this.weekTitle = '',
    this.loId,
    required this.loTitle,
    this.loShortTitle = '',
    required this.skillName,
    this.description = '',
    required this.cognitiveLevel,
    required this.masteryThreshold,
    this.keywords = const [],
    this.prerequisites = const [],
    this.prerequisiteNotes = const [],
    this.splitFrom,
    this.mergedFrom = const [],
    this.provenance,
  });

  final String? goId;
  final int week;
  final String weekTitle;
  final String? loId;
  final String loTitle;
  final String loShortTitle;
  final String skillName;
  final String description;
  final String cognitiveLevel;
  final double masteryThreshold;
  final List<String> keywords;
  final List<String> prerequisites;
  final List<String> prerequisiteNotes;
  final String? splitFrom;
  final List<String> mergedFrom;

  /// The best-matching course excerpt: `source_file`, `excerpt`, `similarity`.
  final Map<String, dynamic>? provenance;

  static const fields = [
    'go_id',
    'week',
    'week_title',
    'lo_id',
    'lo_title',
    'lo_short_title',
    'skill_name',
    'description',
    'cognitive_level',
    'mastery_threshold',
    'keywords',
    'prerequisites',
    'prerequisite_notes',
    'split_from',
    'merged_from',
    'provenance',
  ];

  factory KCRow.fromJson(Map<String, dynamic> json) => KCRow(
    goId: json['go_id'] as String?,
    week: json['week'] as int,
    weekTitle: (json['week_title'] as String?) ?? '',
    loId: json['lo_id'] as String?,
    loTitle: (json['lo_title'] as String?) ?? '',
    loShortTitle: (json['lo_short_title'] as String?) ?? '',
    skillName: (json['skill_name'] as String?) ?? '',
    description: (json['description'] as String?) ?? '',
    cognitiveLevel: (json['cognitive_level'] as String?) ?? '',
    masteryThreshold: _d(json['mastery_threshold'], 0.75),
    keywords: _strings(json['keywords']),
    prerequisites: _strings(json['prerequisites']),
    prerequisiteNotes: _strings(json['prerequisite_notes']),
    splitFrom: json['split_from'] as String?,
    mergedFrom: _strings(json['merged_from']),
    provenance: json['provenance'] as Map<String, dynamic>?,
  );

  Map<String, dynamic> toJson() => {
    'go_id': goId,
    'week': week,
    'week_title': weekTitle,
    'lo_id': loId,
    'lo_title': loTitle,
    'lo_short_title': loShortTitle,
    'skill_name': skillName,
    'description': description,
    'cognitive_level': cognitiveLevel,
    'mastery_threshold': masteryThreshold,
    'keywords': keywords,
    'prerequisites': prerequisites,
    'prerequisite_notes': prerequisiteNotes,
    'split_from': splitFrom,
    'merged_from': mergedFrom,
    'provenance': provenance,
  };

  KCRow copyWith({
    String? Function()? goId,
    String? skillName,
    String? description,
    String? cognitiveLevel,
    double? masteryThreshold,
    List<String>? keywords,
    String? Function()? splitFrom,
    List<String>? mergedFrom,
  }) => KCRow(
    goId: goId == null ? this.goId : goId(),
    week: week,
    weekTitle: weekTitle,
    loId: loId,
    loTitle: loTitle,
    loShortTitle: loShortTitle,
    skillName: skillName ?? this.skillName,
    description: description ?? this.description,
    cognitiveLevel: cognitiveLevel ?? this.cognitiveLevel,
    masteryThreshold: masteryThreshold ?? this.masteryThreshold,
    keywords: keywords ?? this.keywords,
    prerequisites: prerequisites,
    prerequisiteNotes: prerequisiteNotes,
    splitFrom: splitFrom == null ? this.splitFrom : splitFrom(),
    mergedFrom: mergedFrom ?? this.mergedFrom,
    provenance: provenance,
  );

  double? get similarity => (provenance?['similarity'] as num?)?.toDouble();
  String? get excerpt => provenance?['excerpt'] as String?;
  String? get source => provenance?['source_file'] as String?;
}

const bloomLevels = ['Remember', 'Understand', 'Apply', 'Analyze', 'Evaluate', 'Create'];

/// `KCIssue`: a problem (error) or warning in a draft.
class KCIssue {
  const KCIssue({required this.row, required this.field, required this.message, required this.error});

  final int? row;
  final String field;
  final String message;
  final bool error;

  static const fields = ['row', 'field', 'message', 'level'];

  factory KCIssue.fromJson(Map<String, dynamic> json) => KCIssue(
    row: json['row'] as int?,
    field: json['field'] as String,
    message: json['message'] as String,
    error: json['level'] == 'error',
  );
}

/// `DraftOut`: the KC draft.
class KCDraft {
  const KCDraft({
    required this.source,
    required this.basedOn,
    required this.updatedAt,
    required this.saves,
    required this.rows,
    required this.issues,
  });

  final String source;
  final int? basedOn;
  final String updatedAt;
  final int saves;
  final List<KCRow> rows;
  final List<KCIssue> issues;

  static const fields = [
    'course',
    'source',
    'based_on',
    'created_by',
    'created_at',
    'updated_by',
    'updated_at',
    'saves',
    'rows',
    'issues',
  ];

  factory KCDraft.fromJson(Map<String, dynamic> json) => KCDraft(
    source: json['source'] as String,
    basedOn: json['based_on'] as int?,
    updatedAt: (json['updated_at'] as String?) ?? '',
    saves: (json['saves'] as int?) ?? 0,
    rows: [for (final r in (json['rows'] as List?) ?? const []) KCRow.fromJson(r as Map<String, dynamic>)],
    issues: [for (final i in (json['issues'] as List?) ?? const []) KCIssue.fromJson(i as Map<String, dynamic>)],
  );
}

/// `KCOverviewOut`: versions and whether there's a draft.
class KCOverview {
  const KCOverview({required this.publishedVersion, required this.hasDraft, required this.versions});

  final int? publishedVersion;
  final bool hasDraft;
  final List<Map<String, dynamic>> versions;

  static const fields = ['published_version', 'versions', 'draft'];

  factory KCOverview.fromJson(Map<String, dynamic> json) => KCOverview(
    publishedVersion: json['published_version'] as int?,
    hasDraft: json['draft'] != null,
    versions: [for (final v in (json['versions'] as List?) ?? const []) v as Map<String, dynamic>],
  );
}

/// `KCDiffOut`: what publishing would change.
class KCDiff {
  const KCDiff({
    required this.added,
    required this.changed,
    required this.retired,
    required this.splits,
    required this.merges,
    required this.counts,
    required this.impact,
  });

  final List<Map<String, dynamic>> added;
  final List<Map<String, dynamic>> changed;
  final List<Map<String, dynamic>> retired;
  final List<Map<String, dynamic>> splits;
  final List<Map<String, dynamic>> merges;
  final Map<String, int> counts;
  final Map<String, dynamic> impact;

  static const fields = ['added', 'changed', 'retired', 'splits', 'merges', 'counts', 'impact'];

  static List<Map<String, dynamic>> _maps(Object? v) => [
    for (final m in (v as List?) ?? const []) m as Map<String, dynamic>,
  ];

  factory KCDiff.fromJson(Map<String, dynamic> json) => KCDiff(
    added: _maps(json['added']),
    changed: _maps(json['changed']),
    retired: _maps(json['retired']),
    splits: _maps(json['splits']),
    merges: _maps(json['merges']),
    counts: {for (final e in ((json['counts'] as Map?) ?? const {}).entries) e.key as String: e.value as int},
    impact: (json['impact'] as Map<String, dynamic>?) ?? const {},
  );

  int get studentsAffected => (impact['students_affected'] as int?) ?? 0;
  int get studentsWithMastery => (impact['students_with_mastery'] as int?) ?? 0;
  int withMasteryOn(String kind) => ((impact['with_mastery_on'] as Map?)?[kind] as int?) ?? 0;
}

/// `PreviewSessionOut`: a token for the teacher's sandbox student account.
class PreviewSession {
  const PreviewSession({required this.username, required this.token, required this.course, required this.version});

  final String username;
  final String token;
  final String course;
  final int version;

  static const fields = ['username', 'token', 'course', 'version', 'expires_at'];

  factory PreviewSession.fromJson(Map<String, dynamic> json) => PreviewSession(
    username: json['username'] as String,
    token: json['token'] as String,
    course: json['course'] as String,
    version: (json['version'] as int?) ?? 0,
  );
}

/// `PreviewTurnOut`: why LEA did what it did on one preview turn.
class PreviewTurn {
  const PreviewTurn({
    required this.mode,
    required this.goId,
    required this.objective,
    required this.threshold,
    required this.masteryBefore,
    required this.masteryAfter,
    required this.graded,
    required this.correct,
    required this.score,
    required this.diagnostic,
    required this.learner,
    required this.sources,
  });

  final String mode;
  final String? goId;
  final String? objective;
  final double? threshold;
  final double? masteryBefore;
  final double? masteryAfter;
  final bool graded;
  final bool? correct;
  final double? score;
  final bool diagnostic;
  final Map<String, dynamic> learner;
  final List<({String source, String excerpt})> sources;

  static const fields = [
    'at',
    'course',
    'mode',
    'go_id',
    'objective',
    'threshold',
    'question',
    'mastery_before',
    'mastery_after',
    'graded',
    'correct',
    'score',
    'diagnostic',
    'advanced',
    'learner',
    'sources',
  ];

  factory PreviewTurn.fromJson(Map<String, dynamic> json) => PreviewTurn(
    mode: json['mode'] as String,
    goId: json['go_id'] as String?,
    objective: json['objective'] as String?,
    threshold: (json['threshold'] as num?)?.toDouble(),
    masteryBefore: (json['mastery_before'] as num?)?.toDouble(),
    masteryAfter: (json['mastery_after'] as num?)?.toDouble(),
    graded: (json['graded'] as bool?) ?? false,
    correct: json['correct'] as bool?,
    score: (json['score'] as num?)?.toDouble(),
    diagnostic: (json['diagnostic'] as bool?) ?? false,
    learner: (json['learner'] as Map<String, dynamic>?) ?? const {},
    sources: [
      for (final s in (json['sources'] as List?) ?? const [])
        (source: ((s as Map)['source'] as String?) ?? '', excerpt: (s['excerpt'] as String?) ?? ''),
    ],
  );
}

/// `ProbeOut`: something to try in a preview.
class Probe {
  const Probe({required this.id, required this.text});

  final String id;
  final String text;

  static const fields = ['id', 'text'];

  factory Probe.fromJson(Map<String, dynamic> json) => Probe(id: json['id'] as String, text: json['text'] as String);
}

/// `AuditFindingOut`: one audit finding, with the teacher's decision.
class AuditFinding {
  const AuditFinding({
    required this.key,
    required this.check,
    required this.severity,
    required this.title,
    required this.explanation,
    required this.evidence,
    required this.targetKind,
    required this.targetRef,
    required this.tier,
    required this.llm,
    required this.status,
    required this.note,
    required this.isNew,
  });

  final String key;
  final String check;

  /// high, medium, low or info.
  final String severity;
  final String title;
  final String explanation;
  final String evidence;
  final String targetKind;
  final String targetRef;

  /// well_supported, rule_based, moderate, experimental or informational.
  final String tier;
  final bool llm;

  /// open, accepted or dismissed.
  final String status;
  final String note;
  final bool isNew;

  static const fields = [
    'key',
    'check',
    'severity',
    'title',
    'explanation',
    'evidence',
    'target',
    'tier',
    'llm',
    'weight',
    'status',
    'note',
    'new',
  ];

  factory AuditFinding.fromJson(Map<String, dynamic> json) => AuditFinding(
    key: json['key'] as String,
    check: json['check'] as String,
    severity: json['severity'] as String,
    title: json['title'] as String,
    explanation: (json['explanation'] as String?) ?? '',
    evidence: (json['evidence'] as String?) ?? '',
    targetKind: ((json['target'] as Map?)?['kind'] as String?) ?? '',
    targetRef: ((json['target'] as Map?)?['ref'] as String?) ?? '',
    tier: json['tier'] as String,
    llm: (json['llm'] as bool?) ?? false,
    status: (json['status'] as String?) ?? 'open',
    note: (json['note'] as String?) ?? '',
    isNew: (json['new'] as bool?) ?? false,
  );
}

const auditChecks = {
  'accessibility': 'Accessibility',
  'questions': 'Question writing',
  'bloom': 'Bloom balance',
  'coverage': 'Coverage',
  'redundancy': 'Redundancy',
  'prerequisites': 'Prerequisite order',
  'alignment': 'Alignment',
  'readability': 'Readability',
};

const auditTiers = {
  'well_supported': 'Well supported',
  'rule_based': 'Rule-based',
  'moderate': 'Moderate',
  'experimental': 'Experimental',
  'informational': 'Information',
};

/// `AuditRunOut`: the latest audit.
class AuditRun {
  const AuditRun({
    required this.id,
    required this.kcVersion,
    required this.ranAt,
    required this.total,
    required this.reviewed,
    required this.skipped,
    required this.findings,
    required this.resolved,
  });

  final String id;
  final int kcVersion;
  final String ranAt;
  final int total;
  final int reviewed;
  final List<String> skipped;
  final List<AuditFinding> findings;
  final List<String> resolved;

  static const fields = [
    'id',
    'course',
    'kc_version',
    'ran_at',
    'ran_by',
    'counts',
    'total',
    'reviewed',
    'skipped',
    'findings',
    'resolved_since_last',
  ];

  factory AuditRun.fromJson(Map<String, dynamic> json) => AuditRun(
    id: json['id'] as String,
    kcVersion: (json['kc_version'] as int?) ?? 0,
    ranAt: (json['ran_at'] as String?) ?? '',
    total: (json['total'] as int?) ?? 0,
    reviewed: (json['reviewed'] as int?) ?? 0,
    skipped: _strings(json['skipped']),
    findings: [
      for (final f in (json['findings'] as List?) ?? const []) AuditFinding.fromJson(f as Map<String, dynamic>),
    ],
    resolved: [for (final r in (json['resolved_since_last'] as List?) ?? const []) (r as Map)['title'] as String],
  );

  /// "25 Sep" from the timestamp.
  String get date {
    final t = DateTime.tryParse(ranAt)?.toLocal();
    if (t == null) return '';
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    return '${t.day} ${months[t.month - 1]}';
  }
}

/// `AdminUserOut`: an account in the admin list.
class AdminUser {
  const AdminUser({
    required this.username,
    required this.fullName,
    required this.role,
    required this.active,
    required this.sessionKind,
    required this.enrolledCourses,
    required this.ownedCourses,
  });

  final String username;
  final String fullName;
  final String role;
  final bool active;
  final String sessionKind;
  final List<String> enrolledCourses;
  final List<String> ownedCourses;

  static const fields = [
    'username',
    'full_name',
    'role',
    'active',
    'session_kind',
    'created_at',
    'enrolled_courses',
    'owned_courses',
  ];

  factory AdminUser.fromJson(Map<String, dynamic> json) => AdminUser(
    username: json['username'] as String,
    fullName: (json['full_name'] as String?) ?? '',
    role: (json['role'] as String?) ?? 'student',
    active: (json['active'] as bool?) ?? true,
    sessionKind: (json['session_kind'] as String?) ?? 'real',
    enrolledCourses: _strings(json['enrolled_courses']),
    ownedCourses: _strings(json['owned_courses']),
  );

  String get displayName => fullName.trim().isEmpty ? username : fullName.trim();
  bool get isStaff => role == 'teacher' || role == 'admin';
}
