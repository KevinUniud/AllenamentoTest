const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

class SvgNode {
    constructor(tagName) {
        this.tagName = tagName;
        this.attributes = new Map();
        this.children = [];
        this.classList = { add: value => { this.className = value; } };
        this.innerHTML = '';
        this.textContent = '';
    }

    appendChild(child) {
        this.children.push(child);
        return child;
    }

    setAttribute(name, value) {
        this.attributes.set(name, String(value));
    }

    getAttribute(name) {
        return this.attributes.get(name);
    }
}

function loadCharts() {
    const context = {
        document: { createElementNS(namespace, tagName) { return new SvgNode(tagName); } }
    };
    context.window = context;
    vm.createContext(context);
    vm.runInContext(fs.readFileSync('scripts/charts.js', 'utf8'), context);
    return context.LogicCharts;
}

test('percentage charts keep a fixed 0-100 scale and clamp out-of-range values', () => {
    const charts = loadCharts();
    const container = new SvgNode('div');
    const svg = charts.renderBars(container, [
        { label: 'Metà', value: 50, displayValue: '50%' },
        { label: 'Oltre', value: 150, displayValue: '150%' }
    ], { label: 'Precisione', maximum: 100 });

    const bars = svg.children.filter(child => child.tagName === 'rect');
    assert.equal(Number(bars[0].getAttribute('width')), 215);
    assert.equal(Number(bars[1].getAttribute('width')), 430);
    assert.equal(svg.getAttribute('aria-label'), 'Precisione');
});
