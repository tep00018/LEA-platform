/// Videos for stuck students (`/teach/courses/{code}/videos`).
library;

int? _i(Object? v) => (v as num?)?.toInt();

List<Map<String, dynamic>> _list(Object? v) => [for (final e in (v as List?) ?? const []) e as Map<String, dynamic>];

/// The most an objective can have (the API enforces it too).
const maxVideosPerObjective = 5;

/// How many of an objective's videos students see.
const videosShown = 3;

class CuratedVideo {
  const CuratedVideo({
    required this.id,
    required this.url,
    required this.title,
    required this.addedBy,
    required this.addedAt,
    this.channel = '',
    this.note = '',
  });

  final String id;
  final String url;
  final String title;
  final String channel;
  final String note;
  final String addedBy;
  final String addedAt;

  static const fields = ['id', 'url', 'title', 'channel', 'note', 'added_by', 'added_at'];

  factory CuratedVideo.fromJson(Map<String, dynamic> json) => CuratedVideo(
    id: json['id'] as String,
    url: (json['url'] as String?) ?? '',
    title: (json['title'] as String?) ?? 'YouTube video',
    channel: (json['channel'] as String?) ?? '',
    note: (json['note'] as String?) ?? '',
    addedBy: (json['added_by'] as String?) ?? '',
    addedAt: (json['added_at'] as String?) ?? '',
  );

  /// "Added by teacher1 · 12 Sep".
  String get addedLine {
    final date = DateTime.tryParse(addedAt);
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    final when = date == null ? '' : ' · ${date.day} ${months[date.month - 1]}';
    return 'Added by $addedBy$when';
  }
}

class ObjectiveVideos {
  const ObjectiveVideos({
    required this.goId,
    required this.week,
    required this.loId,
    required this.skillName,
    required this.videos,
    required this.studentGets,
    this.helpShownStudents,
  });

  final String goId;
  final int week;
  final String loId;
  final String skillName;
  final List<CuratedVideo> videos;

  /// `curated`, `search` or `links`.
  final String studentGets;

  /// Real students shown video help in the last 30 days: 0 if none, null when 1 to 4 (withheld).
  final int? helpShownStudents;

  static const fields = ['go_id', 'week', 'lo_id', 'skill_name', 'videos', 'student_gets', 'help_shown_students'];

  factory ObjectiveVideos.fromJson(Map<String, dynamic> json) => ObjectiveVideos(
    goId: json['go_id'] as String,
    week: _i(json['week']) ?? 0,
    loId: (json['lo_id'] as String?) ?? '',
    skillName: (json['skill_name'] as String?) ?? '',
    videos: [for (final v in _list(json['videos'])) CuratedVideo.fromJson(v)],
    studentGets: (json['student_gets'] as String?) ?? 'links',
    helpShownStudents: _i(json['help_shown_students']),
  );
}

class VideoSearch {
  const VideoSearch({required this.enabled, required this.cachedSearches, this.quotaPausedUntil});

  final bool enabled;
  final int cachedSearches;

  /// Automatic search is paused until then (Google's daily quota is used up).
  final DateTime? quotaPausedUntil;

  static const fields = ['enabled', 'quota_paused_until', 'cached_searches'];

  factory VideoSearch.fromJson(Map<String, dynamic>? json) => VideoSearch(
    enabled: (json?['enabled'] as bool?) ?? false,
    cachedSearches: _i(json?['cached_searches']) ?? 0,
    quotaPausedUntil: DateTime.tryParse((json?['quota_paused_until'] as String?) ?? ''),
  );

  bool get paused => enabled && quotaPausedUntil != null;

  /// "about 7 hours", "about 40 minutes".
  String pausedFor(DateTime now) {
    final left = quotaPausedUntil?.difference(now.toUtc()) ?? Duration.zero;
    if (left.inMinutes < 60) return 'about ${left.inMinutes.clamp(1, 59)} minutes';
    final hours = (left.inMinutes / 60).round();
    return 'about $hours ${hours == 1 ? 'hour' : 'hours'}';
  }
}

class VideosOverview {
  const VideosOverview({
    required this.course,
    required this.maxPerObjective,
    required this.search,
    required this.curatedObjectives,
    required this.helpWindowDays,
    required this.objectives,
    this.helpShownTimes,
  });

  final String course;
  final int maxPerObjective;
  final VideoSearch search;
  final int curatedObjectives;
  final int helpWindowDays;

  /// Times help was shown to real students in the window; null when fewer than 5 students.
  final int? helpShownTimes;
  final List<ObjectiveVideos> objectives;

  static const fields = [
    'course',
    'max_per_objective',
    'search',
    'curated_objectives',
    'help_window_days',
    'help_shown_times',
    'objectives',
  ];

  factory VideosOverview.fromJson(Map<String, dynamic> json) => VideosOverview(
    course: (json['course'] as String?) ?? '',
    maxPerObjective: _i(json['max_per_objective']) ?? maxVideosPerObjective,
    search: VideoSearch.fromJson(json['search'] as Map<String, dynamic>?),
    curatedObjectives: _i(json['curated_objectives']) ?? 0,
    helpWindowDays: _i(json['help_window_days']) ?? 30,
    helpShownTimes: _i(json['help_shown_times']),
    objectives: [for (final o in _list(json['objectives'])) ObjectiveVideos.fromJson(o)],
  );

  ObjectiveVideos? objective(String goId) => objectives.where((o) => o.goId == goId).firstOrNull;
}
