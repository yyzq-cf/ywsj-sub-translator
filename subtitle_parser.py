"""
Subtitle parser module - supports SRT, VTT, ASS/SSA formats.
Each parsed entry is a dict: {index, start, end, text}
"""

import re


def parse_srt(content):
    """Parse SRT subtitle file."""
    entries = []
    blocks = re.split(r'\n\s*\n', content.strip())
    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) < 3:
            continue
        idx_line = lines[0].strip()
        time_line = lines[1].strip()
        text_lines = lines[2:]
        m = re.match(r'(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,.]\d{3})', time_line)
        if not m:
            continue
        entries.append({
            'index': idx_line,
            'start': m.group(1),
            'end': m.group(2),
            'text': '\n'.join(text_lines),
        })
    return entries


def parse_vtt(content):
    """Parse WebVTT subtitle file."""
    entries = []
    lines = content.strip().split('\n')
    i = 0
    if lines and lines[0].startswith('WEBVTT'):
        i = 1
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        m = re.match(r'(\d{2}:\d{2}:\d{2}\.\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}\.\d{3})', line)
        if m:
            start, end = m.group(1), m.group(2)
            i += 1
            text_lines = []
            while i < len(lines) and lines[i].strip():
                text_lines.append(lines[i])
                i += 1
            entries.append({
                'index': str(len(entries) + 1),
                'start': start,
                'end': end,
                'text': '\n'.join(text_lines),
            })
        else:
            i += 1
    return entries


def parse_ass(content):
    """Parse ASS/SSA subtitle file."""
    entries = []
    in_events = False
    format_fields = []
    for line in content.split('\n'):
        line = line.strip()
        if line.startswith('[Events]'):
            in_events = True
            continue
        if not in_events:
            continue
        if line.startswith('Format:'):
            format_fields = [f.strip() for f in line[7:].split(',')]
            continue
        if line.startswith('Dialogue:') and format_fields:
            data = [f.strip() for f in line[9:].split(',', len(format_fields) - 1)]
            row = dict(zip(format_fields, data))
            start = row.get('Start', '0:00:00.00')
            end = row.get('End', '0:00:00.00')
            text = row.get('Text', '')
            entries.append({
                'index': str(len(entries) + 1),
                'start': start,
                'end': end,
                'text': text,
            })
    return entries


def detect_format(filename, content):
    """Auto-detect subtitle format."""
    content_stripped = content.strip()
    if filename.lower().endswith('.ass') or filename.lower().endswith('.ssa'):
        return 'ass'
    if filename.lower().endswith('.vtt'):
        return 'vtt'
    if filename.lower().endswith('.srt'):
        return 'srt'
    if content_stripped.startswith('WEBVTT'):
        return 'vtt'
    if '[Events]' in content:
        return 'ass'
    return 'srt'


def parse_subtitle(filename, content):
    """Auto-detect and parse subtitle file."""
    fmt = detect_format(filename, content)
    if fmt == 'vtt':
        return parse_vtt(content), 'vtt'
    elif fmt == 'ass':
        return parse_ass(content), 'ass'
    else:
        return parse_srt(content), 'srt'


def rebuild_srt(entries):
    """Rebuild SRT from entries."""
    parts = []
    for i, e in enumerate(entries, 1):
        start = e['start'].replace('.', ',')
        end = e['end'].replace('.', ',')
        parts.append(f"{i}\n{start} --> {end}\n{e['text']}")
    return '\n\n'.join(parts) + '\n'


def rebuild_vtt(entries):
    """Rebuild VTT from entries."""
    parts = ['WEBVTT', '']
    for e in entries:
        start = e['start'].replace(',', '.')
        end = e['end'].replace(',', '.')
        parts.append(f"{start} --> {end}\n{e['text']}\n")
    return '\n'.join(parts)


def rebuild_ass(entries, original_content=''):
    """Rebuild ASS from entries, preserving header from original."""
    header = []
    in_events = False
    for line in original_content.split('\n'):
        if line.strip().startswith('[Events]'):
            in_events = True
            header.append('[Events]')
            continue
        if not in_events:
            header.append(line)
            continue
        if line.strip().startswith('Format:'):
            header.append(line)
            break
    parts = header
    for e in entries:
        parts.append(f"Dialogue: 0,{e['start']},{e['end']},Default,,0,0,0,,{e['text']}")
    return '\n'.join(parts) + '\n'


def rebuild_bilingual_srt(entries, original_entries, mode='bilingual', order='original_first'):
    """Rebuild SRT with bilingual or translation-only options."""
    parts = []
    for i, e in enumerate(entries, 1):
        start = e['start'].replace('.', ',')
        end = e['end'].replace('.', ',')
        orig = original_entries[i-1]['text'] if i-1 < len(original_entries) else ''
        trans = e['text']
        if mode == 'translated':
            text = trans
        elif order == 'original_first':
            text = orig + '\n' + trans
        else:
            text = trans + '\n' + orig
        parts.append(f"{i}\n{start} --> {end}\n{text}")
    return '\n\n'.join(parts) + '\n'


def rebuild_bilingual_vtt(entries, original_entries, mode='bilingual', order='original_first'):
    """Rebuild VTT with bilingual or translation-only options."""
    parts = ['WEBVTT', '']
    for i, e in enumerate(entries):
        start = e['start'].replace(',', '.')
        end = e['end'].replace(',', '.')
        orig = original_entries[i]['text'] if i < len(original_entries) else ''
        trans = e['text']
        if mode == 'translated':
            text = trans
        elif order == 'original_first':
            text = orig + '\n' + trans
        else:
            text = trans + '\n' + orig
        parts.append(f"{start} --> {end}\n{text}\n")
    return '\n'.join(parts)


def rebuild_bilingual_ass(entries, original_entries, original_content='', mode='bilingual', order='original_first'):
    """Rebuild ASS with bilingual or translation-only options."""
    header = []
    in_events = False
    for line in original_content.split('\n'):
        if line.strip().startswith('[Events]'):
            in_events = True
            header.append('[Events]')
            continue
        if not in_events:
            header.append(line)
            continue
        if line.strip().startswith('Format:'):
            header.append(line)
            break
    parts = header
    for i, e in enumerate(entries):
        orig = original_entries[i]['text'] if i < len(original_entries) else ''
        trans = e['text']
        if mode == 'translated':
            text = trans
        elif order == 'original_first':
            text = orig + '\\N' + trans
        else:
            text = trans + '\\N' + orig
        parts.append(f"Dialogue: 0,{e['start']},{e['end']},Default,,0,0,0,,{text}")
    return '\n'.join(parts) + '\n'


def rebuild_bilingual(entries, original_entries, fmt, original_content='', mode='bilingual', order='original_first'):
    """Rebuild subtitle with bilingual options."""
    if fmt == 'vtt':
        return rebuild_bilingual_vtt(entries, original_entries, mode, order)
    elif fmt == 'ass':
        return rebuild_bilingual_ass(entries, original_entries, original_content, mode, order)
    else:
        return rebuild_bilingual_srt(entries, original_entries, mode, order)


def rebuild(entries, fmt, original_content=''):
    """Rebuild subtitle in the given format."""
    if fmt == 'vtt':
        return rebuild_vtt(entries)
    elif fmt == 'ass':
        return rebuild_ass(entries, original_content)
    else:
        return rebuild_srt(entries)
