from types import SimpleNamespace

from app.security.ssrf_guard import UnsafeUrlError, make_route_handler


class _Resp:
    def __init__(self, status: int, location: str | None = None):
        self.status = status
        self.headers = {"location": location} if location else {}


class _Route:
    def __init__(self, url: str, resource_type: str, responses: dict[str, _Resp] | None = None):
        self.request = SimpleNamespace(url=url, resource_type=resource_type)
        self._responses = responses or {}
        self.fetched: list[str] = []
        self.outcome: tuple = ()

    def fetch(self, url=None, max_redirects=None):
        assert max_redirects == 0
        self.fetched.append(url)
        return self._responses[url]

    def fulfill(self, response):
        self.outcome = ("fulfill", response)

    def continue_(self):
        self.outcome = ("continue",)

    def abort(self, error_code=None):
        self.outcome = ("abort", error_code)


def _block_internal(url: str) -> None:
    if "internal" in url:
        raise UnsafeUrlError("blocked")


def test_redirect_to_a_blocked_host_is_aborted_before_it_is_fetched():
    route = _Route("https://pub.test/a", "document", {
        "https://pub.test/a": _Resp(302, "https://pub.test/b"),
        "https://pub.test/b": _Resp(302, "http://internal.test/secret"),
    })
    make_route_handler(_block_internal)(route)
    assert route.outcome == ("abort", "blockedbyclient")
    assert "http://internal.test/secret" not in route.fetched


def test_allowed_redirect_chain_is_followed_and_fulfilled():
    final = _Resp(200)
    route = _Route("http://pub.test/a", "document", {
        "http://pub.test/a": _Resp(301, "https://pub.test/a"),
        "https://pub.test/a": _Resp(302, "/careers/"),
        "https://pub.test/careers/": final,
    })
    make_route_handler(_block_internal)(route)
    assert route.outcome == ("fulfill", final)


def test_too_many_redirects_is_aborted():
    loop = {f"https://pub.test/{i}": _Resp(302, f"https://pub.test/{i + 1}") for i in range(20)}
    route = _Route("https://pub.test/0", "document", loop)
    make_route_handler(_block_internal)(route)
    assert route.outcome == ("abort", "blockedbyclient")


def test_subresource_to_a_blocked_host_is_aborted():
    route = _Route("http://internal.test/pixel.gif", "image")
    make_route_handler(_block_internal)(route)
    assert route.outcome == ("abort", "blockedbyclient")


def test_allowed_subresource_is_continued():
    route = _Route("https://cdn.test/app.js", "script")
    make_route_handler(_block_internal)(route)
    assert route.outcome == ("continue",)
