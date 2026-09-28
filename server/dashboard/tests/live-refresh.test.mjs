import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const source = await readFile(new URL('../static/js/live-refresh.js', import.meta.url), 'utf8');
const { startLiveRefresh } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);

async function flush() { for (let i = 0; i < 10; i++) await Promise.resolve(); }
function setup(t) {
    const status = {};
    const doc = Object.assign(new EventTarget(), { hidden: false, getElementById: () => status });
    const win = new EventTarget();
    globalThis.document = doc;
    globalThis.window = win;
    t.mock.timers.enable({ apis: ['setTimeout'] });
    return { status, doc, win, advance: async (ms) => { t.mock.timers.tick(ms); await flush(); } };
}

test('polls changed data, avoids duplicate renders and stops on cleanup', async t => {
    const { advance } = setup(t);
    let calls = 0, data = [], renders = [];
    const stop = startLiveRefresh(async () => { calls++; return data; }, value => renders.push(value));
    t.after(stop);
    await flush();
    await advance(5000);
    assert.equal(calls, 2);
    assert.equal(renders.length, 1);
    data = [{ id: 'new-device', online: false }];
    await advance(5000);
    data = [{ id: 'new-device', online: true }];
    await advance(5000);
    data = [{ id: 'new-device', online: false }];
    await advance(5000);
    assert.deepEqual(renders.map(v => v[0]?.online), [undefined, false, true, false]);
    stop();
    const stoppedAt = calls;
    await advance(30000);
    assert.equal(calls, stoppedAt);
});

test('keeps old data on failure and recovers with backoff', async t => {
    const { status, advance } = setup(t);
    let fail = false, calls = 0, renders = 0;
    const stop = startLiveRefresh(async () => { calls++; if (fail) throw new TypeError('offline'); return [1]; }, () => renders++);
    t.after(stop);
    await flush();
    fail = true;
    await advance(5000);
    assert.match(status.className, /is-stale/);
    assert.equal(renders, 1);
    fail = false;
    await advance(9999);
    assert.equal(calls, 2);
    await advance(1);
    assert.equal(calls, 3);
    assert.doesNotMatch(status.className, /is-stale/);
});

test('pauses in hidden tabs, resumes immediately and handles page cache', async t => {
    const { doc, win, advance } = setup(t);
    let calls = 0;
    const stop = startLiveRefresh(async () => ++calls, () => {});
    t.after(stop);
    await flush();
    doc.hidden = true;
    doc.dispatchEvent(new Event('visibilitychange'));
    await advance(30000);
    assert.equal(calls, 1);
    doc.hidden = false;
    doc.dispatchEvent(new Event('visibilitychange'));
    await flush();
    assert.equal(calls, 2);
    win.dispatchEvent(new Event('pagehide'));
    await advance(30000);
    assert.equal(calls, 2);
    win.dispatchEvent(new Event('pageshow'));
    await flush();
    assert.equal(calls, 3);
});

test('never overlaps pending requests and aborts requests after timeout', async t => {
    const { win, status, advance } = setup(t);
    let calls = 0, aborted = false;
    const stop = startLiveRefresh(signal => {
        calls++;
        return new Promise((resolve, reject) => signal.addEventListener('abort', () => { aborted = true; reject(new Error('aborted')); }));
    }, () => assert.fail('must not render'));
    t.after(stop);
    win.dispatchEvent(new Event('online'));
    await advance(5000);
    assert.equal(calls, 1);
    await advance(5000);
    assert.equal(aborted, true);
    assert.match(status.className, /is-stale/);
    await advance(10000);
    assert.equal(calls, 2);
});

test('stops polling on lost access', async t => {
    const { advance, status } = setup(t);
    let calls = 0;
    const stop = startLiveRefresh(async () => { calls++; throw Object.assign(new Error('denied'), {status: 401}); }, () => {});
    t.after(stop);
    await flush();
    await advance(30000);
    assert.equal(calls, 1);
    assert.match(status.className, /is-stale/);
});
