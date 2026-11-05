"""Strict local v0.5.7 terminal contract, not a second renderer. AGPL-3.0-only.

Single-probe presentation mirrors the explicitly licensed upstream terminal mapping;
original mapping MIT (Remnawave, 2026), see NOTICE-STREAM.md. This code NEVER
replaces CLI output; it checks the original same-measurement ANSI before display.
Unknown future directory/schema/visual contracts fail closed.
"""
import json
from pathlib import Path
import re

CONTRACT = json.loads((Path(__file__).parent / 'stream_platforms.json').read_text())
PURPOSES = ('video', 'music', 'aiServices', 'gaming', 'community', 'general')
COLOR = {'Yes': (True, 2), 'No': (True, 1), 'Limited': (True, 3), 'Unknown': (True, None)}
SGR = re.compile(r'\x1b\[([0-9;:]*)m')


def _part(label, value, style=(False, None)):
    return ([(c, False, None) for c in label + ' '] if label else []) + [(c, *style) for c in value]


def _join(parts):
    result = []
    for part in parts:
        if result:
            result.extend((c, False, None) for c in ' · ')
        result.extend(part)
    return result


def _plain(cell):
    return ''.join(c[0] for c in cell)


def _groups(report, country):
    buckets = [[] for _ in PURPOSES]
    regional = []
    region = report['selection']['region']
    catalogue = json.loads((Path(__file__).parent / 'unified_catalogue.json').read_text())
    global_ids = set(catalogue['groups']['global'])
    local_ids = set(catalogue['groups'].get(region, ())) - global_ids if region != 'global' else set()
    for field, source in (('services', 'geo'), ('results', 'access'), ('ai_endpoints', 'ai'), ('extra_checks', 'extra')):
        for row in report[field]:
            p = CONTRACT['mapping'].get(source + ':' + row['id'])
            if not p:
                raise ValueError('Unknown terminal probe contract')
            if source == 'geo':
                is_country = row['type'] == 'country'
                code = country(row['value']) if is_country else ''
                label = 'Unknown'
                if row['status'] != 'error':
                    yes = is_country or (row['value'] == 'no' if row['type'] == 'blocked' else row['value'] == 'yes')
                    label = 'Yes' if yes else 'No'
            else:
                label = {'available': 'Yes', 'reachable': 'Yes', 'blocked': 'No', 'restricted': 'Limited', 'error': 'Unknown'}[row['status']]
                code = '' if source == 'ai' else country(row.get('region'))
            cells = [_part('', p['name']), _part('', ('○ ' if label == 'Unknown' else '● ') + label, COLOR[label]), _part('', code)]
            if source == 'extra' and row['id'] in local_ids and p['purpose'] in ('video', 'music'):
                regional.append(cells)
            else:
                buckets[PURPOSES.index(p['purpose'])].append(cells)
    groups = [(CONTRACT['titles'][i], rows) for i, rows in enumerate(buckets) if rows]
    if regional:
        groups.append(('Regional media — ' + CONTRACT['region_titles'][region], regional))
    return groups


def _decode(text):
    """SGR whitelist and semantic state per visible character, across wraps."""
    out, pos, bold, fg = [], 0, False, None
    for match in SGR.finditer(text):
        for char in text[pos:match.start()]:
            if char == '\x1b' or ord(char) < 32 and char != '\n':
                raise ValueError('Invalid terminal controls')
            out.append((char, bold, fg))
        seq = match[1].replace(':', ';')
        codes = [int(v or 0) for v in seq.split(';')]
        at = 0
        while at < len(codes):
            code = codes[at]
            if code == 0:
                bold, fg = False, None
            elif code == 1:
                bold = True
            elif code == 22:
                bold = False
            elif code == 39:
                fg = None
            elif code in (31, 32, 33):
                fg = code - 30
            elif code == 38 and codes[at:at+2] == [38, 5] and len(codes) > at+2 and codes[at+2] in (1, 2, 3):
                fg = codes[at+2]
                at += 2
            else:
                raise ValueError('Unexpected ANSI style')
            at += 1
        pos = match.end()
    for char in text[pos:]:
        if char == '\x1b' or ord(char) < 32 and char != '\n':
            raise ValueError('Invalid terminal controls')
        out.append((char, bold, fg))
    lines, line = [], []
    for item in out:
        if item[0] == '\n':
            lines.append(line)
            line = []
        else:
            line.append(item)
    if line:
        lines.append(line)
    return lines


