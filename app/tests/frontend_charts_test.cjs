// Exercise SVG rendering, gaps, negative bars, metric switching and safe text.
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');

class Element {
    constructor(tag) {
        this.tagName = tag;
        this.children = [];
        this.attributes = {};
        this.listeners = {};
        this.value = '';
        this._text = '';
    }
    appendChild(node) { this.children.push(node); return node; }
    setAttribute(key, value) { this.attributes[key] = String(value); }
    addEventListener(name, callback) { this.listeners[name] = callback; }
    set textContent(value) { this._text = String(value); this.children = []; }
    get textContent() {
        let text = this._text;
        for (const child of this.children) { text += child.textContent; }
        return text;
    }
}
function find(root, tag) {
    const result = [];
    if (root.tagName === tag) { result.push(root); }
    for (const child of root.children) { result.push(...find(child, tag)); }
    return result;
}
const context = {document: {createElement: tag => new Element(tag),
    createElementNS: (namespace, tag) => new Element(tag)}, console};
vm.createContext(context);
vm.runInContext(fs.readFileSync('frontend/financial-charts.js', 'utf8'), context);
const line = {id: 'line:test', type: 'line', title: 'Margin', unit: '%',
    plot_allowed: true, series: [{facility_id: '1', name: '<script>untrusted</script>',
        connect: true, points: [{year: 2022, value: -10}, {year: 2023, value: null},
            {year: 2024, value: 5}]}]};
context.panel = new Element('div');
context.chart = line;
vm.runInContext('drawFinancialChart(panel, chart)', context);
assert.equal(find(context.panel, 'circle').length, 2);
assert.equal(find(context.panel, 'line').filter(node => node.attributes['stroke-width'] === '2.5').length, 0);
assert(context.panel.textContent.includes('Missing / withheld'));
assert.equal(find(context.panel, 'script').length, 0);
assert(context.panel.textContent.includes('<script>untrusted</script>'));

const bar = {id: 'bar:test', type: 'bar', title: 'Margin', unit: '%', plot_allowed: true,
    series: [{facility_id: '1', name: 'First', points: [{year: 2024, value: -10}]},
        {facility_id: '2', name: 'Second', points: [{year: 2024, value: 0}]},
        {facility_id: '3', name: 'Third', points: [{year: 2024, value: 5}]}]};
context.chart = bar;
vm.runInContext('drawFinancialChart(panel, chart)', context);
assert.equal(find(context.panel, 'rect').length, 3);
for (const rect of find(context.panel, 'rect')) {
    assert(Number(rect.attributes.height) >= 1);
}
bar.plot_allowed = false;
vm.runInContext('drawFinancialChart(panel, chart)', context);
assert.equal(find(context.panel, 'svg').length, 0);
assert(context.panel.textContent.includes('Chart withheld'));
assert.equal(find(context.panel, 'td').length, 15);

context.reply = new Element('div');
context.charts = [line, bar];
vm.runInContext('renderFinancialCharts(reply, charts, ["CMS source"])', context);
const select = find(context.reply, 'select')[0];
assert.equal(select.children.length, 2);
select.value = '1';
select.listeners.change();
assert(context.reply.textContent.includes('Chart withheld'));
assert.equal(find(context.reply, 'svg').length, 0);
console.log('Financial chart renderer passed: gaps, negative/zero bars, withholding, safe text and metric selection');
