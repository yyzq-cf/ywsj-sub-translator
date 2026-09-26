import os
import io
import json
import uuid
import secrets
import threading
import logging
import sqlite3
import time
from urllib.parse import quote
from functools import wraps
from flask import Flask, request, jsonify, render_template, send_file, Response, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash

from subtitle_parser import parse_subtitle, rebuild, rebuild_bilingual
from translator import (ENGINES, batch_translate, test_llm_connection, 
    LLM_PRESETS, fetch_llm_models, TRANSLATE_API_PRESETS,
    translate_tencent, translate_baidu, translate_youdao)

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

# ===== SQLite database =====
DB_FILE = os.path.join(DATA_DIR, "app.db")

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS auth (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            username TEXT NOT NULL,
            password TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS llm_configs (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            base_url TEXT NOT NULL,
            api_key TEXT NOT NULL,
            model TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS translate_api_configs (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            engine TEXT NOT NULL,
            api_key TEXT,
            secret_key TEXT
        );
    """)
    conn.commit()
    conn.close()

init_db()

# ===== Auth =====
def load_auth():
    conn = get_db()
    row = conn.execute("SELECT username, password FROM auth WHERE id = 1").fetchone()
    conn.close()
    if row:
        return {'username': row['username'], 'password': row['password']}
    return None

def save_auth(username, password):
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO auth (id, username, password) VALUES (1, ?, ?)",
        (username, generate_password_hash(password))
    )
    conn.commit()
    conn.close()

# ===== LLM configs =====
def load_llm_configs():
    conn = get_db()
    rows = conn.execute("SELECT id, name, base_url, api_key, model FROM llm_configs ORDER BY name").fetchall()
    conn.close()
    return [{'id': r['id'], 'name': r['name'], 'base_url': r['base_url'],
             'api_key': r['api_key'], 'model': r['model']} for r in rows]

def save_llm_configs(configs):
    conn = get_db()
    conn.execute("DELETE FROM llm_configs")
    for c in configs:
        conn.execute(
            "INSERT INTO llm_configs (id, name, base_url, api_key, model) VALUES (?, ?, ?, ?, ?)",
            (c['id'], c.get('name',''), c.get('base_url',''), c.get('api_key',''), c.get('model',''))
        )
    conn.commit()
    conn.close()

# ===== Translate API configs =====
def load_translate_api_configs():
    conn = get_db()
    rows = conn.execute("SELECT id, name, engine, api_key, secret_key FROM translate_api_configs ORDER BY name").fetchall()
    conn.close()
    return [{'id': r['id'], 'name': r['name'], 'engine': r['engine'],
             'api_key': r['api_key'] or '', 'secret_key': r['secret_key'] or ''} for r in rows]

def save_translate_api_configs(configs):
    conn = get_db()
    conn.execute("DELETE FROM translate_api_configs")
    for c in configs:
        conn.execute(
            "INSERT INTO translate_api_configs (id, name, engine, api_key, secret_key) VALUES (?, ?, ?, ?, ?)",
            (c['id'], c.get('name',''), c.get('engine',''), c.get('api_key',''), c.get('secret_key',''))
        )
    conn.commit()
    conn.close()


def is_auth_enabled():
    return load_auth() is not None

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not is_auth_enabled():
            if request.path.startswith('/api/'):
                return jsonify({'error': '未初始化', 'setup_required': True}), 401
            return redirect(url_for('setup'))
        if not session.get('logged_in'):
            if request.path.startswith('/api/'):
                return jsonify({'error': '未登录', 'auth_required': True}), 401
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


@app.route('/setup', methods=['GET', 'POST'])
def setup():
    if is_auth_enabled():
        return redirect(url_for('login'))
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm', '')
        if not username or not password:
            error = '用户名和密码不能为空'
        elif len(password) < 4:
            error = '密码至少4位'
        elif password != confirm:
            error = '两次输入的密码不一致'
        else:
            save_auth(username, password)
            session.clear()
            session['logged_in'] = True
            session.permanent = True
            return redirect(url_for('index'))
    return render_template('setup.html', error=error, version=APP_VERSION)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if not is_auth_enabled():
        return redirect(url_for('setup'))
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')
        auth = load_auth()
        if auth and username == auth['username'] and check_password_hash(auth['password'], password):
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
        'setup_required': not is_auth_enabled(),
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

    if not check_password_hash(auth['password'], old_password):
        return jsonify({'error': '旧密码错误'}), 403

    save_auth(auth['username'], new_password)
    return jsonify({'ok': True})


# ===== In-memory task store =====
tasks = {}


@app.route('/settings')
@login_required
def settings():
    return render_template('settings.html', version=APP_VERSION)


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


def run_translation_task(task_id, entries, content, engine, source, target, api_key, base_url, output_format, detected_fmt, model='gpt-4o-mini', secret_key=''):
    task = tasks[task_id]
    texts = [e['text'] for e in entries]
    total = len(texts)
    task['total'] = total
    task['entries'] = entries
    task['original_entries'] = [dict(e) for e in entries]
    task['content'] = content
    task['detected_fmt'] = detected_fmt

    def _log(msg):
        import datetime
        ts = datetime.datetime.now().strftime('%H:%M:%S')
        task['logs'].append(f'[{ts}] {msg}')
        if len(task['logs']) > 200:
            task['logs'] = task['logs'][-200:]

    _log(f'开始翻译: {total} 条字幕, 引擎={engine}, 目标语言={target}')
    if engine == 'llm':
        from translator import translate_llm
        func = translate_llm
    else:
        engine_info = ENGINES.get(engine, ENGINES['google'])
        func = engine_info['func']
    results = []
    errors = []
    batch_size = 10

    def _is_already_target(text, target):
        if target.startswith('zh'):
            return any('\u4e00' <= c <= '\u9fff' for c in text)
        if target == 'en':
            has_latin = any('a' <= c.lower() <= 'z' for c in text)
            has_cjk = any('\u4e00' <= c <= '\u9fff' for c in text)
            return has_latin and not has_cjk
        if target == 'ja':
            return any('\u3040' <= c <= '\u309f' or '\u30a0' <= c <= '\u30ff' for c in text)
        if target == 'ko':
            return any('\uac00' <= c <= '\ud7af' for c in text)
        return False

    def _do_translate(text):
        if engine == 'libre':
            return func(text, source=source, target=target, api_key=api_key, base_url=base_url or 'http://localhost:5001')
        elif engine == 'deepl':
            return func(text, source=source, target=target, api_key=api_key)
        elif engine == 'llm':
            _log(f'第 {i+1}-{min(i+len(batch), total)} 条: 发送到LLM翻译...')
            return func(text, source=source, target=target, api_key=api_key, base_url=base_url, model=model)
        else:
            return func(text, source=source, target=target, api_key=api_key)

    for i in range(0, total, batch_size):
        batch = texts[i:i + batch_size]
        need_translate = []
        need_indices = []
        batch_results = []
        for j, text in enumerate(batch):
            if _is_already_target(text, target):
                batch_results.append(text)
            else:
                batch_results.append(None)
                need_translate.append(text)
                need_indices.append(len(batch_results) - 1)

        if not need_translate:
            _log(f'第 {i+1}-{min(i+len(batch), total)} 条: 已是目标语言, 跳过')
            results.extend(batch_results)
        elif engine == 'llm':
            _log(f'第 {i+1}-{min(i+len(batch), total)} 条: 发送到LLM翻译...')
            # LLM: use smaller batches (3) for progress + speed balance
            llm_batch = 10
            for li in range(0, len(need_indices), llm_batch):
                sub_indices = need_indices[li:li+llm_batch]
                sub_texts = [batch[idx] for idx in sub_indices]
                separator = '\n---\n'
                combined = separator.join(sub_texts)
                try:
                    translated = _do_translate(combined)
                    parts = translated.split('\n---\n')
                    if len(parts) == len(sub_texts):
                        for sidx, part in zip(sub_indices, parts):
                            batch_results[sidx] = part
                    else:
                        for sidx, stext in zip(sub_indices, sub_texts):
                            try:
                                batch_results[sidx] = _do_translate(stext)
                            except Exception as e:
                                errors.append(f'Line {i+sidx+1}: {str(e)}')
                except Exception as e:
                    errors.append(f'Batch {i//batch_size+1}: {str(e)}')
                # Update progress after each sub-batch
                done_count = len(results) + sum(1 for r in batch_results if r)
                task['done'] = min(done_count, total)
                task['status'] = 'translating'
                for j in range(len(batch_results)):
                    global_j = i + j
                    if global_j < len(entries) and batch_results[j]:
                        entries[global_j]['text'] = batch_results[j]
            results.extend(batch_results)
        else:
            separator = '\n---\n'
            combined = separator.join(need_translate)
            try:
                translated = _do_translate(combined)
                parts = translated.split('\n---\n')
                if len(parts) == len(need_translate):
                    for idx, part in zip(need_indices, parts):
                        batch_results[idx] = part
                else:
                    for idx in need_indices:
                        text = batch[idx]
                        try:
                            batch_results[idx] = _do_translate(text)
                            task['done'] = min(len(results) + idx + 1, total)
                        except Exception as e:
                            errors.append(f'Line {i+idx+1}: {str(e)}')
                            _log(f'第 {i+idx+1} 条翻译失败: {str(e)[:50]}')
                import time
                time.sleep(0.3)
            except Exception as e:
                errors.append(f'Batch {i // batch_size + 1}: {str(e)}')
                logger.error(f'Batch {i//batch_size+1} failed: {e}')

            results.extend(batch_results)

        task['done'] = min(len(results), total)
        task['status'] = 'translating'
        for j in range(i, min(i + len(batch), total)):
            if j < len(results) and results[j]:
                entries[j]['text'] = results[j]

    for i, entry in enumerate(entries):
        if i < len(results) and results[i]:
            entry['text'] = results[i]

    out_fmt = detected_fmt if output_format == 'auto' else output_format
    result_text = rebuild(entries, out_fmt, original_content=content)
    task['result'] = result_text
    task['errors'] = errors
    task['status'] = 'done'
    task['done'] = total
    task['output_fmt'] = out_fmt
    _log(f'翻译完成! 共 {total} 条, 错误 {len(errors)} 条')

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

    # Parse LLM config: engine can be 'llm:<config_id>'
    llm_config_id = request.form.get('llm_config_id', '')
    if engine.startswith('llm:'):
        llm_config_id = engine[4:]
        engine = 'llm'

    # Parse translate API config: engine can be 'tapi:<config_id>'
    tapi_config = None
    secret_key = ''
    if engine.startswith('tapi:'):
        tapi_id = engine[4:]
        for cfg in load_translate_api_configs():
            if cfg['id'] == tapi_id:
                tapi_config = cfg
                engine = cfg['engine']
                api_key = cfg.get('api_key', '')
                secret_key = cfg.get('secret_key', '')
                break
    target = request.form.get('target', 'zh-CN')
    api_key = request.form.get('api_key', '')
    base_url = request.form.get('base_url', '')
    model = request.form.get('model', 'gpt-4o-mini')
    output_format = request.form.get('format', 'auto')

    if engine == 'llm' and llm_config_id:
        for cfg in load_llm_configs():
            if cfg['id'] == llm_config_id:
                api_key = cfg.get('api_key', '')
                base_url = cfg.get('base_url', '')
                model = cfg.get('model', 'gpt-4o-mini')
                break

    try:
        entries, detected_fmt = parse_subtitle(filename, content)
    except Exception as e:
        return jsonify({'error': f'解析字幕失败: {str(e)}'}), 400
    if not entries:
        return jsonify({'error': '未检测到字幕内容'}), 400

    task_id = str(uuid.uuid4())[:8]
    tasks[task_id] = {
        'status': 'pending', 'total': len(entries), 'done': 0,
        'result': None, 'errors': [], 'logs': [], 'filename': filename,
        'target': target, 'fmt': detected_fmt if output_format == 'auto' else output_format,
    }
    t = threading.Thread(target=run_translation_task, args=(
        task_id, entries, content, engine, source, target, api_key, base_url, output_format, detected_fmt, model, secret_key
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
        'logs': task.get('logs', []),
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
    model = data.get('model', 'gpt-4o-mini')
    llm_config_id = data.get('llm_config_id', '')

    # Parse llm: prefix
    if engine.startswith('llm:'):
        llm_config_id = engine[4:]
        engine = 'llm'

    if index is None:
        return jsonify({'error': '缺少索引'}), 400

    if llm_config_id:
        for cfg in load_llm_configs():
            if cfg['id'] == llm_config_id:
                api_key = cfg.get('api_key', '')
                base_url = cfg.get('base_url', '')
                model = cfg.get('model', 'gpt-4o-mini')
                break
    entries = task.get('entries', [])
    if not (0 <= index < len(entries)):
        return jsonify({'error': '索引超出范围'}), 400
    original_entries = task.get('original_entries', [])
    original_text = original_entries[index]['text'] if index < len(original_entries) else entries[index]['text']
    def _log(msg):
        import datetime
        ts = datetime.datetime.now().strftime('%H:%M:%S')
        task['logs'].append(f'[{ts}] {msg}')
        if len(task['logs']) > 200:
            task['logs'] = task['logs'][-200:]

    _log(f'开始翻译: {total} 条字幕, 引擎={engine}, 目标语言={target}')
    if engine == 'llm':
        from translator import translate_llm
        func = translate_llm
    else:
        engine_info = ENGINES.get(engine, ENGINES['google'])
        func = engine_info['func']
    try:
        if engine == 'libre':
            translated = func(original_text, source=source, target=target, api_key=api_key, base_url=base_url or 'http://localhost:5001')
        elif engine == 'deepl':
            translated = func(original_text, source=source, target=target, api_key=api_key)
        elif engine == 'llm':
            _log(f'第 {i+1}-{min(i+len(batch), total)} 条: 发送到LLM翻译...')
            translated = func(original_text, source=source, target=target, api_key=api_key, base_url=base_url, model=model)
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
    """Download translated file with optional bilingual mode."""
    task = tasks.get(task_id)
    if not task:
        return jsonify({'error': '任务不存在'}), 404
    if task['status'] != 'done':
        return jsonify({'error': '翻译尚未完成'}), 400

    subtitle_mode = request.args.get('mode', 'translated')
    order = request.args.get('order', 'original_first')

    entries = task.get('entries', [])
    original_entries = task.get('original_entries', [])
    out_fmt = task.get('output_fmt', task.get('fmt', 'srt'))
    orig_content = task.get('content', '')

    if subtitle_mode == 'bilingual':
        result = rebuild_bilingual(entries, original_entries, out_fmt, orig_content, mode='bilingual', order=order)
        suffix = '.bilingual'
    else:
        result = rebuild(entries, out_fmt, original_content=orig_content)
        suffix = ''

    base_name = os.path.splitext(task['filename'])[0]
    out_filename = f'{base_name}.{task["target"]}{suffix}.{out_fmt}'
    encoded = quote(out_filename)
    ascii_name = encoded.replace('%', 'X')[:50]
    cd = 'attachment; filename="' + ascii_name + '"; filename*=UTF-8' + chr(39) + chr(39) + encoded
    return Response(result, mimetype='application/octet-stream', headers={'Content-Disposition': cd})


@app.route('/api/engines')
@login_required
def engines():
    return jsonify({k: {'label': v['label'], 'needs_key': v['needs_key']} for k, v in ENGINES.items()})


@app.route('/api/llm-configs')
@login_required
def get_llm_configs():
    configs = load_llm_configs()
    safe = []
    for c in configs:
        sc = dict(c)
        if sc.get('api_key'):
            sc['api_key_masked'] = sc['api_key'][:8] + '...' if len(sc['api_key']) > 8 else '***'
            sc['has_key'] = True
        else:
            sc['has_key'] = False
        sc.pop('api_key', None)
        safe.append(sc)
    return jsonify(safe)


@app.route('/api/llm-configs/<config_id>/full')
@login_required
def get_llm_config_full(config_id):
    for cfg in load_llm_configs():
        if cfg['id'] == config_id:
            return jsonify(cfg)
    return jsonify({'error': '配置不存在'}), 404


@app.route('/api/llm-configs', methods=['POST'])
@login_required
def add_llm_config():
    data = request.get_json()
    name = data.get('name', '').strip()
    base_url = data.get('base_url', '').strip()
    api_key = data.get('api_key', '').strip()
    model = data.get('model', '').strip()
    if not name or not base_url or not model:
        return jsonify({'error': '名称、API地址、模型不能为空'}), 400
    configs = load_llm_configs()
    new_config = {
        'id': str(uuid.uuid4())[:8],
        'name': name, 'base_url': base_url,
        'api_key': api_key, 'model': model,
    }
    configs.append(new_config)
    save_llm_configs(configs)
    return jsonify({'ok': True, 'id': new_config['id']})


@app.route('/api/llm-configs/<config_id>', methods=['PUT'])
@login_required
def update_llm_config(config_id):
    data = request.get_json()
    configs = load_llm_configs()
    for c in configs:
        if c['id'] == config_id:
            if 'name' in data: c['name'] = data['name'].strip()
            if 'base_url' in data: c['base_url'] = data['base_url'].strip()
            if 'model' in data: c['model'] = data['model'].strip()
            if 'api_key' in data and data['api_key']: c['api_key'] = data['api_key'].strip()
            save_llm_configs(configs)
            return jsonify({'ok': True})
    return jsonify({'error': '配置不存在'}), 404


@app.route('/api/llm-configs/<config_id>', methods=['DELETE'])
@login_required
def delete_llm_config(config_id):
    configs = load_llm_configs()
    new_configs = [c for c in configs if c['id'] != config_id]
    if len(new_configs) == len(configs):
        return jsonify({'error': '配置不存在'}), 404
    save_llm_configs(new_configs)
    return jsonify({'ok': True})


@app.route('/api/llm-configs/test', methods=['POST'])
@login_required
def test_llm():
    data = request.get_json()
    config_id = data.get('config_id', '')
    if config_id:
        for cfg in load_llm_configs():
            if cfg['id'] == config_id:
                ok, msg = test_llm_connection(cfg['base_url'], cfg.get('api_key', ''), cfg['model'])
                return jsonify({'ok': ok, 'message': msg})
        return jsonify({'ok': False, 'message': '配置不存在'}), 404
    base_url = data.get('base_url', '').strip()
    api_key = data.get('api_key', '').strip()
    model = data.get('model', '').strip()
    if not base_url or not model:
        return jsonify({'ok': False, 'message': 'API地址和模型不能为空'}), 400
    ok, msg = test_llm_connection(base_url, api_key, model)
    return jsonify({'ok': ok, 'message': msg})


@app.route('/api/llm-models', methods=['POST'])
@login_required
def get_llm_models():
    data = request.get_json()
    base_url = data.get('base_url', '').strip()
    api_key = data.get('api_key', '').strip()
    config_id = data.get('config_id', '')
    if config_id:
        for cfg in load_llm_configs():
            if cfg['id'] == config_id:
                base_url = cfg.get('base_url', '')
                api_key = cfg.get('api_key', '')
                break
    if not base_url or not api_key:
        return jsonify({'error': '请先填写API地址和Key'}), 400
    try:
        from translator import fetch_llm_models
        models = fetch_llm_models(base_url, api_key)
        return jsonify({'ok': True, 'models': models})
    except Exception as e:
        return jsonify({'error': str(e)}), 200


@app.route('/api/llm-presets')
@login_required
def llm_presets():
    return jsonify(LLM_PRESETS)


@app.route('/api/translate-api-configs')
@login_required
def get_translate_api_configs():
    configs = load_translate_api_configs()
    safe = []
    for c in configs:
        sc = dict(c)
        if sc.get('api_key'):
            sc['api_key_masked'] = sc['api_key'][:6] + '...' if len(sc['api_key']) > 6 else '***'
            sc['has_key'] = True
        else:
            sc['has_key'] = False
        if sc.get('secret_key'):
            sc['secret_key_masked'] = sc['secret_key'][:6] + '...' if len(sc['secret_key']) > 6 else '***'
            sc['has_secret'] = True
        else:
            sc['has_secret'] = False
        sc.pop('api_key', None)
        sc.pop('secret_key', None)
        safe.append(sc)
    return jsonify(safe)


@app.route('/api/translate-api-configs', methods=['POST'])
@login_required
def add_translate_api_config():
    data = request.get_json()
    name = data.get('name', '').strip()
    engine = data.get('engine', '').strip()
    api_key = data.get('api_key', '').strip()
    secret_key = data.get('secret_key', '').strip()
    if not name or not engine:
        return jsonify({'error': '名称和引擎不能为空'}), 400
    configs = load_translate_api_configs()
    cfg = {
        'id': str(uuid.uuid4())[:8],
        'name': name, 'engine': engine,
        'api_key': api_key, 'secret_key': secret_key,
    }
    configs.append(cfg)
    save_translate_api_configs(configs)
    return jsonify({'ok': True, 'id': cfg['id']})


@app.route('/api/translate-api-configs/<config_id>', methods=['PUT'])
@login_required
def update_translate_api_config(config_id):
    data = request.get_json()
    configs = load_translate_api_configs()
    for c in configs:
        if c['id'] == config_id:
            if 'name' in data: c['name'] = data['name'].strip()
            if 'api_key' in data and data['api_key']: c['api_key'] = data['api_key'].strip()
            if 'secret_key' in data and data['secret_key']: c['secret_key'] = data['secret_key'].strip()
            save_translate_api_configs(configs)
            return jsonify({'ok': True})
    return jsonify({'error': '配置不存在'}), 404


@app.route('/api/translate-api-configs/<config_id>', methods=['DELETE'])
@login_required
def delete_translate_api_config(config_id):
    configs = load_translate_api_configs()
    new_configs = [c for c in configs if c['id'] != config_id]
    if len(new_configs) == len(configs):
        return jsonify({'error': '配置不存在'}), 404
    save_translate_api_configs(new_configs)
    return jsonify({'ok': True})


@app.route('/api/translate-api-configs/<config_id>/full')
@login_required
def get_translate_api_config_full(config_id):
    for cfg in load_translate_api_configs():
        if cfg['id'] == config_id:
            return jsonify(cfg)
    return jsonify({'error': '配置不存在'}), 404


@app.route('/api/translate-api-presets')
def get_translate_api_presets():
    return jsonify(TRANSLATE_API_PRESETS)


@app.route('/api/translate-api-configs/test', methods=['POST'])
@login_required
def test_translate_api():
    data = request.get_json()
    config_id = data.get('config_id', '')
    if config_id:
        for cfg in load_translate_api_configs():
            if cfg['id'] == config_id:
                engine = cfg.get('engine', '')
                api_key = cfg.get('api_key', '')
                secret_key = cfg.get('secret_key', '')
                break
        else:
            return jsonify({'ok': False, 'message': '配置不存在'}), 404
    else:
        engine = data.get('engine', '').strip()
        api_key = data.get('api_key', '').strip()
        secret_key = data.get('secret_key', '').strip()

    if not api_key or not secret_key:
        return jsonify({'ok': False, 'message': '请填写完整的Key和密钥'})

    try:
        if engine == 'tencent':
            from translator import translate_tencent
            result = translate_tencent('Hello', source='en', target='zh', api_key=api_key, secret_key=secret_key)
        elif engine == 'baidu':
            from translator import translate_baidu
            result = translate_baidu('Hello', source='en', target='zh', api_key=api_key, secret_key=secret_key)
        elif engine == 'youdao':
            from translator import translate_youdao
            result = translate_youdao('Hello', source='auto', target='zh-CHS', api_key=api_key, secret_key=secret_key)
        else:
            return jsonify({'ok': False, 'message': '未知的翻译引擎'})
        return jsonify({'ok': True, 'message': f'连接成功，翻译结果: {result}'})
    except Exception as e:
        return jsonify({'ok': False, 'message': str(e)[:200]})


@app.route('/api/cleanup', methods=['POST'])
@login_required
def cleanup():
    """Clear in-memory tasks."""
    cleared = len(tasks)
    tasks.clear()
    return jsonify({'ok': True, 'message': f'已清理 {cleared} 个翻译任务缓存'})


@app.route('/api/cleanup-docker', methods=['POST'])
@login_required
def cleanup_docker():
    """Clean unused Docker images and build cache."""
    import subprocess
    try:
        # Remove dangling images
        r1 = subprocess.run(['docker', 'image', 'prune', '-f'], capture_output=True, text=True, timeout=30)
        # Prune build cache
        r2 = subprocess.run(['docker', 'builder', 'prune', '-f'], capture_output=True, text=True, timeout=30)
        total_reclaimed = '0'
        for line in (r1.stdout + r2.stdout).split('\n'):
            if 'reclaimed' in line.lower() or 'Total' in line:
                total_reclaimed = line.strip()
        return jsonify({'ok': True, 'message': f'Docker清理完成. {total_reclaimed}'})
    except Exception as e:
        return jsonify({'ok': False, 'message': f'清理失败: {str(e)[:100]}'})


@app.route('/health')
def health():
    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5200, debug=True)
