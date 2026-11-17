// D-03 regression: trend-reversal notices are merged per facility and long lists collapse.
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const dir = process.argv[2] || 'frontend';
const src = fs.readFileSync(path.join(dir, 'app.js'), 'utf8');
const start = src.indexOf('function groupTrendReversals');
const end = src.indexOf('function renderWarnings');
const ctx = {};
vm.runInNewContext(src.slice(start, end) + ';this.groupTrendReversals=groupTrendReversals;', ctx);
const assert = require('assert');
const w = (name, metric) => ({code: 'trend_reversals', facility_id: name, facility_name: name, metric,
  message: `${metric} changes direction`, action: 'do not claim sustained improvement'});
const out = ctx.groupTrendReversals([
  w('A', 'operating_margin'), w('A', 'occupancy_rate'), w('B', 'operating_margin'),
  {code: 'acs_moe', facility_name: 'A', message: 'ACS note'}]);
assert.strictEqual(out.length, 3);
assert.match(out[0].message, /operating margin, occupancy rate/);
assert.doesNotMatch(out[0].action, /do not claim/);
assert.strictEqual(out[2].code, 'acs_moe');
console.log('Frontend warnings passed: per-facility merge, plain wording, other notices preserved');
