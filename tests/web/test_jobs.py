from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

from app import db
from app.models import Job
from app.web.routes_jobs import _age_days


def make_job(key="k1", title="Engineer", url="https://x.test/1", company="Acme",
             location="Remote", source_name="Acme Board", source_id="src-1", summary="A great role."):
    return Job(key=key, title=title, url=url, company=company, location=location,
               source_name=source_name, source_id=source_id, summary=summary)


def test_age_days_uses_today_when_not_removed():
    first_seen = (datetime.now(UTC) - timedelta(days=5)).isoformat()
    assert _age_days(first_seen, None) == 5


def test_age_days_uses_removed_at_when_present():
    first_seen = datetime(2026, 1, 1, tzinfo=UTC).isoformat()
    removed_at = datetime(2026, 1, 10, tzinfo=UTC).isoformat()
    assert _age_days(first_seen, removed_at) == 9


def test_jobs_page_empty_state(client):
    resp = client.get("/jobs")

    assert resp.status_code == 200
    assert "Jobs" in resp.text


def test_jobs_page_lists_active_job(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job()], db.start_run(conn))

    resp = client.get("/jobs")

    assert resp.status_code == 200
    assert "Acme" in resp.text
    assert "Acme Board" in resp.text
    assert "Engineer" in resp.text
    assert 'href="https://x.test/1"' in resp.text
    assert "A great role." in resp.text
    assert "Not sent" in resp.text


def test_jobs_page_shows_removed_date_and_class_for_a_removed_job(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="k2", source_id="src-2")], db.start_run(conn))
    db.reconcile_jobs(conn, configured_source_ids=set(), succeeded_source_ids={"src-2"}, found_jobs=[])
    removed_at = db.list_jobs(conn)[0]["removed_at"]
    assert removed_at is not None

    resp = client.get("/jobs?removed=removed")

    assert removed_at in resp.text
    assert 'class="removed"' in resp.text


def test_jobs_page_shows_emailed_timestamp(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="k3")], db.start_run(conn))
    db.mark_emailed(conn, ["k3"])
    emailed_at = db.list_jobs(conn)[0]["emailed_at"]

    resp = client.get("/jobs")

    assert emailed_at in resp.text


def test_jobs_page_title_link_opens_in_new_tab_with_icon(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job()], db.start_run(conn))

    resp = client.get("/jobs")

    assert 'target="_blank"' in resp.text
    assert 'rel="noopener noreferrer"' in resp.text
    assert "&#8599;" in resp.text
    assert "(opens in new tab)" in resp.text


def test_jobs_page_internal_nav_link_is_not_target_blank(client):
    resp = client.get("/jobs")

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(resp.text, "html.parser")
    nav_jobs_link = soup.select_one('nav[aria-label="Main"] a[href="/jobs"]')

    assert nav_jobs_link is not None
    assert nav_jobs_link.get("target") is None


def test_jobs_page_second_page_shows_older_jobs(client):
    conn = client.app.state.conn
    jobs = [make_job(key=f"k{i}", title=f"Job {i}") for i in range(30)]
    db.save_jobs(conn, jobs, db.start_run(conn))

    page1 = client.get("/jobs?page=1")
    page2 = client.get("/jobs?page=2")

    assert "Page 1 of 2" in page1.text
    assert "Page 2 of 2" in page2.text


def test_jobs_page_invalid_page_param_clamps_instead_of_erroring(client):
    resp = client.get("/jobs?page=not-a-number")

    assert resp.status_code == 200
    assert "Page 1 of 1" in resp.text


def test_jobs_page_negative_page_param_clamps_to_first_page(client):
    resp = client.get("/jobs?page=-3")

    assert resp.status_code == 200
    assert "Page 1 of 1" in resp.text


def test_jobs_table_has_scoped_headers_and_scroll_wrapper(client):
    resp = client.get("/jobs")

    assert 'scope="col"' in resp.text
    assert 'class="table-scroll"' in resp.text


