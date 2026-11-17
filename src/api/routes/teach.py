"""The Teacher area. Every route needs a teacher or admin (403 for students); course routes
also need the caller to own the course (or be an admin)."""

from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile

from src.api import deps
from src.api.schemas import (AnalyticsOverviewOut, ChatTopicsOut, ChatTopicsResultOut, ExplainerOut,
                             ObjectiveDetailOut, AuditEstimateOut, AuditFindingOut, AuditRunOut, AuditRunSummaryOut, DecisionIn,
                             CourseCreateIn, CourseMetaOut, DraftIn, DraftOut, IssuesOut, JobIn, JobOut,
                             KCDiffOut, KCImportOut, KCOverviewOut, KCRowsIn, MaterialsFolderOut, MaterialsSourceIn,
                             MaterialsSourceOut, PlanIn, PlanOut, PreviewSessionOut,
                             PreviewTurnOut, ProbeOut, PublishIn, PublishOut, SyncPreviewOut, TeachCourseOut,
                             UploadOut, VideoIn, VideoMoveIn, VideoOut, VideosOverviewOut)
from src.onboarding.materials_source import available_subfolders
from src.services.container import Services
from src.services.errors import InvalidInput, NotFound

MAX_SHEET_BYTES = 20 * 1024 * 1024
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

router = APIRouter(prefix="/teach", tags=["teach"], dependencies=[Depends(deps.require_staff)])


def _summary(code: str, svc: Services) -> TeachCourseOut:
    model = svc.registry.kc_model(code) or {}
    weeks = list(model.get("week_navigation", {}).values())
    los = [lo for w in weeks for lo in w.get("learning_objectives", [])]
    meta = svc.setup.meta(code)
    return TeachCourseOut(
        code=code, name=svc.registry.profile(code).name or code, owners=svc.staff.owners(code),
        managed=meta is not None, uploads=len(svc.setup.uploads(code)), active_job=svc.jobs.active(code),
        has_kc_model=bool(model), has_content=svc.registry.has_vector_store(code),
        weeks=len(weeks) or (meta or {}).get("weeks", 0), learning_objectives=len(los),
        granular_objectives=sum(len(lo.get("granular_objectives", [])) for lo in los),
    )


# ---------------------------------------------------------------------------- courses


@router.get("/courses", response_model=list[TeachCourseOut])
def my_courses(user: str = Depends(deps.current_user), svc: Services = Depends(deps.services)):
    """The courses the caller owns; for an admin, every course (installed, set up or owned)."""
    if svc.staff.role(user) == "admin":
        codes = sorted(set(svc.courses.available()) | set(svc.setup.managed_courses())
                       | {c for u in svc.staff.users() for c in u["owned_courses"]})
    else:
        codes = svc.staff.owned_courses(user)
    return [_summary(code, svc) for code in codes]


@router.post("/courses", response_model=CourseMetaOut, status_code=201)
def create_course(body: CourseCreateIn, user: str = Depends(deps.current_user), svc: Services = Depends(deps.services)):
    """Set up a new course. A teacher who creates it owns it. Students don't see it until a
    KC model is published for it."""
    return svc.setup.create(user, body.code, body.name, body.discipline, body.allows_code, body.code_language,
                            body.weeks)


@router.get("/courses/{code}", response_model=TeachCourseOut)
def course(code: str = Depends(deps.teacher_course), svc: Services = Depends(deps.services)):
    return _summary(code, svc)


@router.get("/courses/{code}/objectives", response_model=PlanOut)
def objectives(code: str = Depends(deps.teacher_course), svc: Services = Depends(deps.services)):
    plan = svc.setup.plan(code)
    if plan is None:
        raise NotFound("No learning objectives yet.")
    return plan


@router.put("/courses/{code}/objectives", response_model=PlanOut)
def set_objectives(body: PlanIn, code: str = Depends(deps.teacher_course), user: str = Depends(deps.current_user),
                   svc: Services = Depends(deps.services)):
    """The weekly learning objectives the KC model is drafted from (every week, 1-12 each)."""
    return svc.setup.set_plan(user, code, [w.model_dump() for w in body.weeks])


# ---------------------------------------------------------------------------- uploads


@router.get("/courses/{code}/uploads", response_model=list[UploadOut])
def uploads(code: str = Depends(deps.teacher_course), svc: Services = Depends(deps.services)):
    return sorted(svc.setup.uploads(code).values(), key=lambda u: ((u.get("week") or 0), u["name"].lower()))


