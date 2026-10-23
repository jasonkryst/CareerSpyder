import json
import os
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError
from starlette.datastructures import UploadFile

from app import db, emailer
from app.config import SourcesFile, diff_import
from app.models import JOB_STATUSES
from app.web import ratelimit
from app.web.auth import (
    hash_password,
    password_too_long,
    require_admin,
    require_user,
    start_session,
    verify_password,
)
from app.web.flash import flash_redirect
from app.web.templating import templates
from app.web.validation import fmt_validation_error

_IMPORT_MAX_BYTES = 1 * 1024 * 1024  # 1 MB

router = APIRouter()


def _str_field(form: dict, key: str) -> str:
    value = form[key]
    if not isinstance(value, str):
        raise HTTPException(status_code=400, detail=f"{key} must be a text field")
    return value


DAY_CODES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
MAX_DIGEST_RECIPIENTS = 5


def _str_list_field(form, key: str) -> list[str]:
    values = form.getlist(key)
    for value in values:
        if not isinstance(value, str):
            raise HTTPException(status_code=400, detail=f"{key} must be text fields")
    return values


def _split_emails(raw: str | None) -> list[str]:
    return [addr.strip() for addr in (raw or "").split(",") if addr.strip()]


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _is_valid_email(addr: str) -> bool:
    return bool(EMAIL_RE.match(addr))


@router.get("/settings", response_class=HTMLResponse)
def settings_redirect(current_user: dict = Depends(require_user)):
    if current_user["role"] == "admin":
        return RedirectResponse(url="/settings/email")
    return RedirectResponse(url="/settings/preferences")


@router.get("/settings/email", response_class=HTMLResponse)
def show_settings(
    request: Request,
    current_user: dict = Depends(require_admin),
):
    with request.app.state.pool.connection() as conn:
        settings = db.get_settings(conn, current_user["id"])
    return templates.TemplateResponse(request, "settings_email.html", {"settings": settings})


@router.post("/settings/email")
async def save_settings(
    request: Request,
    current_user: dict = Depends(require_admin),
):
    form = dict((await request.form()).items())
    with request.app.state.pool.connection() as conn:
        db.save_settings(
            conn, current_user["id"],
            _str_field(form, "smtp_host"), int(_str_field(form, "smtp_port")), _str_field(form, "smtp_user"),
            _str_field(form, "email_from"),
        )
    return flash_redirect("/settings/email", "Email settings saved.")


@router.post("/settings/email/test")
def test_email(
    request: Request,
    current_user: dict = Depends(require_admin),
):
    if not ratelimit.check(f"test-email:{current_user['id']}", 3, 600):
        return flash_redirect("/settings/email", "Rate limit reached — wait a few minutes before trying again.")
    with request.app.state.pool.connection() as conn:
        settings = db.get_settings(conn, current_user["id"])
    if not settings or not settings.get("smtp_host"):
        return flash_redirect("/settings/email", "Configure email settings first.")
    smtp_password = os.environ.get("SMTP_PASSWORD", "")
    if not smtp_password:
        return flash_redirect("/settings/email", "SMTP_PASSWORD environment variable is not set.")
    recipients = _split_emails(settings["email_to"])
    if not recipients:
        recipients = [settings["email_from"]]
    try:
        emailer.send_email(
            smtp_host=settings["smtp_host"],
            smtp_port=int(settings["smtp_port"]),
            smtp_user=settings["smtp_user"],
            smtp_password=smtp_password,
            email_from=settings["email_from"],
            email_to=recipients,
            subject="CareerSpyder — test email",
            html_body="<p>This is a test email from CareerSpyder. Your email configuration is working.</p>",
        )
    except Exception as exc:  # noqa: BLE001
        return flash_redirect("/settings/email", f"Test email failed: {exc}")
    return flash_redirect("/settings/email", "Test email sent successfully.")


@router.get("/settings/data", response_class=HTMLResponse)
def show_settings_data(
    request: Request,
    current_user: dict = Depends(require_user),
):
    return templates.TemplateResponse(request, "settings_data.html", {})


