from app.models import Job


def apply_keyword_filters(jobs: list[Job], include: list[str], exclude: list[str]) -> list[Job]:
    result = jobs
    if include:
        needles = [k.lower() for k in include]
        result = [j for j in result if any(n in j.title.lower() for n in needles)]
    if exclude:
        needles = [k.lower() for k in exclude]
        result = [j for j in result if not any(n in j.title.lower() for n in needles)]
    return result