@router.post("/courses/{code}/uploads", response_model=list[UploadOut], status_code=201)
def add_uploads(files: List[UploadFile] = File(..., description="One or more course files"),
                week: Optional[int] = Form(None, description="The week they belong to (optional)"),
                kind: Optional[str] = Form(None, description="Lecture, Lab, Reading, Assignment, Transcript, "
                                                             "Video, Audio or Other (default: from the file type)"),
                code: str = Depends(deps.teacher_course), user: str = Depends(deps.current_user),
                svc: Services = Depends(deps.services)):
    """Upload course materials: PDF, DOCX, PPTX, XLSX, MD, TXT, IPYNB, MP3, MP4, WAV; at most
    50 MB each and 1 GB per course. A file with the same name replaces the old one. All
    files are checked before any is kept, file by file: the first bad file stops the rest."""
    return [svc.setup.add_upload(user, code, f.filename or "", f.file, week=week, kind=kind) for f in files]


@router.delete("/courses/{code}/uploads/{name}", status_code=204)
def delete_upload(name: str, code: str = Depends(deps.teacher_course), user: str = Depends(deps.current_user),
                  svc: Services = Depends(deps.services)):
    svc.setup.delete_upload(user, code, name)
    return Response(status_code=204)


# ---------------------------------------------------------------------------- linked materials source


@router.get("/materials-folders", response_model=list[MaterialsFolderOut])
def materials_folders():
    """Subfolders under LEA_COURSE_MATERIALS_ROOT, for the "link a folder" picker."""
    return [MaterialsFolderOut(name=n) for n in available_subfolders()]


@router.get("/courses/{code}/materials-source", response_model=Optional[MaterialsSourceOut])
def materials_source(code: str = Depends(deps.teacher_course), svc: Services = Depends(deps.services)):
    return svc.setup.materials_source(code)


@router.post("/courses/{code}/materials-source", response_model=MaterialsSourceOut, status_code=201)
def link_materials_source(body: MaterialsSourceIn, code: str = Depends(deps.teacher_course),
                          user: str = Depends(deps.current_user), svc: Services = Depends(deps.services)):
    """Link a read-only folder under LEA_COURSE_MATERIALS_ROOT. A Build job then ingests its
    files alongside any uploads -- see GET .../materials-source/sync-preview."""
    return svc.setup.link_materials_source(user, code, body.type, body.path)


@router.delete("/courses/{code}/materials-source", status_code=204)
def unlink_materials_source(code: str = Depends(deps.teacher_course), user: str = Depends(deps.current_user),
                            svc: Services = Depends(deps.services)):
    """Stop tracking the link. Files already ingested from it stay as ordinary uploads."""
    svc.setup.unlink_materials_source(user, code)
    return Response(status_code=204)


@router.get("/courses/{code}/materials-source/sync-preview", response_model=SyncPreviewOut)
def materials_source_sync_preview(code: str = Depends(deps.teacher_course), svc: Services = Depends(deps.services)):
    """What the next Build job would pick up from the linked folder: each file as new,
    changed, unchanged, removed or rejected (with why). Read-only -- changes nothing."""
    entries = svc.setup.materials_source_status(code)
    counts = {s: sum(1 for e in entries if e["status"] == s)
             for s in ("new", "changed", "unchanged", "removed", "rejected")}
    return SyncPreviewOut(entries=entries, **counts)


# ---------------------------------------------------------------------------- jobs


def _job_for_teacher(job_id: str, user: str, svc: Services) -> dict:
    job = svc.jobs.get(job_id)
    svc.staff.require_teacher(user, job["course"])
    return job


@router.get("/courses/{code}/jobs", response_model=list[JobOut])
def jobs(code: str = Depends(deps.teacher_course), svc: Services = Depends(deps.services)):
    """The course's recent jobs, newest first (without their logs)."""
    return svc.jobs.for_course(code)


@router.post("/courses/{code}/jobs", response_model=JobOut, status_code=201)
def start_job(body: JobIn, code: str = Depends(deps.teacher_course), user: str = Depends(deps.current_user),
              svc: Services = Depends(deps.services)):
    """Prepare an onboarding run and price it. Nothing runs (and nothing is spent) until
    `POST /teach/jobs/{id}/confirm`. One job per course at a time (409 otherwise)."""
    return svc.jobs.create(user, code, body.steps)


@router.get("/jobs/{job_id}", response_model=JobOut)
def job(job_id: str, user: str = Depends(deps.current_user), svc: Services = Depends(deps.services)):
    """Status, progress, estimate, result and the latest log lines. Poll while it runs."""
    return _job_for_teacher(job_id, user, svc)