@router.get("/settings/preferences", response_class=HTMLResponse)
def show_settings_preferences(
    request: Request,
    current_user: dict = Depends(require_user),
):
    with request.app.state.pool.connection() as conn:
        settings = db.get_settings(conn, current_user["id"])
    email_days_selected = set((settings["email_days"] if settings else "").split(","))
    email_to_list = _split_emails(settings["email_to"] if settings else "") or [""]
    digest_exclude_statuses_set = set(
        (settings["digest_exclude_statuses"] if settings else "").split(",")
    ) - {""}
    return templates.TemplateResponse(
        request, "settings_preferences.html",
        {
            "settings": settings,
            "email_days_selected": email_days_selected,
            "email_to_list": email_to_list,
            "digest_exclude_statuses_set": digest_exclude_statuses_set,
        },
    )


@router.post("/settings/preferences")
async def save_preferences(
    request: Request,
    current_user: dict = Depends(require_user),
):
    form = await request.form()
    selected_days = set(_str_list_field(form, "email_days")) & set(DAY_CODES)
    email_days = ",".join(day for day in DAY_CODES if day in selected_days)
    resend_jobs = "resend_jobs" in form
    hide_not_interested_on_map = "hide_not_interested_on_map" in form
    send_weekly_checkin = "send_weekly_checkin" in form
    submitted_emails = [addr.strip() for addr in _str_list_field(form, "email_to") if addr.strip()]

    raw_max = form.get("digest_max_per_company")
    try:
        digest_max_per_company = max(0, int(raw_max) if isinstance(raw_max, str) else 0)
    except ValueError:
        digest_max_per_company = 0

    raw_exclude = set(_str_list_field(form, "digest_exclude_statuses")) & set(JOB_STATUSES)
    digest_exclude_statuses = ",".join(s for s in JOB_STATUSES if s in raw_exclude)

    if len(submitted_emails) > MAX_DIGEST_RECIPIENTS:
        with request.app.state.pool.connection() as conn:
            settings = db.get_settings(conn, current_user["id"])
        return templates.TemplateResponse(
            request, "settings_preferences.html",
            {
                "settings": settings,
                "email_days_selected": selected_days,
                "email_to_list": submitted_emails or [""],
                "digest_exclude_statuses_set": raw_exclude,
                "error": f"Digests can go to at most {MAX_DIGEST_RECIPIENTS} addresses.",
            },
            status_code=400,
        )

    invalid = [addr for addr in submitted_emails if not _is_valid_email(addr)]
    if invalid:
        with request.app.state.pool.connection() as conn:
            settings = db.get_settings(conn, current_user["id"])
        digest_exclude_statuses_set = raw_exclude
        return templates.TemplateResponse(
            request, "settings_preferences.html",
            {
                "settings": settings,
                "email_days_selected": selected_days,
                "email_to_list": submitted_emails or [""],
                "digest_exclude_statuses_set": digest_exclude_statuses_set,
                "error": f"Invalid email address: {invalid[0]}",
            },
            status_code=400,
        )

    email_to = ",".join(submitted_emails)
    with request.app.state.pool.connection() as conn:
        db.save_preferences(
            conn, current_user["id"], email_days, resend_jobs, email_to, hide_not_interested_on_map,
            digest_max_per_company=digest_max_per_company,
            digest_exclude_statuses=digest_exclude_statuses,
            send_weekly_checkin=send_weekly_checkin,
        )
    return flash_redirect("/settings/preferences", "Preferences saved.")


@router.post("/settings/data/clear-cache")
def clear_cache(
    request: Request,
    current_user: dict = Depends(require_user),
):
    with request.app.state.pool.connection() as conn:
        db.clear_jobs(conn, current_user["id"])
    return flash_redirect(
        "/settings/data",
        "Job cache cleared. The next run will re-report every currently known job as new.",
    )


DEFAULT_PREFERENCES = {
    "email_days": [], "resend_jobs": False, "email_to": [], "hide_not_interested_on_map": True,
    "digest_max_per_company": 0, "digest_exclude_statuses": [], "send_weekly_checkin": False,
}


def _export_payload(conn, user_id: str) -> dict:
    sources = db.list_sources(conn, user_id)
    settings = db.get_settings(conn, user_id)
    if settings is None:
        preferences = dict(DEFAULT_PREFERENCES)
    else:
        preferences = {
            "email_days": [d for d in settings["email_days"].split(",") if d],
            "resend_jobs": settings["resend_jobs"],
            "email_to": [a for a in settings["email_to"].split(",") if a],
            "hide_not_interested_on_map": settings["hide_not_interested_on_map"],
            "digest_max_per_company": settings["digest_max_per_company"],
            "digest_exclude_statuses": [
                s for s in (settings["digest_exclude_statuses"] or "").split(",") if s
            ],
            "send_weekly_checkin": settings["send_weekly_checkin"],
        }
    return {"sources": [s.model_dump() for s in sources], "preferences": preferences}


