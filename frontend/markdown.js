/* Small Markdown renderer: build DOM nodes, never interpolate model HTML. */
function appendInlineMarkdown(parent, text) {
    const pattern = /(\*\*([^*]+)\*\*|`([^`]+)`|\[([^\]]+)\]\(([^\s)]+)\)|\*([^*\n]+)\*)/g;
    let start = 0;
    for (const match of text.matchAll(pattern)) {
        parent.appendChild(document.createTextNode(text.slice(start, match.index)));
        let element;
        if (match[2]) {
            element = document.createElement('strong');
            element.textContent = match[2];
        } else if (match[3]) {
            element = document.createElement('code');
            element.textContent = match[3];
        } else if (match[4]) {
            let url;
            try { url = new URL(match[5]); } catch { url = null; }
            if (url && ['https:', 'http:'].includes(url.protocol)) {
                element = document.createElement('a');
                element.href = url.href;
                element.target = '_blank';
                element.rel = 'noopener noreferrer';
                element.textContent = match[4];
            } else {
                element = document.createTextNode(match[4]);
            }
        } else {
            element = document.createElement('em');
            element.textContent = match[6];
        }
        parent.appendChild(element);
        start = match.index + match[0].length;
    }
    parent.appendChild(document.createTextNode(text.slice(start)));
}

function renderMarkdown(text, target) {
    const lines = String(text).replace(/\r\n/g, '\n').split('\n');
    const cells = line => line.trim().replace(/^\||\|$/g, '').split('|').map(c => c.trim());
    const isTableSeparator = line => line && cells(line).every(c => /^:?-{3,}:?$/.test(c));
    const isBlock = (line, next) => !line.trim() || /^(#{1,6})\s|^\s*([-*+]\s|\d+\.\s)|^```|^>\s|^---+$/.test(line) || (line.includes('|') && isTableSeparator(next));
    for (let i = 0; i < lines.length;) {
        const line = lines[i];
        if (!line.trim()) { i++; continue; }
        if (line.startsWith('```')) {
            const pre = document.createElement('pre'), code = document.createElement('code');
            const body = []; i++;
            while (i < lines.length && !lines[i].startsWith('```')) body.push(lines[i++]);
            if (i < lines.length) i++;
            code.textContent = body.join('\n'); pre.appendChild(code); target.appendChild(pre); continue;
        }
        const heading = line.match(/^(#{1,6})\s+(.+)$/);
        if (heading) {
            const h = document.createElement('h' + Math.min(6, heading[1].length + 1));
            appendInlineMarkdown(h, heading[2]); target.appendChild(h); i++; continue;
        }
        if (/^---+$/.test(line.trim())) { target.appendChild(document.createElement('hr')); i++; continue; }
        if (line.includes('|') && isTableSeparator(lines[i + 1])) {
            const wrapper = document.createElement('div'); wrapper.className = 'table-scroll';
            const table = document.createElement('table'), head = document.createElement('thead');
            const row = document.createElement('tr');
            cells(line).forEach(cell => { const th = document.createElement('th'); th.scope = 'col'; appendInlineMarkdown(th, cell); row.appendChild(th); });
            head.appendChild(row); table.appendChild(head); i += 2;
            const body = document.createElement('tbody');
            while (i < lines.length && lines[i].trim() && lines[i].includes('|')) {
                const tr = document.createElement('tr');
                cells(lines[i++]).forEach(cell => { const td = document.createElement('td'); appendInlineMarkdown(td, cell); tr.appendChild(td); });
                body.appendChild(tr);
            }
            table.appendChild(body); wrapper.appendChild(table); target.appendChild(wrapper); continue;
        }
        const list = line.match(/^\s*([-*+]\s+|\d+\.\s+)(.*)$/);
        if (list) {
            const ordered = /^\d/.test(list[1]);
            const element = document.createElement(ordered ? 'ol' : 'ul');
            if (ordered) element.start = parseInt(list[1], 10);
            while (i < lines.length) {
                const item = lines[i].match(/^\s*([-*+]\s+|\d+\.\s+)(.*)$/);
                if (!item || /^\d/.test(item[1]) !== ordered) break;
                const li = document.createElement('li'); appendInlineMarkdown(li, item[2]); i++;
                while (i < lines.length && /^\s{2,}\S/.test(lines[i]) && !/^\s*([-*+]\s|\d+\.\s)/.test(lines[i])) {
                    li.appendChild(document.createTextNode(' ')); appendInlineMarkdown(li, lines[i++].trim());
                }
                element.appendChild(li);
            }
            target.appendChild(element); continue;
        }
        if (line.startsWith('> ')) {
            const quote = document.createElement('blockquote'); appendInlineMarkdown(quote, line.slice(2));
            target.appendChild(quote); i++; continue;
        }
        const paragraph = document.createElement('p');
        const body = [line]; i++;
        while (i < lines.length && !isBlock(lines[i], lines[i + 1])) body.push(lines[i++]);
        body.forEach((part, index) => {
            appendInlineMarkdown(paragraph, part.replace(/\s{2}$/, ''));
            if (index < body.length - 1) paragraph.appendChild(/\s{2}$/.test(part) ? document.createElement('br') : document.createTextNode(' '));
        });
        target.appendChild(paragraph);
    }
}