@router.post("/jobs/{job_id}/confirm", response_model=JobOut)
def confirm_job(job_id: str, user: str = Depends(deps.current_user), svc: Services = Depends(deps.services)):
    """Accept the estimate and queue the job."""
    _job_for_teacher(job_id, user, svc)
    return svc.jobs.confirm(user, job_id)


@router.post("/jobs/{job_id}/cancel", response_model=JobOut)
def cancel_job(job_id: str, user: str = Depends(deps.current_user), svc: Services = Depends(deps.services)):
    """Cancel: at once if it hasn't started, otherwise after the current file."""
    _job_for_teacher(job_id, user, svc)
    return svc.jobs.cancel(user, job_id)


# ---------------------------------------------------------------------------- KC review


@router.get("/courses/{code}/kc", response_model=KCOverviewOut)
def kc_overview(code: str = Depends(deps.teacher_course), svc: Services = Depends(deps.services)):
    """Published versions (the live one marked) and the draft, if any."""
    draft = svc.kc.draft(code)
    return KCOverviewOut(
        published_version=svc.kc.published_version(code), versions=svc.kc.versions(code),
        draft={k: draft[k] for k in ("source", "based_on", "created_at", "updated_at", "saves")} if draft else None)


@router.post("/courses/{code}/kc/draft", response_model=DraftOut, status_code=201)
def kc_create_draft(body: DraftIn, code: str = Depends(deps.teacher_course), user: str = Depends(deps.current_user),
                    svc: Services = Depends(deps.services)):
    """Start the draft from the live model or an onboarding job's draft (409 if a draft
    exists, unless ``replace``)."""
    return svc.kc.create_draft(user, code, body.source, body.replace)


@router.get("/courses/{code}/kc/draft", response_model=DraftOut)
def kc_draft(code: str = Depends(deps.teacher_course), svc: Services = Depends(deps.services)):
    """The draft's rows (one per granular objective) and any problems with them."""
    return svc.kc.view(code)


@router.put("/courses/{code}/kc/draft", response_model=DraftOut)
def kc_save_draft(body: KCRowsIn, code: str = Depends(deps.teacher_course), user: str = Depends(deps.current_user),
                  svc: Services = Depends(deps.services)):
    """Replace the draft's rows. New rows get IDs; nothing is saved if any row has an error."""
    return svc.kc.save_rows(user, code, [r.model_dump() for r in body.rows])


@router.delete("/courses/{code}/kc/draft", status_code=204)
def kc_discard_draft(code: str = Depends(deps.teacher_course), user: str = Depends(deps.current_user),
                     svc: Services = Depends(deps.services)):
    svc.kc.discard(user, code)
    return Response(status_code=204)


@router.post("/courses/{code}/kc/draft/validate", response_model=IssuesOut)
def kc_validate(body: KCRowsIn, code: str = Depends(deps.teacher_course), svc: Services = Depends(deps.services)):
    """Check rows without saving them."""
    return IssuesOut(issues=svc.kc.check(code, [svc.kc.clean(r.model_dump()) for r in body.rows]))


@router.get("/courses/{code}/kc/draft/export", response_class=Response,
            responses={200: {"content": {XLSX: {}}, "description": "The draft (or the live model) as a spreadsheet"}})
def kc_export(code: str = Depends(deps.teacher_course), svc: Services = Depends(deps.services)):
    name = f"{code}_kc_model.xlsx"
    return Response(svc.kc.export(code), media_type=XLSX,
                    headers={"Content-Disposition": f"attachment; filename={name}"})


@router.post("/courses/{code}/kc/draft/import", response_model=KCImportOut)
def kc_import(file: UploadFile = File(..., description="An exported, edited spreadsheet"),
              code: str = Depends(deps.teacher_course), user: str = Depends(deps.current_user),
              svc: Services = Depends(deps.services)):
    """Read an edited spreadsheet into the draft. It is validated first: with any error,
    nothing changes and the problems are listed. Returns the draft and its diff."""
    data = file.file.read(MAX_SHEET_BYTES + 1)
    if len(data) > MAX_SHEET_BYTES:
        raise InvalidInput("That spreadsheet is over 20 MB.")
    return svc.kc.import_sheet(user, code, data)


@router.get("/courses/{code}/kc/diff", response_model=KCDiffOut)
def kc_diff(code: str = Depends(deps.teacher_course), svc: Services = Depends(deps.services)):
    """What publishing the draft would change, and how many students it affects."""
    return svc.kc.diff(code)


