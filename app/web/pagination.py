from dataclasses import dataclass


@dataclass
class Pagination:
    page: int
    total_pages: int
    offset: int
    has_prev: bool
    has_next: bool


def paginate(total: int, page: object, page_size: int = 25) -> Pagination:
    total_pages = max(1, -(-total // page_size))  # ceil(total / page_size), floored at 1

    try:
        page_num = int(page)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        page_num = 1

    page_num = max(1, min(page_num, total_pages))
    offset = (page_num - 1) * page_size

    return Pagination(
        page=page_num,
        total_pages=total_pages,
        offset=offset,
        has_prev=page_num > 1,
        has_next=page_num < total_pages,
    )