def test_jobs_page_neutralizes_a_javascript_url(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="k4", url="javascript:alert(1)")], db.start_run(conn))

    resp = client.get("/jobs")

    assert 'href="javascript:alert(1)"' not in resp.text
    assert 'href="#"' in resp.text


def test_nav_includes_jobs_link(client):
    resp = client.get("/jobs")

    assert 'href="/jobs" aria-current="page"' in resp.text


def test_jobs_table_cells_have_data_labels(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job()], db.start_run(conn))

    resp = client.get("/jobs")

    for label in ("Company", "Search name", "Title", "Location", "Date found",
                  "Removed", "Age (days)", "Emailed", "Summary"):
        assert f'data-label="{label}"' in resp.text


def test_jobs_page_sort_by_company_orders_rows(client):
    conn = client.app.state.conn
    run_id = db.start_run(conn)
    db.save_jobs(conn, [make_job(key="a", company="Zeta")], run_id)
    db.save_jobs(conn, [make_job(key="b", company="Acme")], run_id)

    resp = client.get("/jobs?sort=company&dir=asc")

    assert resp.text.index("Acme") < resp.text.index("Zeta")


def test_jobs_page_filters_by_company(client):
    conn = client.app.state.conn
    run_id = db.start_run(conn)
    db.save_jobs(conn, [make_job(key="a", company="Acme")], run_id)
    db.save_jobs(conn, [make_job(key="b", company="Zeta")], run_id)

    resp = client.get("/jobs?company=Acme")

    assert "Acme" in resp.text
    assert "Zeta" not in resp.text


def test_jobs_page_filter_dropdown_lists_distinct_source_names(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="a", source_name="Acme Board")], db.start_run(conn))

    resp = client.get("/jobs")

    assert '<option value="Acme Board"' in resp.text


def test_jobs_page_filter_dropdown_lists_distinct_resolved_locations(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="a", location="Chicago, IL")], db.start_run(conn))
    conn.execute(
        "UPDATE geocoded_locations SET status = 'resolved', display_name = 'Chicago, IL' "
        "WHERE location = 'Chicago, IL'"
    )
    conn.commit()

    resp = client.get("/jobs")

    assert '<option value="Chicago, IL"' in resp.text


def test_jobs_page_location_filter_narrows_results(client):
    conn = client.app.state.conn
    run_id = db.start_run(conn)
    db.save_jobs(conn, [make_job(key="a", title="Chicago Job", location="Chicago, IL")], run_id)
    db.save_jobs(conn, [make_job(key="b", title="Austin Job", location="Austin, TX")], run_id)
    conn.execute(
        "UPDATE geocoded_locations SET status = 'resolved', display_name = 'Chicago, IL' "
        "WHERE location = 'Chicago, IL'"
    )
    conn.commit()

    resp = client.get("/jobs?location=Chicago, IL")

    assert "Chicago Job" in resp.text
    assert "Austin Job" not in resp.text


def test_jobs_page_location_filter_shown_in_clear_filters_check(client):
    resp = client.get("/jobs?location=__unresolved__")
    assert "Clear filters" in resp.text


def test_jobs_map_page_renders(client):
    resp = client.get("/jobs/map")
    assert resp.status_code == 200
    assert "Jobs Map" in resp.text


def test_jobs_map_data_groups_jobs_by_location(client):
    conn = client.app.state.conn
    run_id = db.start_run(conn)
    db.save_jobs(conn, [
        make_job(key="a", title="Job A", location="Chicago, IL"),
        make_job(key="b", title="Job B", location="Chicago, IL"),
    ], run_id)
    conn.execute(
        "UPDATE geocoded_locations SET status = 'resolved', display_name = 'Chicago, IL', "
        "lat = 41.8, lng = -87.6 WHERE location = 'Chicago, IL'"
    )
    conn.commit()

    resp = client.get("/jobs/map/data")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["display_name"] == "Chicago, IL"
    assert data[0]["lat"] == 41.8
    assert {j["key"] for j in data[0]["jobs"]} == {"a", "b"}


