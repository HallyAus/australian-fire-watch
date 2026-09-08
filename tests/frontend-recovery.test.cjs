// Deterministic event/timing checks, not browser automation or live HA writes.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');
const source = fs.readFileSync(path.join(__dirname,
  '../custom_components/australian_fire_watch/frontend/australian-fire-watch-panel.js'), 'utf8');

function environment() {
  let clock = 10000;
  let nextId = 0;
  const timers = new Map();
  const intervals = [];
  const registered = new Map();
  const listeners = new Map();
  const documentListeners = new Map();
  const on = (registry, name, fn) => {
    const callbacks = registry.get(name) || [];
    callbacks.push(fn); registry.set(name, callbacks);
  };
  const document = { children: [], visibilityState: 'visible',
    addEventListener: (name, fn) => on(documentListeners, name, fn) };
  const window = {
    location: { origin: 'https://ha.example.invalid' },
    addEventListener: (name, fn) => on(listeners, name, fn),
    setTimeout(fn, ms) { const id = ++nextId; timers.set(id, { fn, at: clock + ms }); return id; },
    clearTimeout(id) { timers.delete(id); },
    setInterval(fn, ms) { intervals.push({ fn, ms }); return intervals.length; },
    clearInterval() {},
  };
  class FakeDate extends Date { static now() { return clock; } }
  const context = vm.createContext({ window, document, URL, Date: FakeDate,
    HTMLElement: class {}, console: { info() {}, warn() {} },
    CustomEvent: class { constructor(type) { this.type = type; } },
    customElements: { get: name => registered.get(name), define: (name, value) => registered.set(name, value) },
  });
  function load() {
    vm.runInContext(`(() => { ${source}\nglobalThis.recover = recoverFailedFireWatchCards;
      globalThis.cameraHelpers = { resolveCameraSites, normalizeIncident, renderIncidentCameras, renderCameraNetwork, renderCompactBomAttribution }; })()`, context);
  }
  load();
  return { context, document, intervals, listeners, load,
    tick(ms) { clock += ms; },
    drain() {
      let count = 0;
      while (timers.size) {
        assert.ok(++count < 100, 'recovery must remain bounded');
        const [id, timer] = [...timers].sort((a, b) => a[1].at - b[1].at)[0];
        timers.delete(id); clock = timer.at; timer.fn();
      }
    },
    emit(name, detail) { for (const fn of listeners.get(name) || []) fn({ detail }); },
    emitDocument(name) { for (const fn of documentListeners.get(name) || []) fn({}); },
  };
}

test('camera viewers preserve provider encoding and escape display names', () => {
  const { cameraHelpers: helpers } = environment().context;
  const catalogue = { kowen: { name: 'Kowen Forest', region: 'ACT', views: ['Guard', 'Sentry'] } };
  const incident = helpers.normalizeIncident({ id: 'one', nearby_cameras: [{site_id: 'kowen', distance_km: 0}] }, 0, catalogue);
  assert.equal(incident.cameras.length, 1);
  assert.equal(incident.cameras[0].views[0].url, 'https://centralwatch.watchtowers.io/au?camera=Kowen%2520Forest%2520-%2520Guard');
  const html = helpers.renderIncidentCameras(incident);
  assert.equal((html.match(/class="camera-view-button"/g) || []).length, 1);
  assert.ok(html.includes('View Kowen Forest Guard on Central Watch'));
  assert.ok(html.includes('central-watch-view.png'));
  assert.ok(!html.includes('View Sentry'));
  assert.ok(html.includes('reported fire location'));
  assert.ok(!html.includes('<details'), 'Incident cameras must be immediately visible');
  const hostile = helpers.normalizeIncident({nearby_cameras: [{site_id: 'x', distance_km: 2}]}, 0,
    {x: {name: '<img src=x onerror=alert(1)>', views: ['Guard']}});
  assert.ok(!helpers.renderIncidentCameras(hostile).includes('<img src=x'));
});

test('camera section handles disabled, empty and old summaries', () => {
  const helpers = environment().context.cameraHelpers;
  assert.equal(helpers.renderCameraNetwork({}), '');
  assert.equal(helpers.renderIncidentCameras(helpers.normalizeIncident({})), '');
  assert.equal(helpers.resolveCameraSites([{site_id: 'missing', distance_km: 5}], {}).length, 0);
  assert.ok(helpers.renderCameraNetwork({cameraNetwork: {nearbySites: []}}).includes('No listed camera sites'));
  const sites = helpers.resolveCameraSites([{site_id:'one',distance_km:5}], {one:{name:'Fixture',region:'NSW',views:['Guard']}});
  const html = helpers.renderCameraNetwork({cameraNetwork:{nearbySites:sites}});
  assert.ok(!html.includes('<details'), 'Watchtowers must not be hidden behind a dropdown');
  assert.ok(html.includes('1 site</span>'));
  assert.ok(html.includes('camera-view-button'));
  const credit = helpers.renderCompactBomAttribution();
  assert.ok(credit.includes('Weather data: Bureau of Meteorology'));
  assert.ok(!credit.includes('<img'), 'Mobile attribution should be readable text');
});

function missingCard({ message = "Custom element doesn't exist: australian-fire-watch-card.", ready = true } = {}) {
  const wrapper = { localName: 'hui-card', isConnected: true,
    config: { type: 'custom:australian-fire-watch-card' }, children: [] };
  const error = { localName: 'hui-error-card', isConnected: true,
    _config: { message }, attempts: 0, ready,
    dispatchEvent(event) {
      assert.equal(event.type, 'll-rebuild'); this.attempts++;
      if (this.ready) {
        this.isConnected = false;
        wrapper._element = { localName: 'australian-fire-watch-card' };
        wrapper.children = [wrapper._element];
      }
    },
  };
  wrapper._element = error; wrapper.children = [error];
  return { wrapper, error };
}

test('a rebuild request is not mistaken for a completed rebuild', () => {
  const env = environment(); const { wrapper, error } = missingCard({ ready: false });
  env.document.children = [wrapper]; env.context.recover();
  assert.equal(error.attempts, 1);
  error.ready = true; env.tick(1500); env.context.recover();
  assert.equal(wrapper._element.localName, 'australian-fire-watch-card');
});

for (const event of ['location-changed', 'pageshow', 'online', 'connection-status']) {
  test(`recovers an original card on ${event} after the initial four-second window`, () => {
    const env = environment(); env.drain();
    const { wrapper } = missingCard(); env.document.children = [wrapper];
    env.emit(event, 'connected'); env.drain();
    assert.equal(wrapper._element.localName, 'australian-fire-watch-card');
  });
}

test('returning from a backgrounded mobile view schedules recovery', () => {
  const env = environment(); env.drain(); const { wrapper } = missingCard();
  env.document.children = [wrapper]; env.emitDocument('visibilitychange'); env.drain();
  assert.equal(wrapper._element.localName, 'australian-fire-watch-card');
});

test('never replaces unrelated configuration errors', () => {
  const env = environment();
  for (const message of ['Invalid card configuration', "Custom element doesn't exist: other-card."]) {
    const { wrapper, error } = missingCard({ message });
    env.document.children = [wrapper]; env.context.recover();
    assert.equal(error.attempts, 0);
  }
});

test('extra-module and Lovelace loading do not duplicate recovery listeners', () => {
  const env = environment(); env.load();
  assert.equal(env.listeners.get('pageshow')?.length, 1);
});
