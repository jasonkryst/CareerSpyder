from app.web.pagination import paginate


def test_middle_page_computes_correct_offset():
    result = paginate(total=100, page=3, page_size=25)

    assert result.page == 3
    assert result.offset == 50
    assert result.total_pages == 4
    assert result.has_prev is True
    assert result.has_next is True


def test_page_zero_clamps_to_one():
    result = paginate(total=100, page=0, page_size=25)

    assert result.page == 1
    assert result.offset == 0
    assert result.has_prev is False


def test_negative_page_clamps_to_one():
    result = paginate(total=100, page=-5, page_size=25)

    assert result.page == 1


def test_non_numeric_page_clamps_to_one():
    result = paginate(total=100, page="not-a-number", page_size=25)

    assert result.page == 1


def test_page_beyond_last_clamps_to_last_page():
    result = paginate(total=100, page=999, page_size=25)

    assert result.page == 4
    assert result.has_next is False


def test_empty_total_has_one_page():
    result = paginate(total=0, page=1, page_size=25)

    assert result.total_pages == 1
    assert result.page == 1
    assert result.has_prev is False
    assert result.has_next is False
