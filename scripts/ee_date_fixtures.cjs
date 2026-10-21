/* Generate Date invocation fixtures using the pinned, unmodified official EE SDK.
 * Run: node scripts/ee_date_fixtures.cjs > tests/fixtures/ee-date-1.7.49.json
 * No server calls, user scripts, credentials, or network access are used.
 */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
global.window = globalThis;
const ee = require(path.join(root, 'vendor/earthengine-js/earthengine.cjs'));
global.ee = ee;
const raw = JSON.parse(fs.readFileSync(path.join(root, 'vendor/earthengine-js/algorithms.json'))).algorithms;
const signatures = Object.fromEntries(raw.map(a => [a.name.replace(/^algorithms\//, ''), {
  description: a.description, returns: a.returnType,
  args: (a.arguments || []).map(x => ({ name: x.argumentName, type: x.type,
    optional: !!x.optional, ...('defaultValue' in x ? {default: x.defaultValue} : {}) }))
}]));
ee.data.getAlgorithms = callback => callback ? callback(signatures) : signatures;
ee.initialize('http://localhost/disabled', 'http://localhost/disabled');
ee.data.computeValue = () => { throw Error('Date fixture generation must never call a server'); };

const leapStart = ee.Date('2020-01-01T00:00:00Z');
const leapEnd = ee.Date('2021-01-01T00:00:00Z');
const leapDay = ee.Date('2020-02-29T07:15:31.240Z');
const values = {
  differenceDaysPlural: ee.Date('2020-01-15').difference(ee.Date('2020-01-01'), 'days'),
  differenceLeapYear: leapEnd.difference(leapStart, 'year'),
  differenceMonth: ee.Date('2020-02-01').difference(ee.Date('2020-01-01'), 'month'),
  relativeMonthYear: leapDay.getRelative('month', 'year'),
  relativeWeekYear: ee.Date('2021-01-01').getRelative('week', 'year'),
  relativeDayYear: leapDay.getRelative('day', 'year'),
  relativeDayMonth: leapDay.getRelative('day', 'month'),
  relativeMinuteDay: leapDay.getRelative('minute', 'day'),
  relativeSecondMinute: leapDay.getRelative('second', 'minute'),
  relativeLargerUnit: leapDay.getRelative('year', 'month'),
  relativeTimezone: ee.Date('2021-01-01T00:00:00Z').getRelative('day', 'year', 'UTC'),
  fractionYear: leapDay.getFraction('year'),
  fractionMonth: leapDay.getFraction('month'),
  fractionWeek: leapDay.getFraction('week'),
  fractionDay: leapDay.getFraction('day'),
  fractionHour: leapDay.getFraction('hour'),
  fractionMinute: leapDay.getFraction('minute'),
  fractionSecond: leapDay.getFraction('second'),
};
const expressions = Object.fromEntries(Object.entries(values).map(([key, value]) => [key, ee.Serializer.encode(value)]));
process.stdout.write(JSON.stringify({
  sdk: '1.7.49',
  source_commit: 'e189e4b89e785019ea5642ea8e80cb644749cd4a',
  source: 'https://github.com/google/earthengine-api',
  expressions,
}, null, 2) + '\n');