def validate_terminal(terminal, report, selection_notice, country):
    groups = _groups(report, country)
    lines = _decode(terminal)
    if not lines or _plain(lines.pop(0)) != selection_notice:
        raise ValueError('Missing/incorrect automatic selection notice')
    plain = [_plain(line) for line in lines]
    if not plain or not re.fullmatch('╭─+╮', plain[0]) or not re.fullmatch('╰─+╯', plain[-1]):
        raise ValueError('Not a complete single rounded frame')
    width = len(plain[0])
    if not 14 <= width <= 160 or any(len(line) != width for line in plain):
        raise ValueError('Broken unified frame width')
    if any(sum(line.count(c) for line in plain) != 1 for c in '╭╮╰╯'):
        raise ValueError('Multiple frames')
    # All currently accepted explicit platform/label/country characters occupy
    # one terminal cell (including ●, ○ and ·); unknown text cannot enter here.
    widths = [7, 6, 6]
    for _, rows in groups:
        for row in rows:
            for index, cell in enumerate(row):
                widths[index] = max(widths[index], len(cell))
    padding = 0 if width < 20 else 1
    budget = width - 2 - 6 * padding
    while sum(widths) > budget:
        largest = max(range(3), key=lambda i: widths[i])
        if widths[largest] <= 4:
            raise ValueError('Unsupported column dimensions')
        widths[largest] -= 1
    if sum(widths) != budget:
        raise ValueError('Unexpected column dimensions')
    separator = '├' + '─' * (width-2) + '┤'
    at = 1

    def consume(cells, limits, heading=False):
        nonlocal at
        chunks = [[cell[i:i+limit] for i in range(0, len(cell), limit)] or [[]] for cell, limit in zip(cells, limits)]
        height = max(map(len, chunks))
        for part_index in range(height):
            if at >= len(lines)-1:
                raise ValueError('Missing wrapped terminal rows')
            expected = [('│', False, None)]
            for index, limit in enumerate(limits):
                chunk = chunks[index][part_index] if part_index < len(chunks[index]) else []
                expected += [(' ', False, None)] * padding + chunk + [(' ', False, None)] * (limit-len(chunk)+padding)
            expected.append(('│', False, None))
            actual = lines[at]
            if _plain(actual) != _plain(expected):
                raise ValueError('Terminal platform/ability/source-region differs from JSON')
            if not heading:
                for got, want in zip(actual, expected):
                    if want[0] != ' ' and got != want:
                        raise ValueError('Terminal independent fragment color differs from JSON')
            at += 1

    consume([_part('', s) for s in ('Service', 'Result', 'Region')], widths, heading=True)
    if at >= len(plain) or plain[at] != separator:
        raise ValueError('Wrong table header')
    at += 1
    for index, (title, rows) in enumerate(groups):
        consume([_part('', title)], [width-2-2*padding], heading=True)
        if at >= len(plain) or plain[at] != separator:
            raise ValueError('Missing/reordered internal section')
        at += 1
        for row in rows:
            consume(row, widths)
        expected_end = '╰' + '─' * (width-2) + '╯' if index == len(groups)-1 else separator
        if at >= len(plain) or plain[at] != expected_end:
            raise ValueError('Missing/extra platform rows or footer')
        at += 1
    if at != len(lines):
        raise ValueError('Extra terminal rows/frames')
