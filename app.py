import os
import io
import json
import logging
from flask import Flask, request, jsonify, render_template, send_file, Response

from subtitle_parser import parse_subtitle, rebuild
from translator import ENGINES, batch_translate

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB

APP_VERSION = os.environ.get('APP_VERSION', 'dev')


@app.route('/')
def index():
    return render_template('index.html', engines=ENGINES, version=APP_VERSION)


@app.route('/api/translate', methods=['POST'])
def translate():
    """Upload subtitle file and translate."""
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
    output_format = request.form.get('format', 'auto')  # auto=same as input

    # Parse subtitle
    try:
        entries, detected_fmt = parse_subtitle(filename, content)
    except Exception as e:
        return jsonify({'error': f'解析字幕失败: {str(e)}'}), 400

    if not entries:
        return jsonify({'error': '未检测到字幕内容'}), 400

    # Extract texts
    texts = [e['text'] for e in entries]

    # Translate
    try:
        translated_texts, errors = batch_translate(
            texts, engine=engine, source=source, target=target,
            api_key=api_key, base_url=base_url, batch_size=20
        )
    except Exception as e:
        return jsonify({'error': f'翻译失败: {str(e)}'}), 500

    # Rebuild
    for i, entry in enumerate(entries):
        entry['text'] = translated_texts[i] if i < len(translated_texts) else entry['text']

    out_fmt = detected_fmt if output_format == 'auto' else output_format
    result = rebuild(entries, out_fmt, original_content=content)

    # Return as downloadable file
    base_name = os.path.splitext(filename)[0]
    out_filename = f'{base_name}.{target}.{out_fmt}'

    return Response(
        result,
        mimetype='application/octet-stream',
        headers={'Content-Disposition': f'attachment; filename="{out_filename}"'}
    )


@app.route('/api/preview', methods=['POST'])
def preview():
    """Preview translation without downloading."""
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

    # Return first 10 entries for preview
    preview_entries = entries[:10]
    return jsonify({
        'format': detected_fmt,
        'total': len(entries),
        'preview': preview_entries,
    })


@app.route('/api/engines')
def engines():
    return jsonify({k: {'label': v['label'], 'needs_key': v['needs_key']} for k, v in ENGINES.items()})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5200, debug=True)
# CI retrigger
