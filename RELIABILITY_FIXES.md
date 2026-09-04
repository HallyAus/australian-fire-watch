# Reliability and alert-delivery behaviour

This integration remains supplementary to official emergency channels. These
changes improve failure handling; they do not certify life-safety reliability.

## Feed failures and entity states

A stale, unavailable or incomplete incident assessment makes the official-warning
binary sensor unavailable, not Off. Retained warning information remains in
attributes. An uncertain empty assessment is not presented as no current warning.
The first missing snapshot retains the previous incident pending confirmation;
resolution still needs two complete, current snapshots.

Current positive evidence from one validated official feed can create or escalate
an alert even when another feed fails. Absence, departure and downgrades require
all configured incident sources to be current. NSW also validates the unfiltered
GeoJSON record count before applying its bushfire-only display/alert filter.
Feed health exposes individual failures rather than hiding them behind a healthy
fallback or a recent cached body.

HTTP responses only replace the last-good cache after structural validation.
Maintenance pages, truncated feature collections and incomplete live CAP records
are failures, not valid empty incident lists. CAP test and exercise messages
remain excluded. Freshness checks distinguish publisher envelope timestamps from
individual incident update timestamps.

## Fire danger and Total Fire Bans

Relative today/tomorrow labels are bound to the validated response's original
publication or acceptance date in Australia/Sydney. An unchanged response or 304
does not move that date. Yesterday's today value cannot become today's value.
A current revalidation can use an explicitly published tomorrow declaration when
that calendar date arrives. Failed requests make current declarations unavailable;
last-known values are labelled separately. Missing data never means no fire ban.

## Warning areas

Alert relevance uses polygon containment and shortest boundary distance where
warning-area geometry is supplied, while preserving marker distance for display.
Holes and disjoint polygons remain separate. A location inside a warning polygon
qualifies even when its representative marker is outside the configured radius.
Invalid geometry remains unknown. These checks do not predict spread or safe routes.

## Notification delivery

Lifecycle records and per-recipient pending messages are persisted together before
sending. Transient delivery failures retry on an independent 30-second timer with
bounded backoff. One successful recipient is not retried because another fails.
Queued work survives restarts, is superseded by newer transitions, and expires
after 15 minutes. Removed recipients are pruned. Ordinary retries require current
relevant evidence; tests remain non-critical and can run without an active feed.

The new notification-delivery problem binary sensor exposes failed and expired
work. Its attributes show pending counts, errors and the last successful service
call. Expiry counts are cumulative. A successful notify service call is not proof
that a phone displayed the message. Delivery is at-least-once across a crash;
stable notification tags limit duplicate display. The independent timer is removed
and active delivery is drained when the entry unloads.

## Validation

Run the original pure unit and packaging suite separately from real Home Assistant
runtime tests, because the former deliberately avoids importing Home Assistant:

```sh
python -m unittest discover -s tests -v
python -m compileall -q custom_components tests integration_tests
python -m pip install -r integration_tests/requirements.txt
python -m pytest -c integration_tests/pytest.ini integration_tests -v
node --check custom_components/australian_fire_watch/frontend/australian-fire-watch-panel.js
```

The pinned runtime harness requires Python 3.14. Production code remains compatible
with the repository's declared Python/Home Assistant baseline. CI additionally
runs HACS and hassfest validation. Runtime tests cover HTTP caching, partial feeds,
entity availability, lifecycle/outbox checkpointing, reload/unload, dates,
geometry, retry/expiry and storage failures. All network and notification fixtures
are synthetic; tests never send a real emergency notification.