def _parse_preferences_import(data: dict) -> tuple[str, bool, str, bool, int, str, bool] | None:
    preferences = data.get("preferences")
    if preferences is None:
        return None

    raw_days = preferences.get("email_days")
    days = raw_days if isinstance(raw_days, list) else []
    selected_days = {d for d in days if isinstance(d, str)} & set(DAY_CODES)
    email_days = ",".join(day for day in DAY_CODES if day in selected_days)

    resend_jobs = preferences.get("resend_jobs")
    if not isinstance(resend_jobs, bool):
        resend_jobs = False

    raw_emails = preferences.get("email_to")
    emails = raw_emails if isinstance(raw_emails, list) else []
    valid = [
        addr.strip() for addr in emails
        if isinstance(addr, str) and addr.strip() and _is_valid_email(addr.strip())
    ]
    email_to = ",".join(valid[:MAX_DIGEST_RECIPIENTS])

    hide_not_interested_on_map = preferences.get("hide_not_interested_on_map")
    if not isinstance(hide_not_interested_on_map, bool):
        hide_not_interested_on_map = True

    digest_max_per_company = preferences.get("digest_max_per_company")
    if not isinstance(digest_max_per_company, int) or digest_max_per_company < 0:
        digest_max_per_company = 0

    raw_statuses = preferences.get("digest_exclude_statuses")
    if isinstance(raw_statuses, list):
        digest_exclude_statuses = ",".join(
            s for s in JOB_STATUSES if s in {x for x in raw_statuses if isinstance(x, str)}
        )
    else:
        digest_exclude_statuses = ""

    send_weekly_checkin = preferences.get("send_weekly_checkin")
    if not isinstance(send_weekly_checkin, bool):
        send_weekly_checkin = False

    return (
        email_days, resend_jobs, email_to, hide_not_interested_on_map, digest_max_per_company,
        digest_exclude_statuses, send_weekly_checkin,
    )


@router.get("/settings/data/export")
def export_settings(
    request: Request,
    current_user: dict = Depends(require_user),
):
    with request.app.state.pool.connection() as conn:
        payload = json.dumps(_export_payload(conn, current_user["id"]), indent=2)
    return Response(
        content=payload,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="settings.json"'},
    )


_PREFERENCE_LABELS = {
    "email_days": "Check days", "resend_jobs": "Resend jobs",
    "email_to": "Digest recipients", "hide_not_interested_on_map": "Hide Not Interested on map",
    "digest_max_per_company": "Max jobs per company", "digest_exclude_statuses": "Excluded statuses",
    "send_weekly_checkin": "Weekly check-in email",
}


def _preference_diff(existing_settings, parsed) -> list[dict]:
    """Changed-keys-only diff between stored settings and a parsed import
    tuple, for the import preview. Returns [] when the file has no
    preferences section at all (nothing would change)."""
    if parsed is None:
        return []
    (
        email_days, resend_jobs, email_to, hide_not_interested_on_map,
        digest_max_per_company, digest_exclude_statuses, send_weekly_checkin,
    ) = parsed
    new = {
        "email_days": email_days, "resend_jobs": resend_jobs, "email_to": email_to,
        "hide_not_interested_on_map": hide_not_interested_on_map,
        "digest_max_per_company": digest_max_per_company,
        "digest_exclude_statuses": digest_exclude_statuses,
        "send_weekly_checkin": send_weekly_checkin,
    }
    old = existing_settings or {}
    changes = []
    for key, label in _PREFERENCE_LABELS.items():
        old_value = old.get(key) if existing_settings is not None else None
        if old_value != new[key]:
            changes.append({"label": label, "old": old_value, "new": new[key]})
    return changes


