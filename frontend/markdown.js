/* Render a limited Markdown subset using DOM nodes; never interpolate model HTML. */

// Inline formatting: copy plain text and explicitly create supported elements.
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
            // Only web links become clickable; unsupported schemes remain text.
            let url;
            try {
                url = new URL(match[5]);
            } catch {
                url = null;
            }

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

// Table parsing: trim optional edge pipes without interpreting cell text as HTML.
function markdownTableCells(line) {
    const rawCells = line.trim().replace(/^\||\|$/g, '').split('|');
    const cells = [];
    for (const cell of rawCells) {
        cells.push(cell.trim());
    }
    return cells;
}

function isMarkdownTableSeparator(line) {
    if (!line) {
        return false;
    }
    for (const cell of markdownTableCells(line)) {
        if (!/^:?-{3,}:?$/.test(cell)) {
            return false;
        }
    }
    return true;
}

// Paragraph boundaries: stop before a list, heading, code block, quote or table.
function isMarkdownBlock(line, next) {
    if (!line.trim()) {
        return true;
    }
    if (/^(#{1,6})\s|^\s*([-*+]\s|\d+\.\s)|^```|^>\s|^---+$/.test(line)) {
        return true;
    }
    return line.includes('|') && isMarkdownTableSeparator(next);
}

// Table blocks return the first unconsumed line so the main parser stays linear.
function renderMarkdownTable(lines, start, target) {
    const wrapper = document.createElement('div');
    wrapper.className = 'table-scroll';
    const table = document.createElement('table');
    const head = document.createElement('thead');
    const row = document.createElement('tr');

    for (const cell of markdownTableCells(lines[start])) {
        const header = document.createElement('th');
        header.scope = 'col';
        appendInlineMarkdown(header, cell);
        row.appendChild(header);
    }
    head.appendChild(row);
    table.appendChild(head);

    const body = document.createElement('tbody');
    let index = start + 2;
    while (index < lines.length && lines[index].trim() && lines[index].includes('|')) {
        const tableRow = document.createElement('tr');
        for (const cell of markdownTableCells(lines[index])) {
            const tableCell = document.createElement('td');
            appendInlineMarkdown(tableCell, cell);
            tableRow.appendChild(tableCell);
        }
        body.appendChild(tableRow);
        index++;
    }

    table.appendChild(body);
    wrapper.appendChild(table);
    target.appendChild(wrapper);
    return index;
}

// Block rendering: consume one supported block at a time, preserving line order.
function renderMarkdown(text, target) {
    const lines = String(text).replace(/\r\n/g, '\n').split('\n');

    for (let index = 0; index < lines.length;) {
        const line = lines[index];
        if (!line.trim()) {
            index++;
            continue;
        }

        // 1. Fenced code is literal text, including any markup inside it.
        if (line.startsWith('```')) {
            const pre = document.createElement('pre');
            const code = document.createElement('code');
            const body = [];
            index++;
            while (index < lines.length && !lines[index].startsWith('```')) {
                body.push(lines[index]);
                index++;
            }
            if (index < lines.length) {
                index++;
            }
            code.textContent = body.join('\n');
            pre.appendChild(code);
            target.appendChild(pre);
            continue;
        }

        // 2. Headings are offset beneath the page's main application heading.
        const heading = line.match(/^(#{1,6})\s+(.+)$/);
        if (heading) {
            const element = document.createElement('h' + Math.min(6, heading[1].length + 1));
            appendInlineMarkdown(element, heading[2]);
            target.appendChild(element);
            index++;
            continue;
        }
        if (/^---+$/.test(line.trim())) {
            target.appendChild(document.createElement('hr'));
            index++;
            continue;
        }

        // 3. Tables require a header separator and scroll horizontally on phones.
        if (line.includes('|') && isMarkdownTableSeparator(lines[index + 1])) {
            index = renderMarkdownTable(lines, index, target);
            continue;
        }

        // 4. Preserve ordered/unordered list type and indented continuation text.
        const list = line.match(/^\s*([-*+]\s+|\d+\.\s+)(.*)$/);
        if (list) {
            const ordered = /^\d/.test(list[1]);
            let listElement;
            if (ordered) {
                listElement = document.createElement('ol');
                listElement.start = parseInt(list[1], 10);
            } else {
                listElement = document.createElement('ul');
            }

            while (index < lines.length) {
                const item = lines[index].match(/^\s*([-*+]\s+|\d+\.\s+)(.*)$/);
                if (!item || /^\d/.test(item[1]) !== ordered) {
                    break;
                }
                const listItem = document.createElement('li');
                appendInlineMarkdown(listItem, item[2]);
                index++;

                while (index < lines.length && /^\s{2,}\S/.test(lines[index]) && !/^\s*([-*+]\s|\d+\.\s)/.test(lines[index])) {
                    listItem.appendChild(document.createTextNode(' '));
                    appendInlineMarkdown(listItem, lines[index].trim());
                    index++;
                }
                listElement.appendChild(listItem);
            }
            target.appendChild(listElement);
            continue;
        }

        // 5. Block quotes use the same safe inline renderer as ordinary text.
        if (line.startsWith('> ')) {
            const quote = document.createElement('blockquote');
            appendInlineMarkdown(quote, line.slice(2));
            target.appendChild(quote);
            index++;
            continue;
        }

        // 6. Join paragraph lines, retaining Markdown's explicit hard line breaks.
        const paragraph = document.createElement('p');
        const body = [line];
        index++;
        while (index < lines.length && !isMarkdownBlock(lines[index], lines[index + 1])) {
            body.push(lines[index]);
            index++;
        }
        for (let partIndex = 0; partIndex < body.length; partIndex++) {
            const part = body[partIndex];
            appendInlineMarkdown(paragraph, part.replace(/\s{2}$/, ''));
            if (partIndex < body.length - 1) {
                if (/\s{2}$/.test(part)) {
                    paragraph.appendChild(document.createElement('br'));
                } else {
                    paragraph.appendChild(document.createTextNode(' '));
                }
            }
        }
        target.appendChild(paragraph);
    }
}
