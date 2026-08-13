from types import SimpleNamespace

from pydantic import BaseModel

from app.config import (
    GenericHtmlSource,
    GreenhouseSource,
    IndeedSource,
    InforSource,
    LeverSource,
    LinkedInSource,
    Selectors,
)

TYPE_MODELS: dict[str, type[BaseModel]] = {
    "greenhouse": GreenhouseSource,
    "lever": LeverSource,
    "generic_html": GenericHtmlSource,
    "linkedin": LinkedInSource,
    "indeed": IndeedSource,
    "infor": InforSource,
}


def _keywords(raw: str) -> list[str]:
    return [k.strip() for k in raw.split(",") if k.strip()]


def _strip(raw: str) -> str:
    return raw.strip()


def source_from_form(form: dict):
    common = {
        "name": _strip(form["name"]),
        "company": _strip(form.get("company", "")) or None,
        "include_keywords": _keywords(form.get("include_keywords", "")),
        "exclude_keywords": _keywords(form.get("exclude_keywords", "")),
        "type": form["type"],
    }
    if form.get("id"):
        common["id"] = form["id"]

    source_type = form["type"]
    if source_type in ("greenhouse", "lever"):
        if "board_token" in form:
            common["board_token"] = _strip(form["board_token"])
    elif source_type == "generic_html":
        if "url" in form:
            common["url"] = _strip(form["url"])
        common["render_js"] = form.get("render_js") == "on"
        common["selectors"] = Selectors(
            job_card=_strip(form.get("selector_job_card", "")),
            title=_strip(form.get("selector_title", "")),
            link=_strip(form.get("selector_link", "")),
            location=_strip(form.get("selector_location", "")) or None,
        )
    elif source_type == "infor":
        if "infor_url" in form:
            common["url"] = _strip(form["infor_url"])
        if form.get("max_pages"):
            common["max_pages"] = int(form["max_pages"])
    else:
        if "url" in form:
            common["url"] = _strip(form["url"])

    model = TYPE_MODELS[source_type]
    return model.model_validate(common)


def echo_source(form: dict):
    """Build a lenient, unvalidated view of submitted form data so the form
    template can be re-rendered with the user's input preserved after a
    validation error (instead of losing it)."""
    selectors = SimpleNamespace(
        job_card=form.get("selector_job_card", ""),
        title=form.get("selector_title", ""),
        link=form.get("selector_link", ""),
        location=form.get("selector_location") or None,
    )
    url = form.get("infor_url", "") if form.get("type") == "infor" else form.get("url", "")
    return SimpleNamespace(
        id=form.get("id", ""),
        name=form.get("name", ""),
        company=form.get("company") or None,
        type=form.get("type", ""),
        board_token=form.get("board_token", ""),
        url=url,
        render_js=form.get("render_js") == "on",
        selectors=selectors,
        max_pages=form.get("max_pages", ""),
        include_keywords=_keywords(form.get("include_keywords", "")),
        exclude_keywords=_keywords(form.get("exclude_keywords", "")),
    )