@router.post("/courses/{code}/kc/publish", response_model=PublishOut)
def kc_publish(body: PublishIn, code: str = Depends(deps.teacher_course), user: str = Depends(deps.current_user),
               svc: Services = Depends(deps.services)):
    """Publish the draft as the next version: students see it at once. Mastery follows the
    lineage (splits copy it to each part, merges take the mean); retired objectives keep
    their mastery but no longer count."""
    return svc.kc.publish(user, code, body.note)


# ---------------------------------------------------------------------------- preview


@router.post("/courses/{code}/preview", response_model=PreviewSessionOut)
def preview_start(code: str = Depends(deps.teacher_course), user: str = Depends(deps.current_user),
                  svc: Services = Depends(deps.services)):
    """Start or resume "Try as a student": a token for your sandbox student account
    (<you>.preview), enrolled in this course. Everything it does is tagged test and never
    reaches research logs, analytics or exports."""
    return svc.preview.start(user, code)


@router.post("/courses/{code}/preview/reset", status_code=204)
def preview_reset(code: str = Depends(deps.teacher_course), user: str = Depends(deps.current_user),
                  svc: Services = Depends(deps.services)):
    """Forget what the sandbox did in this course (mastery, sessions, chat), to start over."""
    svc.preview.reset(user, code)
    return Response(status_code=204)


@router.get("/courses/{code}/preview/explain", response_model=list[PreviewTurnOut])
def preview_explain(code: str = Depends(deps.teacher_course), user: str = Depends(deps.current_user),
                    svc: Services = Depends(deps.services)):
    """Why LEA did what it did on your latest preview turns, newest first: the objective,
    mastery before and after, grading, the learner model's state, the scaffolding and the
    course content retrieved. Only for your own sandbox; students never receive this."""
    return svc.preview.explanations(user, code)


@router.get("/courses/{code}/preview/probes", response_model=list[ProbeOut])
def preview_probes(week: Optional[int] = Query(None, ge=1, le=52), code: str = Depends(deps.teacher_course),
                   svc: Services = Depends(deps.services)):
    """Things to try in a preview of the week."""
    return svc.preview.probes(code, week)


# ---------------------------------------------------------------------------- content audit


@router.get("/courses/{code}/audit", response_model=Optional[AuditRunOut])
def audit_latest(code: str = Depends(deps.teacher_course), svc: Services = Depends(deps.services)):
    """The latest audit with each finding's decision, what's new since the run before, and
    what that run found that this one doesn't (null before the first run)."""
    return svc.audit.latest(code)


@router.get("/courses/{code}/audit/estimate", response_model=AuditEstimateOut)
def audit_estimate(code: str = Depends(deps.teacher_course), svc: Services = Depends(deps.services)):
    """What running the audit costs (only coverage and redundancy use OpenAI)."""
    return svc.audit.estimate(code)


@router.get("/courses/{code}/audit/runs", response_model=list[AuditRunSummaryOut])
def audit_runs(code: str = Depends(deps.teacher_course), svc: Services = Depends(deps.services)):
    return svc.audit.runs(code)


@router.post("/courses/{code}/audit/runs", response_model=AuditRunOut, status_code=201)
def audit_run(code: str = Depends(deps.teacher_course), user: str = Depends(deps.current_user),
              svc: Services = Depends(deps.services)):
    """Audit the live version: accessibility of the files, question writing, Bloom balance,
    coverage, redundancy, prerequisite order, alignment, readability. Findings are ranked
    (at most 15 per check); earlier decisions carry over."""
    return svc.audit.run(user, code)


@router.put("/courses/{code}/audit/findings/{key}", response_model=AuditFindingOut)
def audit_decide(key: str, body: DecisionIn, code: str = Depends(deps.teacher_course),
                 user: str = Depends(deps.current_user), svc: Services = Depends(deps.services)):
    """Accept or dismiss a finding (with an optional note), or reopen it."""
    return svc.audit.decide(user, code, key, body.status, body.note)


# ---------------------------------------------------------------------------- analytics

Kind = Query("real", pattern="^(real|simulated)$",
             description="real (default) or simulated (seeded students, for trying the screens); never mixed")


