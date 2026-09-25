import os
import io
import json
import uuid
import secrets
import threading
import logging
from urllib.parse import quote
from functools import wraps
from flask import Flask, request, jsonify, render_template, send_file, Response, session, redirect, url_for

from subtitle_parser import parse_subtitle, rebuild
from translator import ENGINES, batch_translate

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB
app.config['PERMANENT_SESSION_LIFETIME'] = 86400  # 24h

APP_VERSION = os.environ.get('APP_VERSION', 'dev')

DATA_DIR = os.environ.get('DATA_DIR', '/data')
os.makedirs(DATA_DIR, exist_ok=True)

# ===== Persisted secret key =====
def _load_secret_key():
    key_file = os.path.join(DATA_DIR, '.flask_secret_key')
    try:
        with open(key_file, 'r') as f:
            return f.read().strip()
    except (OSError, IOError):
        key = secrets.token_hex(32)
        with open(key_file, 'w') as f:
            f.write(key)
        os.chmod(key_file, 0o600)
        return key

app.secret_key = _load_secret_key()

# ===== Auth config =====
AUTH_FILE=os.path.join(DATA_DIR, "auth.json")

def load_auth():
    """Load username/password from auth file."""
    try:
        with open(AUTH_FILE, 'r') as f:
            return json.load(f)
    except (OSError, IOError):
        return None

def save_auth(username, password):
    """Save username/password to auth file."""
    with open(AUTH_FILE, 'w') as f:
        json.dump({'username': username, 'password': password}, f)
    os.chmod(AUTH_FILE, 0o600)

def is_auth_enabled():
    return load_auth() is not None

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if is_auth_enabled() and not session.get('logged_in'):
            # API requests get JSON error, page requests get redirected
            if request.path.startswith('/api/'):
                return jsonify({'error': '未登录', 'auth_required': True}), 401
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


@app.route('/login', methods=['GET', 'POST'])
def login():
    if not is_auth_enabled():
        return redirect(url_for('index'))
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')
        auth = load_auth()
        if auth and username == auth['username'] and password == auth['password']:
            session.clear()
            session['logged_in'] = True
            session.permanent = True
            return redirect(url_for('index'))
        error = '用户名或密码错误'
    return render_template('login.html', error=error, version=APP_VERSION)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/api/auth/status')
def auth_status():
    return jsonify({
        'auth_enabled': is_auth_enabled(),
        'logged_in': bool(session.get('logged_in')),
    })


@app.route('/api/auth/change-password', methods=['POST'])
@login_required
def change_password():
    data = request.get_json()
    old_password = data.get('old_password', '')
    new_password = data.get('new_password', '')

    if not new_password or len(new_password) < 4:
        return jsonify({'error': '新密码至少4位'}), 400

    auth = load_auth()
    if not auth:
        return jsonify({'error': '认证未启用'}), 400

    if old_password != auth['password']:
        return jsonify({'error': '旧密码错误'}), 403

    save_auth(auth['username'], new_password)
    return jsonify({'ok': True})


# ===== In-memory task store =====
tasks = {}


@app.route('/')
@login_required
def index():
    return render_template('index.html', engines=ENGINES, version=APP_VERSION)


@app.route('/api/preview', methods=['POST'])
@login_required
def preview():
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
    return jsonify({
        'format': detected_fmt,
        'total': len(entries),
        'preview': entries[:10],
    })


def run_translation_task(task_id, entries, content, engine, source, target, api_key, base_url, output_format, detected_fmt):
    task = tasks[task_id]
    texts = [e['text'] for e in entries]
    total = len(texts)
    task['total'] = total
    task['entries'] = entries
    task['original_entries'] = [dict(e) for e in entries]
    task['content'] = content
    task['detected_fmt'] = detected_fmt

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
        for j in range(i, min(i + len(batch), total)):
            if j < len(results):
                entries[j]['text'] = results[j]

    for i, entry in enumerate(entries):
        entry['text'] = results[i] if i < len(results) else entry['text']

    out_fmt = detected_fmt if output_format == 'auto' else output_format
    result_text = rebuild(entries, out_fmt, original_content=content)
    task['result'] = result_text
    task['errors'] = errors
    task['status'] = 'done'
    task['done'] = total
    task['output_fmt'] = out_fmt