def test_jobs_map_data_excludes_unresolved_locations(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="a", location="Remote")], db.start_run(conn))

    resp = client.get("/jobs/map/data")

    assert resp.json() == []


def test_jobs_map_data_respects_filters(client):
    conn = client.app.state.conn
    run_id = db.start_run(conn)
    db.save_jobs(conn, [make_job(key="a", company="Acme", location="Chicago, IL")], run_id)
    db.save_jobs(conn, [make_job(key="b", company="Zeta", location="Chicago, IL")], run_id)
    conn.execute(
        "UPDATE geocoded_locations SET status = 'resolved', display_name = 'Chicago, IL', "
        "lat = 41.8, lng = -87.6 WHERE location = 'Chicago, IL'"
    )
    conn.commit()

    resp = client.get("/jobs/map/data?company=Acme")

    assert [j["key"] for j in resp.json()[0]["jobs"]] == ["a"]


def test_jobs_map_data_hides_not_interested_jobs_by_default(client):
    conn = client.app.state.conn
    run_id = db.start_run(conn)
    db.save_jobs(conn, [
        make_job(key="a", location="Chicago, IL"),
        make_job(key="b", location="Chicago, IL"),
    ], run_id)
    conn.execute(
        "UPDATE geocoded_locations SET status = 'resolved', display_name = 'Chicago, IL', "
        "lat = 41.8, lng = -87.6 WHERE location = 'Chicago, IL'"
    )
    conn.commit()
    db.set_job_status(conn, "b", "not_interested")

    resp = client.get("/jobs/map/data")

    assert {j["key"] for j in resp.json()[0]["jobs"]} == {"a"}


def test_jobs_map_data_shows_not_interested_jobs_when_preference_is_off(client):
    conn = client.app.state.conn
    db.save_preferences(conn, "mon,tue,wed,thu,fri,sat,sun", False, "to@x.test", hide_not_interested_on_map=False)
    run_id = db.start_run(conn)
    db.save_jobs(conn, [
        make_job(key="a", location="Chicago, IL"),
        make_job(key="b", location="Chicago, IL"),
    ], run_id)
    conn.execute(
        "UPDATE geocoded_locations SET status = 'resolved', display_name = 'Chicago, IL', "
        "lat = 41.8, lng = -87.6 WHERE location = 'Chicago, IL'"
    )
    conn.commit()
    db.set_job_status(conn, "b", "not_interested")

    resp = client.get("/jobs/map/data")

    assert {j["key"] for j in resp.json()[0]["jobs"]} == {"a", "b"}


def test_jobs_page_has_map_view_link(client):
    resp = client.get("/jobs")
    assert 'href="/jobs/map"' in resp.text


def test_jobs_page_invalid_sort_does_not_error(client):
    resp = client.get("/jobs?sort=nonsense")

    assert resp.status_code == 200


def test_jobs_page_empty_filter_matches_none_renders_empty_table(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="a", company="Acme")], db.start_run(conn))

    resp = client.get("/jobs?company=NoSuchCompany")

    assert resp.status_code == 200
    assert "Page 1 of 1" in resp.text
    assert 'data-label="Company">Acme' not in resp.text


def test_jobs_page_clear_filters_link_hidden_when_no_filter_active(client):
    resp = client.get("/jobs")
    assert "Clear filters" not in resp.text


def test_jobs_page_clear_filters_link_shown_when_filter_active(client):
    resp = client.get("/jobs?company=Acme")
    assert 'href="/jobs"' in resp.text
    assert "Clear filters" in resp.text


def test_jobs_page_sortable_headers_have_aria_sort_when_active(client):
    resp = client.get("/jobs?sort=company&dir=asc")
    assert 'aria-sort="ascending"' in resp.text


def test_jobs_page_removed_and_emailed_filters_narrow_results(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="a")], db.start_run(conn))
    db.mark_emailed(conn, ["a"])

    company_cell = 'data-label="Company">Acme'
    assert company_cell in client.get("/jobs?emailed=sent").text
    assert company_cell not in client.get("/jobs?emailed=not_sent").text
    assert company_cell in client.get("/jobs?removed=active").text
    assert company_cell not in client.get("/jobs?removed=removed").text


