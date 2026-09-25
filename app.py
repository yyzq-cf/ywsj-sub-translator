import os
import io
import json
import uuid
import threading
import logging
from flask import Flask, request, jsonify, render_template, send_file, Response

from subtitle_parser import parse_subtitle, rebuild
from translator import ENGINES, batch_translate

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB

APP_VERSION = os.environ.get('APP_VERSION', 'dev')

# ===== In-memory task store (good enough for single-worker gunicorn) =====
tasks = {}


@app.route('/')
def index():
    return render_template('index.html', engines=ENGINES, version=APP_VERSION)


@app.route('/api/preview', methods=['POST'])
def preview():
    """Preview subtitle file - first 10 entries."""
    file = request.files.get('file')
    if not file:
        return jsonify({'error': '没有上传文件'}), 400

    filename = file.filename or 'subs.srt'
    raw = file.read()
    try:
        content = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        try:
            content = raw.decode('gbk')
        except UnicodeDecodeError:
            content = raw.decode('utf-8', errors='replace')

    try:
        entries, detected_fmt = parse_subtitle(filename, content)
    except Exception as e:
        return jsonify({'error': f'解析字幕失败: {str(e)}'}), 400

    if not entries:
        return jsonify({'error': '未检测到字幕内容'}), 400

    preview_entries = entries[:10]
    return jsonify({
        'format': detected_fmt,
        'total': len(entries),
        'preview': preview_entries,
    })


def run_translation_task(task_id, entries, content, engine, source, target, api_key, base_url, output_format, detected_fmt):
    """Background translation worker."""
    task = tasks[task_id]
    texts = [e['text'] for e in entries]
    total = len(texts)
    task['total'] = total

    engine_info = ENGINES.get(engine, ENGINES['google'])
    func = engine_info['func']
    results = []
    errors = []
    batch_size = 20

    for i in range(0, total, batch_size):
        batch = texts[i:i + batch_size]
        separator = '\n---\n'
        combined = separator.join(batch)
        try:
            if engine == 'libre':
                translated = func(combined, source=source, target=target, api_key=api_key, base_url=base_url or 'http://localhost:5001')
            elif engine == 'deepl':
                translated = func(combined, source=source, target=target, api_key=api_key)
            elif engine == 'mymemory':
                translated = func(combined, source=source if source != 'auto' else 'en', target=target, api_key=api_key)
            else:
                translated = func(combined, source=source, target=target, api_key=api_key)
            parts = translated.split('\n---\n')
            if len(parts) == len(batch):
                results.extend(parts)
            else:
                for text in batch:
                    try:
                        if engine == 'libre':
                            r = func(text, source=source, target=target, api_key=api_key, base_url=base_url or 'http://localhost:5001')
                        elif engine == 'deepl':
                            r = func(text, source=source, target=target, api_key=api_key)
                        elif engine == 'mymemory':
                            r = func(text, source=source if source != 'auto' else 'en', target=target, api_key=api_key)
                        else:
                            r = func(text, source=source, target=target, api_key=api_key)
                        results.append(r)
                    except Exception as e:
                        results.append(text)
                        errors.append(f'Line {len(results)}: {str(e)}')
            import time
            time.sleep(0.3)
        except Exception as e:
            results.extend(batch)
            errors.append(f'Batch {i // batch_size + 1}: {str(e)}')

        task['done'] = min(len(results), total)
        task['status'] = 'translating'

    # Rebuild
    for i, entry in enumerate(entries):
        entry['text'] = results[i] if i < len(results) else entry['text']

    out_fmt = detected_fmt if output_format == 'auto' else output_format
    result_text = rebuild(entries, out_fmt, original_content=content)
    task['result'] = result_text
    task['errors'] = errors
    task['status'] = 'done'
    task['done'] = total


@app.route('/api/translate', methods=['POST'])
def start_translate():
    """Start a translation task, return task_id for progress polling."""
    file = request.files.get('file')
    if not file:
        return jsonify({'error': '没有上传文件'}), 400

    filename = file.filename or 'subs.srt'
    raw = file.read()
    try:
        content = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        try:
            content = raw.decode('gbk')
        except UnicodeDecodeError:
            content = raw.decode('utf-8', errors='replace')

    engine = request.form.get('engine', 'google')
    source = request.form.get('source', 'auto')
    target = request.form.get('target', 'zh-CN')
    api_key = request.form.get('api_key', '')
    base_url = request.form.get('base_url', '')
    output_format = request.form.get('format', 'auto')

    try:
        entries, detected_fmt = parse_subtitle(filename, content)
    except Exception as e:
        return jsonify({'error': f'解析字幕失败: {str(e)}'}), 400

    if not entries:
        return jsonify({'error': '未检测到字幕内容'}), 400

    # Create task
    task_id = str(uuid.uuid4())[:8]
    tasks[task_id] = {
        'status': 'pending',
        'total': len(entries),
        'done': 0,
        'result': None,
        'errors': [],
        'filename': filename,
        'target': target,
        'fmt': detected_fmt if output_format == 'auto' else output_format,
    }

    # Start background thread
    t = threading.Thread(target=run_translation_task, args=(
        task_id, entries, content, engine, source, target, api_key, base_url, output_format, detected_fmt
    ))
    t.daemon = True
    t.start()

    return jsonify({'task_id': task_id, 'total': len(entries)})


@app.route('/api/progress/<task_id>')
def progress(task_id):
    """Poll translation progress."""
    task = tasks.get(task_id)
    if not task:
        return jsonify({'error': '任务不存在'}), 404

    return jsonify({
        'status': task['status'],
        'total': task['total'],
        'done': task['done'],
        'errors': task['errors'],
    })


@app.route('/api/download/<task_id>')
def download(task_id):
    """Download translated file."""
    task = tasks.get(task_id)
    if not task:
        return jsonify({'error': '任务不存在'}), 404
    if task['status'] != 'done':
        return jsonify({'error': '翻译尚未完成'}), 400

    base_name = os.path.splitext(task['filename'])[0]
    out_filename = f'{base_name}.{task["target"]}.{task["fmt"]}'

    # Clean up task after download
    result = task['result']
    # Keep task for a bit so progress endpoint still works after download

    from urllib.parse import quote
    encoded = quote(out_filename)
    cd = "attachment; filename="" + encoded + ""; filename*=UTF-8''" + encoded
    return Response(
        result,
        mimetype='application/octet-stream',
        headers={'Content-Disposition': cd}
    )


@app.route('/api/engines')
def engines():
    return jsonify({k: {'label': v['label'], 'needs_key': v['needs_key']} for k, v in ENGINES.items()})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5200, debug=True)
