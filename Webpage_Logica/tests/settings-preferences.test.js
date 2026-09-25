const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

const context = {};
context.window = context;
vm.runInNewContext(fs.readFileSync('scripts/settings-preferences.js', 'utf8'), context);
const preferences = context.LogicPreferences;

test('font values are parsed and clamped', () => {
    assert.equal(preferences.parsePxValue('18px', 12, 28, 16), 18);
    assert.equal(preferences.parsePxValue('100', 12, 28, 16), 28);
    assert.equal(preferences.parsePxValue('invalid', 12, 28, 16), null);
});

test('boolean storage uses the 1/0 convention', () => {
    const values = new Map();
    const storage = { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value) };
    preferences.writeBool(storage, 'feature', true);
    assert.equal(preferences.readBool(storage, 'feature'), true);
});