def test_jobs_page_filter_form_preserves_active_sort_via_hidden_fields(client):
    resp = client.get("/jobs?sort=company&dir=asc")

    assert '<input type="hidden" name="sort" value="company">' in resp.text
    assert '<input type="hidden" name="dir" value="asc">' in resp.text


def test_post_job_status_sets_status_and_redirects_with_flash(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="k1")], db.start_run(conn))

    resp = client.post("/jobs/status", data={"key": "k1", "status": "applied"}, follow_redirects=False)

    assert resp.status_code == 303
    location = urlparse(resp.headers["location"])
    assert location.path == "/jobs"
    assert parse_qs(location.query)["flash"] == ["Marked as Applied."]
    rows = {r["key"]: r for r in db.list_jobs(conn)}
    assert rows["k1"]["status"] == "applied"


def test_post_job_status_accepts_not_interested(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="k1")], db.start_run(conn))

    resp = client.post("/jobs/status", data={"key": "k1", "status": "not_interested"}, follow_redirects=False)

    assert resp.status_code == 303
    location = urlparse(resp.headers["location"])
    assert parse_qs(location.query)["flash"] == ["Marked as Not Interested."]
    rows = {r["key"]: r for r in db.list_jobs(conn)}
    assert rows["k1"]["status"] == "not_interested"


def test_post_job_status_clearing_redirects_with_cleared_message(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="k1")], db.start_run(conn))
    db.set_job_status(conn, "k1", "applied")

    resp = client.post("/jobs/status", data={"key": "k1", "status": ""}, follow_redirects=False)

    location = urlparse(resp.headers["location"])
    assert parse_qs(location.query)["flash"] == ["Status cleared."]
    rows = {r["key"]: r for r in db.list_jobs(conn)}
    assert rows["k1"]["status"] is None


def test_post_job_status_invalid_status_returns_400(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="k1")], db.start_run(conn))

    resp = client.post("/jobs/status", data={"key": "k1", "status": "bogus"})

    assert resp.status_code == 400
    rows = {r["key"]: r for r in db.list_jobs(conn)}
    assert rows["k1"]["status"] is None


def test_post_job_status_unknown_key_returns_404(client):
    resp = client.post("/jobs/status", data={"key": "does-not-exist", "status": "applied"})

    assert resp.status_code == 404


def test_jobs_page_shows_status_select_with_current_status_selected(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="k1")], db.start_run(conn))
    db.set_job_status(conn, "k1", "applied")

    resp = client.get("/jobs")

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(resp.text, "html.parser")
    select = soup.select_one('form[action="/jobs/status"] select[name="status"]')
    assert select is not None
    selected = select.select_one("option[selected]")
    assert selected["value"] == "applied"


def test_jobs_page_shows_status_history_entries(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="k1")], db.start_run(conn))
    db.set_job_status(conn, "k1", "applied")
    db.set_job_status(conn, "k1", "rejected")

    resp = client.get("/jobs")

    assert "Applied" in resp.text
    assert "Rejected" in resp.text
    assert "<summary>History</summary>" in resp.text


def test_jobs_page_hides_history_details_when_no_changes(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="k1")], db.start_run(conn))

    resp = client.get("/jobs")

    assert "<summary>History</summary>" not in resp.text


def test_jobs_page_status_filter_shows_only_matching_jobs(client):
    conn = client.app.state.conn
    db.save_jobs(
        conn,
        [make_job(key="k1", title="Applied Job"), make_job(key="k2", title="Other Job")],
        db.start_run(conn),
    )
    db.set_job_status(conn, "k1", "applied")

    resp = client.get("/jobs?status=applied")

    assert "Applied Job" in resp.text
    assert "Other Job" not in resp.text


def test_jobs_page_wraps_first_seen_at_in_a_time_element(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="k1")], db.start_run(conn))
    first_seen_at = db.list_jobs(conn)[0]["first_seen_at"]

    resp = client.get("/jobs")

    assert f'<time datetime="{first_seen_at}">{first_seen_at}</time>' in resp.text