@router.post("/settings/data/import")
async def import_settings(
    request: Request,
    current_user: dict = Depends(require_user),
):
    form = await request.form()
    force = request.query_params.get("force") == "1" or form.get("force") == "1"
    confirmed = form.get("confirmed") == "1"

    if confirmed:
        raw = str(form.get("sources_json") or "").encode("utf-8")
    else:
        upload = form.get("file")
        if not isinstance(upload, UploadFile) or not upload.filename:
            return templates.TemplateResponse(
                request, "settings_data.html", {"error": "Choose a file to import."}, status_code=400,
            )
        raw = await upload.read()

    # Starlette's own Request.form() already caps any single field (so also
    # "sources_json" on the confirm path, not just the uploaded file) at 1 MiB
    # by default and turns an oversized one into HTTPException(400) before this
    # line ever runs. This check stays as explicit, resilient defense-in-depth
    # -- it's one coherent limit applied by this route's own logic rather than
    # one path depending on an unstated framework default -- and it's what
    # produces the friendlier themed error on the upload path.
    if len(raw) > _IMPORT_MAX_BYTES:
        return templates.TemplateResponse(
            request, "settings_data.html",
            {"error": "Import file is too large (max 1 MB)."},
            status_code=413,
        )

    try:
        data = json.loads(raw)
        sources = SourcesFile.model_validate(data).sources
    except json.JSONDecodeError as exc:
        return templates.TemplateResponse(
            request, "settings_data.html", {"error": f"Import failed: {exc}"}, status_code=400,
        )
    except ValidationError as exc:
        return templates.TemplateResponse(
            request, "settings_data.html",
            {"error": f"Import failed: {fmt_validation_error(exc)}"}, status_code=400,
        )

    parsed_preferences = _parse_preferences_import(data)

    if not force and not confirmed:
        with request.app.state.pool.connection() as conn:
            existing_sources = db.list_sources(conn, current_user["id"])
            existing_settings = db.get_settings(conn, current_user["id"])
        diff = diff_import(existing_sources, sources)
        pref_diff = _preference_diff(existing_settings, parsed_preferences)
        return templates.TemplateResponse(request, "settings_data.html", {
            "preview": {
                "diff": diff, "pref_diff": pref_diff,
                "sources_json": json.dumps(data),
                "added_count": len(diff["added"]), "updated_count": len(diff["updated"]),
                "unchanged_count": len(diff["unchanged"]),
            },
        })

    with request.app.state.pool.connection() as conn:
        count = db.import_sources(conn, current_user["id"], sources)
        if parsed_preferences is not None:
            (
                email_days, resend_jobs, email_to, hide_not_interested_on_map, digest_max,
                digest_excl, send_weekly_checkin,
            ) = parsed_preferences
            db.save_preferences(
                conn, current_user["id"], email_days, resend_jobs, email_to, hide_not_interested_on_map,
                digest_max_per_company=digest_max, digest_exclude_statuses=digest_excl,
                send_weekly_checkin=send_weekly_checkin,
            )

    redirect_message = f"Imported {count} source(s)."
    if parsed_preferences is not None:
        redirect_message = f"Imported {count} source(s) and preferences."
    return flash_redirect("/settings/data", redirect_message)


@router.get("/settings/account", response_class=HTMLResponse)
def account_settings(
    request: Request,
    current_user: dict = Depends(require_user),
):
    return templates.TemplateResponse(request, "settings_account.html", {})


@router.post("/settings/account/password")
async def change_password(
    request: Request,
    current_user: dict = Depends(require_user),
):
    def _error(msg: str) -> HTMLResponse:
        return templates.TemplateResponse(
            request, "settings_account.html",
            {"error": msg},
            status_code=400,
        )

    if not ratelimit.check(f"change-password:{current_user['id']}", 10, 900):
        return templates.TemplateResponse(
            request, "settings_account.html",
            {"error": "Too many attempts. Please wait a few minutes and try again."},
            status_code=429,
        )

    form = dict((await request.form()).items())
    current_password = str(form.get("current_password") or "")
    new_password = str(form.get("new_password") or "")
    new_password_confirm = str(form.get("new_password_confirm") or "")

    with request.app.state.pool.connection() as conn:
        user_with_hash = db.get_user_by_id_with_hash(conn, current_user["id"])

    current_ok = user_with_hash is not None and await run_in_threadpool(
        verify_password, current_password, user_with_hash["password_hash"],
    )
    if not current_ok:
        return _error("Current password is incorrect.")
    if len(new_password) < 8:
        return _error("New password must be at least 8 characters.")
    if password_too_long(new_password):
        return _error("New password must be at most 72 bytes.")
    if new_password != new_password_confirm:
        return _error("New passwords do not match.")

    new_hash = await run_in_threadpool(hash_password, new_password)
    with request.app.state.pool.connection() as conn:
        db.update_password(conn, current_user["id"], new_hash)
        refreshed = db.get_user_by_id_with_hash(conn, current_user["id"])
        if refreshed is not None:
            start_session(request, refreshed)

    return flash_redirect("/settings/account", "Password updated.")
