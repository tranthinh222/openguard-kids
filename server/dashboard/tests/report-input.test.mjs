import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
const source = fs.readFileSync(new URL('../static/js/report-input.js', import.meta.url), 'utf8');
const {validateReportRange} = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);

test('report date range rejects invalid, reversed, future and overlong dates', () => {
  const today = '2026-10-14';
  assert.equal(validateReportRange('2026-10-14', today, today), '');
  assert.equal(validateReportRange('2026-07-17', today, today), '');
  for (const [start, end] of [['', today], ['2026-02-30', today], [today, '2026-10-13'],
                             [today, '2026-10-15'], ['2026-07-16', today]]) {
    assert.notEqual(validateReportRange(start, end, today), '');
  }
});