def test_jobs_page_wraps_removed_at_in_a_time_element(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="k2", source_id="src-2")], db.start_run(conn))
    db.reconcile_jobs(conn, configured_source_ids=set(), succeeded_source_ids={"src-2"}, found_jobs=[])
    removed_at = db.list_jobs(conn)[0]["removed_at"]

    resp = client.get("/jobs?removed=removed")

    assert f'<time datetime="{removed_at}">{removed_at}</time>' in resp.text


def test_jobs_page_does_not_wrap_removed_dash_placeholder_in_a_time_element(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="k1")], db.start_run(conn))

    resp = client.get("/jobs")

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(resp.text, "html.parser")
    cell = soup.select_one('td[data-label="Removed"]')
    assert cell.get_text(strip=True) == "—"
    assert cell.find("time") is None


def test_jobs_page_wraps_emailed_at_in_a_time_element(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="k3")], db.start_run(conn))
    db.mark_emailed(conn, ["k3"])
    emailed_at = db.list_jobs(conn)[0]["emailed_at"]

    resp = client.get("/jobs")

    assert f'<time datetime="{emailed_at}">{emailed_at}</time>' in resp.text


def test_jobs_page_wraps_status_history_timestamp_in_a_time_element(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="k1")], db.start_run(conn))
    db.set_job_status(conn, "k1", "applied")
    changed_at = db.get_job_status_history(conn, ["k1"])["k1"][0]["changed_at"]

    resp = client.get("/jobs")

    assert f'<time datetime="{changed_at}">{changed_at}</time>' in resp.text


# --- Active-default filter tests (issue #85) ---

def test_jobs_page_defaults_to_active_only(client):
    conn = client.app.state.conn
    run_id = db.start_run(conn)
    db.save_jobs(conn, [make_job(key="active", title="Active Job", source_id="src-active")], run_id)
    db.save_jobs(conn, [make_job(key="gone", title="Removed Job", source_id="src-gone")], run_id)
    db.reconcile_jobs(
        conn, configured_source_ids={"src-active"}, succeeded_source_ids={"src-gone"}, found_jobs=[],
    )

    resp = client.get("/jobs")

    assert "Active Job" in resp.text
    assert "Removed Job" not in resp.text


def test_jobs_page_active_filter_selected_in_dropdown_by_default(client):
    resp = client.get("/jobs")

    assert '<option value="active" selected>Active</option>' in resp.text


def test_jobs_page_all_status_shows_both_active_and_removed(client):
    conn = client.app.state.conn
    run_id = db.start_run(conn)
    db.save_jobs(conn, [make_job(key="active", title="Active Job", source_id="src-active")], run_id)
    db.save_jobs(conn, [make_job(key="gone", title="Removed Job", source_id="src-gone")], run_id)
    db.reconcile_jobs(
        conn, configured_source_ids={"src-active"}, succeeded_source_ids={"src-gone"}, found_jobs=[],
    )

    resp = client.get("/jobs?removed=")

    assert "Active Job" in resp.text
    assert "Removed Job" in resp.text


def test_jobs_page_clear_filters_hidden_at_default_state(client):
    resp = client.get("/jobs")
    assert "Clear filters" not in resp.text


def test_jobs_page_clear_filters_shown_when_status_overridden_to_all(client):
    resp = client.get("/jobs?removed=")
    assert "Clear filters" in resp.text


def test_jobs_page_clear_filters_shown_when_status_set_to_removed(client):
    resp = client.get("/jobs?removed=removed")
    assert "Clear filters" in resp.text


def test_jobs_map_defaults_to_active_filter(client):
    resp = client.get("/jobs/map")

    assert resp.status_code == 200
    assert '<option value="active" selected>Active</option>' in resp.text


def test_jobs_map_clear_filters_hidden_at_default_state(client):
    resp = client.get("/jobs/map")
    assert "Clear filters" not in resp.text


