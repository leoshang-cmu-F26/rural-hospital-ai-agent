// Draw only validated numeric payloads; never evaluate model text or inject HTML.
function renderFinancialCharts(reply, charts, notes) {
    if (!charts.length) {
        return;
    }
    const section = document.createElement('section');
    section.className = 'financial-charts';
    const heading = document.createElement('h3');
    heading.textContent = 'Financial charts';
    section.appendChild(heading);
    const select = document.createElement('select');
    select.setAttribute('aria-label', 'Choose financial chart metric');
    for (let index = 0; index < charts.length; index += 1) {
        const option = document.createElement('option');
        option.value = String(index);
        const names = [];
        for (const series of charts[index].series) {
            names.push(series.facility_id);
        }
        option.textContent = charts[index].title + ' — ' + charts[index].type + ' — ' + names.join(', ');
        select.appendChild(option);
    }
    section.appendChild(select);
    const notice = document.createElement('p');
    notice.className = 'chart-notes';
    notice.textContent = notes.join(' ');
    section.appendChild(notice);
    const panel = document.createElement('div');
    section.appendChild(panel);
    select.addEventListener('change', function () {
        const chart = charts[Number(select.value)];
        if (chart) {
            drawFinancialChart(panel, chart);
        }
    });
    drawFinancialChart(panel, charts[0]);
    reply.appendChild(section);
}