@router.get("/courses/{code}/analytics", response_model=AnalyticsOverviewOut)
def analytics(kind: str = Kind, week: Optional[int] = Query(None, ge=1, le=52),
              since: Optional[str] = Query(None, description="ISO date, inclusive"),
              until: Optional[str] = Query(None, description="ISO date, exclusive"),
              code: str = Depends(deps.teacher_course), user: str = Depends(deps.current_user),
              svc: Services = Depends(deps.services)):
    """Each objective's mastery band, students, first-attempt accuracy, attempts to master,
    learning-curve verdict and "needs attention" score (LEA's heuristic, with the factor
    that drove it), most in need first; then usage. Real students only by default; figures
    from fewer than 5 students are withheld."""
    return svc.analytics.overview(user, code, kind, week, since, until)


@router.get("/courses/{code}/analytics/objectives/{go_id}", response_model=ObjectiveDetailOut)
def analytics_objective(go_id: str, kind: str = Kind, code: str = Depends(deps.teacher_course),
                        user: str = Depends(deps.current_user), svc: Services = Depends(deps.services)):
    """One objective: the learning curve, common wrong answers, tutor struggle, chat topics
    and a suggested action."""
    return svc.analytics.detail(user, code, go_id, kind)


@router.get("/courses/{code}/analytics/curves.csv", response_class=Response,
            responses={200: {"content": {"text/csv": {}}, "description": "Aggregated learning curves"}})
def analytics_curves(kind: str = Kind, code: str = Depends(deps.teacher_course),
                     user: str = Depends(deps.current_user), svc: Services = Depends(deps.services)):
    """Learning curves as CSV: objective, opportunity, students, error rate (no per-student rows)."""
    return Response(svc.analytics.curves_csv(user, code, kind), media_type="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={code}_learning_curves.csv"})


@router.get("/courses/{code}/analytics/chat-topics", response_model=ChatTopicsOut)
def analytics_chat_topics(kind: str = Kind, code: str = Depends(deps.teacher_course),
                          svc: Services = Depends(deps.services)):
    """The last grouping of chat questions by topic (if any) and what a new one costs."""
    return svc.analytics.chat_topics(code, kind)


@router.post("/courses/{code}/analytics/chat-topics", response_model=ChatTopicsResultOut)
def analytics_run_chat_topics(kind: str = Kind, code: str = Depends(deps.teacher_course),
                              user: str = Depends(deps.current_user), svc: Services = Depends(deps.services)):
    """Group chat questions by topic and map them to objectives (GPT-4o mini), with a second
    independent pass to report agreement. Only topics asked by 5 or more students are kept."""
    return svc.analytics.run_chat_topics(user, code, kind)


@router.post("/courses/{code}/analytics/objectives/{go_id}/explainer", response_model=ExplainerOut)
def analytics_explainer(go_id: str, code: str = Depends(deps.teacher_course), user: str = Depends(deps.current_user),
                        svc: Services = Depends(deps.services)):
    """Draft a short explanation of the objective from the course material, for the
    teacher to edit. LEA never publishes it."""
    return svc.analytics.explainer(user, code, go_id)


# ---------------------------------------------------------------------------- videos for stuck students


@router.get("/courses/{code}/videos", response_model=VideosOverviewOut)
def videos(code: str = Depends(deps.teacher_course), svc: Services = Depends(deps.services)):
    """Every objective of the live version with the videos chosen for it, and the state of
    automatic YouTube search (paused when its daily quota is used up)."""
    return svc.videos.overview(code)


@router.post("/courses/{code}/videos", response_model=VideoOut, status_code=201)
def add_video(body: VideoIn, code: str = Depends(deps.teacher_course), user: str = Depends(deps.current_user),
              svc: Services = Depends(deps.services)):
    """Add a YouTube video to an objective (up to 5). The video is checked with YouTube, which
    also supplies its title and channel. The tutor shows an objective's videos, in this order,
    to a student who is stuck, instead of searching."""
    return svc.videos.add(user, code, body.go_id, body.url, body.note)


@router.delete("/courses/{code}/videos/{go_id}/{video_id}", status_code=204)
def remove_video(go_id: str, video_id: str, code: str = Depends(deps.teacher_course),
                 user: str = Depends(deps.current_user), svc: Services = Depends(deps.services)):
    svc.videos.remove(user, code, go_id, video_id)
    return Response(status_code=204)


@router.post("/courses/{code}/videos/{go_id}/{video_id}/move", response_model=List[VideoOut])
def move_video(go_id: str, video_id: str, body: VideoMoveIn, code: str = Depends(deps.teacher_course),
               user: str = Depends(deps.current_user), svc: Services = Depends(deps.services)):
    """Move a video up or down in the objective's list; the first three are what students see."""
    return svc.videos.move(user, code, go_id, video_id, -1 if body.direction == "up" else 1)