@app.route('/api/translate', methods=['POST'])
@login_required
def start_translate():
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

    task_id = str(uuid.uuid4())[:8]
    tasks[task_id] = {
        'status': 'pending', 'total': len(entries), 'done': 0,
        'result': None, 'errors': [], 'filename': filename,
        'target': target, 'fmt': detected_fmt if output_format == 'auto' else output_format,
    }
    t = threading.Thread(target=run_translation_task, args=(
        task_id, entries, content, engine, source, target, api_key, base_url, output_format, detected_fmt
    ))
    t.daemon = True
    t.start()
    return jsonify({'task_id': task_id, 'total': len(entries)})


@app.route('/api/progress/<task_id>')
@login_required
def progress(task_id):
    task = tasks.get(task_id)
    if not task:
        return jsonify({'error': '任务不存在'}), 404
    resp = {
        'status': task['status'], 'total': task['total'],
        'done': task['done'], 'errors': task['errors'],
    }
    if task['status'] in ('translating', 'done') and 'entries' in task:
        resp['entries'] = task['entries']
        resp['original_entries'] = task.get('original_entries', [])
    return jsonify(resp)


@app.route('/api/edit/<task_id>', methods=['POST'])
@login_required
def edit_entry(task_id):
    task = tasks.get(task_id)
    if not task:
        return jsonify({'error': '任务不存在'}), 404
    data = request.get_json()
    index = data.get('index')
    text = data.get('text')
    if index is None or text is None:
        return jsonify({'error': '缺少参数'}), 400
    entries = task.get('entries', [])
    if 0 <= index < len(entries):
        entries[index]['text'] = text
        out_fmt = task.get('output_fmt', task.get('fmt', 'srt'))
        task['result'] = rebuild(entries, out_fmt, original_content=task.get('content', ''))
        return jsonify({'ok': True})
    return jsonify({'error': '索引超出范围'}), 400


@app.route('/api/retranslate/<task_id>', methods=['POST'])
@login_required
def retranslate_entry(task_id):
    task = tasks.get(task_id)
    if not task:
        return jsonify({'error': '任务不存在'}), 404
    data = request.get_json()
    index = data.get('index')
    engine = data.get('engine', 'google')
    source = data.get('source', 'auto')
    target = data.get('target', 'zh-CN')
    api_key = data.get('api_key', '')
    base_url = data.get('base_url', '')
    if index is None:
        return jsonify({'error': '缺少索引'}), 400
    entries = task.get('entries', [])
    if not (0 <= index < len(entries)):
        return jsonify({'error': '索引超出范围'}), 400
    original_entries = task.get('original_entries', [])
    original_text = original_entries[index]['text'] if index < len(original_entries) else entries[index]['text']
    engine_info = ENGINES.get(engine, ENGINES['google'])
    func = engine_info['func']
    try:
        if engine == 'libre':
            translated = func(original_text, source=source, target=target, api_key=api_key, base_url=base_url or 'http://localhost:5001')
        elif engine == 'deepl':
            translated = func(original_text, source=source, target=target, api_key=api_key)
        elif engine == 'mymemory':
            translated = func(original_text, source=source if source != 'auto' else 'en', target=target, api_key=api_key)
        else:
            translated = func(original_text, source=source, target=target, api_key=api_key)
        entries[index]['text'] = translated
        out_fmt = task.get('output_fmt', task.get('fmt', 'srt'))
        task['result'] = rebuild(entries, out_fmt, original_content=task.get('content', ''))
        return jsonify({'ok': True, 'text': translated})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/download/<task_id>')
@login_required
def download(task_id):
    task = tasks.get(task_id)
    if not task:
        return jsonify({'error': '任务不存在'}), 404
    if task['status'] != 'done':
        return jsonify({'error': '翻译尚未完成'}), 400
    base_name = os.path.splitext(task['filename'])[0]
    out_filename = f'{base_name}.{task["target"]}.{task["fmt"]}'
    result = task['result']
    encoded = quote(out_filename)
    ascii_name = encoded.replace('%', 'X')[:50]
    cd = 'attachment; filename="' + ascii_name + '"; filename*=UTF-8' + chr(39) + chr(39) + encoded
    return Response(result, mimetype='application/octet-stream', headers={'Content-Disposition': cd})


@app.route('/api/engines')
@login_required
def engines():
    return jsonify({k: {'label': v['label'], 'needs_key': v['needs_key']} for k, v in ENGINES.items()})


@app.route('/health')
def health():
    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5200, debug=True)