// Keep negative values and zero baselines visible; missing values break lines.
function drawFinancialChart(panel, chart) {
    panel.textContent = '';
    const palette = ['#2563a6', '#be4a2f', '#32805b', '#8253a3', '#936612'];
    const values = [];
    const years = new Set();
    for (const series of chart.series) {
        for (const point of series.points) {
            years.add(point.year);
            if (typeof point.value === 'number' && Number.isFinite(point.value)) {
                values.push(point.value);
            }
        }
    }
    const orderedYears = Array.from(years).sort((first, second) => first - second);
    const heading = document.createElement('h4');
    heading.textContent = chart.title + ' (' + chart.unit + ')';
    panel.appendChild(heading);
    if (chart.plot_allowed !== false && values.length) {
        let low = Math.min(0, ...values);
        let high = Math.max(0, ...values);
        if (low === high) {
            low -= 1;
            high += 1;
        }
        const padding = (high - low) * 0.08;
        low -= padding;
        high += padding;
        const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.setAttribute('viewBox', '0 0 800 330');
        svg.setAttribute('role', 'img');
        svg.setAttribute('aria-label', chart.title + '. Exact values and fiscal dates are in the data table below.');
        const left = 78;
        const right = 770;
        const top = 24;
        const bottom = 274;
        function shape(tag, attributes, text) {
            const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
            for (const key of Object.keys(attributes)) {
                node.setAttribute(key, String(attributes[key]));
            }
            if (text !== undefined) {
                node.textContent = text;
            }
            svg.appendChild(node);
            return node;
        }
        function y(value) {
            return bottom - (value - low) / (high - low) * (bottom - top);
        }
        function x(index, length) {
            return left + (index + 0.5) / length * (right - left);
        }
        for (let tick = 0; tick <= 4; tick += 1) {
            const value = low + (high - low) * tick / 4;
            shape('line', {x1: left, x2: right, y1: y(value), y2: y(value), stroke: '#dce3e6'});
            shape('text', {x: left - 8, y: y(value) + 4, 'text-anchor': 'end', 'font-size': 12}, value.toFixed(2));
        }
        shape('line', {x1: left, x2: right, y1: y(0), y2: y(0), stroke: '#53636e', 'stroke-width': 1.5});
        for (let index = 0; index < chart.series.length; index += 1) {
            const series = chart.series[index];
            const color = palette[index % palette.length];
            let previous = null;
            for (const point of series.points) {
                if (typeof point.value !== 'number' || !Number.isFinite(point.value)) {
                    previous = null;
                    continue;
                }
                let px = x(index, chart.series.length);
                if (chart.type === 'line') {
                    px = x(orderedYears.indexOf(point.year), orderedYears.length);
                }
                const py = y(point.value);
                if (chart.type === 'line' && series.connect && previous && point.year === previous.year + 1) {
                    shape('line', {x1: previous.x, y1: previous.y, x2: px, y2: py, stroke: color, 'stroke-width': 2.5});
                }
                let mark;
                if (chart.type === 'bar') {
                    const width = Math.min(72, (right - left) / chart.series.length * 0.6);
                    mark = shape('rect', {x: px - width / 2, y: Math.min(py, y(0)), width: width,
                        height: Math.max(1, Math.abs(py - y(0))), fill: color});
                    shape('text', {x: px, y: py - 6, 'text-anchor': 'middle', 'font-size': 12}, point.value.toFixed(2));
                } else {
                    mark = shape('circle', {cx: px, cy: py, r: 4, fill: color});
                }
                const tooltip = document.createElementNS('http://www.w3.org/2000/svg', 'title');
                tooltip.textContent = series.name + ' (' + series.facility_id + ') · ' + point.year + ': ' + point.value + ' ' + chart.unit
                    + ' · Fiscal period: ' + (point.fiscal_year_begin || 'unknown') + ' – ' + (point.fiscal_year_end || 'unknown');
                mark.appendChild(tooltip);
                previous = {x: px, y: py, year: point.year};
            }
            if (chart.type === 'bar') {
                shape('text', {x: x(index, chart.series.length), y: bottom + 22, 'text-anchor': 'middle', 'font-size': 12}, String(index + 1));
            }
        }
        if (chart.type === 'line') {
            for (let index = 0; index < orderedYears.length; index += 1) {
                shape('text', {x: x(index, orderedYears.length), y: bottom + 22, 'text-anchor': 'middle', 'font-size': 12}, String(orderedYears[index]));
            }
        }
        let axisLabel = 'Hospital number (see legend)';
        if (chart.type === 'line') {
            axisLabel = 'CMS dataset year';
        }
        shape('text', {x: 420, y: 322, 'text-anchor': 'middle', 'font-size': 12}, axisLabel);
        panel.appendChild(svg);
    } else {
        const message = document.createElement('p');
        message.className = 'chart-notes';
        message.textContent = 'Chart withheld: no usable values or fiscal periods require review. See reported values below.';
        panel.appendChild(message);
    }

    // Accessible tables retain missing rows, fiscal dates and source snapshots.
    const legend = document.createElement('ul');
    for (let index = 0; index < chart.series.length; index += 1) {
        const item = document.createElement('li');
        item.setAttribute('style', 'color:' + palette[index % palette.length]);
        item.textContent = String(index + 1) + '. ' + chart.series[index].name + ' · CCN ' + chart.series[index].facility_id;
        legend.appendChild(item);
    }
    panel.appendChild(legend);
    const details = document.createElement('details');
    const summary = document.createElement('summary');
    summary.textContent = 'View chart data and fiscal periods';
    details.appendChild(summary);
    const table = document.createElement('table');
    const head = document.createElement('tr');
    for (const text of ['Hospital / CCN', 'Dataset year', 'Value (' + chart.unit + ')', 'Fiscal period', 'Source retrieved']) {
        const cell = document.createElement('th');
        cell.textContent = text;
        head.appendChild(cell);
    }
    table.appendChild(head);
    for (const series of chart.series) {
        for (const point of series.points) {
            const row = document.createElement('tr');
            let value = 'Missing / withheld';
            if (typeof point.value === 'number' && Number.isFinite(point.value)) {
                value = String(point.value);
            }
            const provenance = point.source_provenance || {};
            for (const text of [series.name + ' / ' + series.facility_id, String(point.year), value,
                (point.fiscal_year_begin || '?') + ' – ' + (point.fiscal_year_end || '?'), provenance.source_retrieved_at || 'Not recorded']) {
                const cell = document.createElement('td');
                cell.textContent = text;
                row.appendChild(cell);
            }
            table.appendChild(row);
        }
    }
    details.appendChild(table);
    panel.appendChild(details);
    const source = document.createElement('a');
    source.textContent = 'Source: CMS cost reports';
    source.href = 'https://www.cms.gov/data-research/statistics-trends-and-reports/cost-reports';
    source.target = '_blank';
    source.rel = 'noopener noreferrer';
    panel.appendChild(source);
}