def test_jobs_map_clear_filters_shown_when_status_overridden_to_all(client):
    resp = client.get("/jobs/map?removed=")
    assert "Clear filters" in resp.text


def test_jobs_map_data_defaults_to_active_only(client):
    conn = client.app.state.conn
    run_id = db.start_run(conn)
    db.save_jobs(conn, [
        make_job(key="active", title="Active Job", location="Chicago, IL", source_id="src-active"),
        make_job(key="gone", title="Removed Job", location="Chicago, IL", source_id="src-gone"),
    ], run_id)
    db.reconcile_jobs(
        conn, configured_source_ids={"src-active"}, succeeded_source_ids={"src-gone"}, found_jobs=[],
    )
    conn.execute(
        "UPDATE geocoded_locations SET status = 'resolved', display_name = 'Chicago, IL', "
        "lat = 41.8, lng = -87.6 WHERE location = 'Chicago, IL'"
    )
    conn.commit()

    resp = client.get("/jobs/map/data")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert {j["key"] for j in data[0]["jobs"]} == {"active"}


def test_jobs_map_data_shows_removed_when_explicitly_requested(client):
    conn = client.app.state.conn
    run_id = db.start_run(conn)
    db.save_jobs(conn, [
        make_job(key="active", title="Active Job", location="Chicago, IL", source_id="src-active"),
        make_job(key="gone", title="Removed Job", location="Chicago, IL", source_id="src-gone"),
    ], run_id)
    db.reconcile_jobs(
        conn, configured_source_ids={"src-active"}, succeeded_source_ids={"src-gone"}, found_jobs=[],
    )
    conn.execute(
        "UPDATE geocoded_locations SET status = 'resolved', display_name = 'Chicago, IL', "
        "lat = 41.8, lng = -87.6 WHERE location = 'Chicago, IL'"
    )
    conn.commit()

    resp = client.get("/jobs/map/data?removed=")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert {j["key"] for j in data[0]["jobs"]} == {"active", "gone"}


def test_jobs_map_data_empty_when_all_jobs_are_removed(client):
    conn = client.app.state.conn
    run_id = db.start_run(conn)
    db.save_jobs(conn, [make_job(key="gone", location="Chicago, IL", source_id="src-gone")], run_id)
    db.reconcile_jobs(
        conn, configured_source_ids=set(), succeeded_source_ids={"src-gone"}, found_jobs=[],
    )
    conn.execute(
        "UPDATE geocoded_locations SET status = 'resolved', display_name = 'Chicago, IL', "
        "lat = 41.8, lng = -87.6 WHERE location = 'Chicago, IL'"
    )
    conn.commit()

    resp = client.get("/jobs/map/data")

    assert resp.status_code == 200
    assert resp.json() == []


# --- Location override endpoint tests (issue #84) ---

def _fake_geocode_response(lat="41.8781136", lon="-87.6297982",
                           display_name="Chicago, IL, USA",
                           city="Chicago", state="Illinois", country="United States"):
    from unittest.mock import Mock
    resp = Mock()
    resp.raise_for_status = Mock()
    resp.json.return_value = [{
        "lat": lat, "lon": lon, "display_name": display_name,
        "address": {"city": city, "state": state, "country": country},
    }]
    return resp


def test_location_override_saves_and_returns_ok(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="k1")], db.start_run(conn))

    from unittest.mock import patch
    with patch("app.geocoding.nominatim.requests.get", return_value=_fake_geocode_response()):
        resp = client.post("/jobs/location-override", data={"key": "k1", "location": "Chicago, IL"})

    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    rows = {r["key"]: r for r in db.list_jobs(conn)}
    assert rows["k1"]["is_overridden"] is True
    assert rows["k1"]["location_override"] == "Chicago, IL"


def test_location_override_clears_when_location_empty(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="k1")], db.start_run(conn))

    from unittest.mock import patch
    with patch("app.geocoding.nominatim.requests.get", return_value=_fake_geocode_response()):
        client.post("/jobs/location-override", data={"key": "k1", "location": "Chicago, IL"})

    resp = client.post("/jobs/location-override", data={"key": "k1", "location": ""})

    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    rows = {r["key"]: r for r in db.list_jobs(conn)}
    assert rows["k1"]["is_overridden"] is False
    assert rows["k1"]["location_override"] is None


