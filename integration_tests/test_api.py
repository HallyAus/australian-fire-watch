"""Exercise the actual HTTP cache with deterministic in-memory responses."""
from custom_components.australian_fire_watch.api import OfficialFeedClient
from custom_components.australian_fire_watch.parsers import parse_geojson

GOOD = b'{"type":"FeatureCollection","features":[]}'


class Body:
    def __init__(self, body):
        self.body = body

    async def iter_chunked(self, size):
        yield self.body


class Response:
    def __init__(self, status, body=b"", etag="fixture-old", modified=None):
        self.status = status
        self.headers = {"ETag": etag}
        if modified:
            self.headers["Last-Modified"] = modified
        self.content = Body(body)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class Session:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def get(self, url, headers):
        self.requests.append(dict(headers))
        return self.responses.pop(0)


async def test_bad_200_preserves_good_body_and_validators():
    session = Session(Response(200, GOOD), Response(200, b"<html>Maintenance</html>", "bad-new"))
    client = OfficialFeedClient(session)
    first = await client.async_fetch("fixture", "https://example.invalid", validator=parse_geojson)
    bad = await client.async_fetch("fixture", "https://example.invalid", validator=parse_geojson)
    assert first.response_received
    assert not bad.response_received
    assert bad.body == GOOD and bad.etag == "fixture-old" and bad.status == "retained"
    assert bad.fetched_at == first.fetched_at
    assert session.requests[1]["If-None-Match"] == "fixture-old"


async def test_304_revalidates_without_redating_content():
    client = OfficialFeedClient(Session(Response(200, GOOD), Response(304)))
    first = await client.async_fetch("fixture", "https://example.invalid", validator=parse_geojson)
    second = await client.async_fetch("fixture", "https://example.invalid", validator=parse_geojson)
    assert second.response_received and second.not_modified
    assert second.changed_at == first.changed_at and second.body == first.body


async def test_http_failure_preserves_accepted_body():
    client = OfficialFeedClient(Session(Response(200, GOOD), Response(503)))
    await client.async_fetch("fixture", "https://example.invalid", validator=parse_geojson)
    bad = await client.async_fetch("fixture", "https://example.invalid", validator=parse_geojson)
    assert bad.body == GOOD and not bad.response_received


async def test_identical_body_does_not_move_publication_date():
    client = OfficialFeedClient(Session(Response(200, GOOD), Response(200, GOOD)))
    first = await client.async_fetch("fixture", "https://example.invalid", validator=parse_geojson)
    second = await client.async_fetch("fixture", "https://example.invalid", validator=parse_geojson)
    assert second.changed_at == first.changed_at


async def test_republication_last_modified_moves_date_even_when_body_identical():
    client = OfficialFeedClient(Session(
        Response(200, GOOD, modified="Fri, 04 Sep 2026 02:00:00 GMT"),
        Response(200, GOOD, modified="Sat, 05 Sep 2026 02:00:00 GMT"),
    ))
    first = await client.async_fetch("fixture", "https://example.invalid", validator=parse_geojson)
    second = await client.async_fetch("fixture", "https://example.invalid", validator=parse_geojson)
    assert second.changed_at > first.changed_at


async def test_incomplete_valid_xml_cannot_replace_cache():
    from types import SimpleNamespace
    client = OfficialFeedClient(Session(Response(200, GOOD), Response(200, b"<distribution/>")))
    await client.async_fetch("fixture", "https://example.invalid", validator=parse_geojson)
    second = await client.async_fetch("fixture", "https://example.invalid", validator=lambda body: SimpleNamespace(metadata={"complete": False}))
    assert not second.response_received and second.body == GOOD
