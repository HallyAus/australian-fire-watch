# NSW Fire Watch contributor guide

This repository is a HACS-installable Home Assistant integration for NSW bush-fire awareness. It is supplementary to official emergency channels and must never describe missing or stale data as safe.

## Architecture

- `custom_components/nsw_fire_watch/`: config flow, official NSW RFS/BOM feed coordinators, normalized models, HA entities/events/services, and the bundled frontend.
- `custom_components/nsw_fire_watch/frontend/`: prebuilt plain JavaScript loaded directly by Home Assistant; no runtime package manager.
- `blueprints/`: optional user-owned alert automations.
- `tests/`: deterministic unit tests. Keep feed parsing and ranking logic pure where possible.

## Safety rules

- Keep official warning level, incident control status, incident type, and proximity as separate fields.
- Unknown/unavailable/stale is never green and never “safe” or “all clear”.
- Reserve red for Emergency Warning or Catastrophic. Do not rely on colour alone.
- Use official source links and timestamps; expose stale age and retain the last good response.
- Do not infer fire spread, evacuation routes, or property safety.
- Notifications must be deduplicated by stable incident ID and lifecycle change; escalation always overrides snooze.
- Never commit Home Assistant `.storage`, coordinates, tokens, service names, or other household data.

## Validation

Run `python -m unittest discover -s tests -v`, compile Python, validate JSON/YAML, and run `ruff`/`mypy` when available. Production installation requires a Home Assistant configuration check before restart.