def test_location_override_returns_400_when_geocode_returns_none(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="k1")], db.start_run(conn))

    from unittest.mock import Mock, patch
    empty_resp = Mock()
    empty_resp.raise_for_status = Mock()
    empty_resp.json.return_value = []
    with patch("app.geocoding.nominatim.requests.get", return_value=empty_resp):
        resp = client.post("/jobs/location-override", data={"key": "k1", "location": "Nowhere, XX"})

    assert resp.status_code == 400
    assert "resolved" in resp.json()["detail"].lower()


def test_location_override_returns_400_on_geocoder_exception(client):
    """NominatimGeocoder swallows RequestException and returns None, which maps to the same 400."""
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="k1")], db.start_run(conn))

    import requests as _requests
    from unittest.mock import patch
    with patch("app.geocoding.nominatim.requests.get", side_effect=_requests.RequestException("timeout")):
        resp = client.post("/jobs/location-override", data={"key": "k1", "location": "Chicago, IL"})

    assert resp.status_code == 400
    assert "resolved" in resp.json()["detail"].lower()


def test_location_override_returns_400_when_key_missing(client):
    resp = client.post("/jobs/location-override", data={"key": "", "location": "Chicago, IL"})
    assert resp.status_code == 400


def test_location_override_returns_404_for_unknown_job(client):
    from unittest.mock import patch
    with patch("app.geocoding.nominatim.requests.get", return_value=_fake_geocode_response()):
        resp = client.post("/jobs/location-override", data={"key": "no-such-key", "location": "Chicago, IL"})
    assert resp.status_code == 404


def test_location_override_clear_returns_404_for_unknown_job(client):
    resp = client.post("/jobs/location-override", data={"key": "no-such-key", "location": ""})
    assert resp.status_code == 404


def test_jobs_page_shows_pin_button_in_location_cell(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="k1")], db.start_run(conn))

    resp = client.get("/jobs")

    assert "location-override-btn" in resp.text
    assert 'data-key="k1"' in resp.text


def test_jobs_page_shows_override_badge_for_overridden_location(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="k1")], db.start_run(conn))
    db.set_location_override(
        conn, "k1", "Chicago, IL",
        display_name="Chicago, IL, USA", city="Chicago", region="IL", country="US",
        lat=41.8781, lng=-87.6298, provider="nominatim",
    )

    resp = client.get("/jobs")

    assert "location-overridden-badge" in resp.text
    assert "Chicago, IL, USA" in resp.text


def test_jobs_page_shows_override_modal_dialog(client):
    resp = client.get("/jobs")
    assert 'id="location-override-modal"' in resp.text
    assert 'id="location-override-form"' in resp.text


def test_jobs_map_data_shows_is_overridden_false_without_override(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="k1", location="Chicago, IL")], db.start_run(conn))
    conn.execute(
        "UPDATE geocoded_locations SET status = 'resolved', display_name = 'Chicago, IL', "
        "lat = 41.8, lng = -87.6 WHERE location = 'Chicago, IL'"
    )
    conn.commit()

    data = client.get("/jobs/map/data").json()

    job = next(j for j in data[0]["jobs"] if j["key"] == "k1")
    assert job["is_overridden"] is False


def test_jobs_map_data_shows_is_overridden_true_and_override_coords(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="k1", location="Remote")], db.start_run(conn))
    db.set_location_override(
        conn, "k1", "Chicago, IL",
        display_name="Chicago, IL, USA", city="Chicago", region="IL", country="US",
        lat=41.8781, lng=-87.6298, provider="nominatim",
    )

    data = client.get("/jobs/map/data").json()

    assert len(data) == 1
    assert data[0]["lat"] == 41.8781
    job = data[0]["jobs"][0]
    assert job["key"] == "k1"
    assert job["is_overridden"] is True
