from app.config import (
    GenericHtmlSource,
    GreenhouseSource,
    IndeedSource,
    LeverSource,
    LinkedInSource,
    Selectors,
)

TYPE_MODELS = {
    "greenhouse": GreenhouseSource,
    "lever": LeverSource,
    "generic_html": GenericHtmlSource,
    "linkedin": LinkedInSource,
    "indeed": IndeedSource,
}


def _keywords(raw: str) -> list[str]:
    return [k.strip() for k in raw.split(",") if k.strip()]


def source_from_form(form: dict):
    common = {
        "name": form["name"],
        "company": form.get("company") or None,
        "include_keywords": _keywords(form.get("include_keywords", "")),
        "exclude_keywords": _keywords(form.get("exclude_keywords", "")),
        "type": form["type"],
    }
    if form.get("id"):
        common["id"] = form["id"]

    source_type = form["type"]
    if source_type in ("greenhouse", "lever"):
        if "board_token" in form:
            common["board_token"] = form["board_token"]
    elif source_type == "generic_html":
        if "url" in form:
            common["url"] = form["url"]
        common["render_js"] = form.get("render_js") == "on"
        common["selectors"] = Selectors(
            job_card=form.get("selector_job_card", ""),
            title=form.get("selector_title", ""),
            link=form.get("selector_link", ""),
            location=form.get("selector_location") or None,
        )
    else:
        if "url" in form:
            common["url"] = form["url"]

    model = TYPE_MODELS[source_type]
    return model.model_validate(common)
