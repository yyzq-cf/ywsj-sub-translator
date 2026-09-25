"""
Translation module - supports multiple translation engines.
"""

import requests
import time
import logging

logger = logging.getLogger(__name__)

# Language code mapping for different APIs
LANG_MAP = {
    'zh': 'zh',
    'zh-CN': 'zh-CN',
    'zh-TW': 'zh-TW',
    'en': 'en',
    'ja': 'ja',
    'ko': 'ko',
    'fr': 'fr',
    'de': 'de',
    'es': 'es',
    'ru': 'ru',
    'it': 'it',
    'pt': 'pt',
    'vi': 'vi',
    'th': 'th',
    'ar': 'ar',
    'hi': 'hi',
}


def translate_google(text, source='auto', target='zh-CN', api_key=''):
    """Use Google Translate (free endpoint)."""
    url = 'https://translate.googleapis.com/translate_a/single'
    params = {
        'client': 'gtx',
        'dt': 't',
        'sl': source,
        'tl': target,
        'q': text,
    }
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    return ''.join(part[0] for part in data[0] if part[0])


def translate_deepl(text, source='auto', target='ZH', api_key=''):
    """Use DeepL API."""
    url = 'https://api-free.deepl.com/v2/translate' if api_key.endswith(':fx') else 'https://api.deepl.com/v2/translate'
    data = {
        'text': text,
        'target_lang': target.upper(),
    }
    if source != 'auto':
        data['source_lang'] = source.upper()
    headers = {'Authorization': f'DeepL-Auth-Key {api_key}'}
    resp = requests.post(url, data=data, headers=headers, timeout=10)
    resp.raise_for_status()
    result = resp.json()
    return result['translations'][0]['text']


def translate_libre(text, source='auto', target='zh', api_key='', base_url='http://localhost:5001'):
    """Use LibreTranslate / self-hosted instance."""
    url = base_url.rstrip('/') + '/translate'
    data = {
        'q': text,
        'source': source,
        'target': target,
        'format': 'text',
    }
    if api_key:
        data['api_key'] = api_key
    resp = requests.post(url, data=data, timeout=15)
    resp.raise_for_status()
    return resp.json()['translatedText']


    """Use MyMemory free translation API."""
    params = {
        'q': text,
        'langpair': f'{source}|{target}',
    }
    if api_key:
        params['de'] = api_key
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()['responseData']['translatedText']


def translate_llm(text, source='auto', target='zh-CN', api_key='', base_url='', model='gpt-4o-mini'):
    """Use LLM via OpenAI-compatible API for translation."""
    url = base_url.rstrip('/') + '/v1/chat/completions'
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
    }

    # Build language names for the prompt
    lang_names = {
        'zh-CN': '简体中文', 'zh-TW': '繁體中文', 'en': 'English', 'ja': '日本語',
        'ko': '한국어', 'fr': 'Français', 'de': 'Deutsch', 'es': 'Español',
        'ru': 'Русский', 'it': 'Italiano', 'pt': 'Português', 'vi': 'Tiếng Việt',
        'th': 'ภาษาไทย', 'ar': 'العربية', 'hi': 'हिन्दी', 'tr': 'Türkçe',
        'nl': 'Nederlands', 'pl': 'Polski', 'id': 'Indonesia', 'zh': '中文',
    }
    target_name = lang_names.get(target, target)
    source_name = lang_names.get(source, 'auto-detected') if source != 'auto' else 'auto-detected'

    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': f'You are a professional subtitle translator. Translate the following subtitle text from {source_name} to {target_name}. Only output the translation, nothing else. Preserve any formatting, line breaks, and special characters. Do not add explanations.'},
            {'role': 'user', 'content': text},
        ],
        'temperature': 0.3,
    }

    resp = requests.post(url, json=payload, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data['choices'][0]['message']['content'].strip()


def test_llm_connection(base_url, api_key, model):
    """Test LLM connection, return (ok, message)."""
    try:
        url = base_url.rstrip('/') + '/v1/chat/completions'
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        }
        payload = {
            'model': model,
            'messages': [{'role': 'user', 'content': 'Hi, reply with "OK" only.'}],
            'max_tokens': 10,
            'temperature': 0,
        }
        resp = requests.post(url, json=payload, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        reply = data['choices'][0]['message']['content'].strip()
        return True, f'连接成功，模型回复: {reply}'
    except requests.exceptions.ConnectionError:
        return False, '无法连接到API地址'
    except requests.exceptions.Timeout:
        return False, '请求超时'
    except requests.exceptions.HTTPError as e:
        code = e.response.status_code
        try:
            err_msg = e.response.json().get('error', {}).get('message', str(e))
        except:
            err_msg = str(e)
        return False, f'HTTP {code}: {err_msg}'
    except Exception as e:
        return False, str(e)


def fetch_llm_models(base_url, api_key):
    """Fetch available models from OpenAI-compatible /v1/models endpoint."""
    url = base_url.rstrip('/') + '/v1/models'
    headers = {'Authorization': f'Bearer {api_key}'}
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    models = []
    for m in data.get('data', []):
        mid = m.get('id', '')
        if mid:
            models.append(mid)
    models.sort()
    return models


# Built-in LLM presets
LLM_PRESETS = [
    {'name': '硅基流动 SiliconFlow', 'base_url': 'https://api.siliconflow.cn', 'model': 'Qwen/Qwen2.5-7B-Instruct'},
    {'name': 'OpenAI', 'base_url': 'https://api.openai.com', 'model': 'gpt-4o-mini'},
    {'name': 'DeepSeek', 'base_url': 'https://api.deepseek.com', 'model': 'deepseek-chat'},
    {'name': '智谱 GLM', 'base_url': 'https://open.bigmodel.cn/api/paas', 'model': 'glm-4-flash'},
    {'name': '月之暗面 Moonshot', 'base_url': 'https://api.moonshot.cn', 'model': 'moonshot-v1-8k'},
    {'name': 'Ollama 本地', 'base_url': 'http://localhost:11434', 'model': 'qwen2.5:7b'},
    {'name': '自定义', 'base_url': '', 'model': ''},
]


ENGINES = {
    'google': {'func': translate_google, 'label': 'Google翻译', 'needs_key': False, 'default_target': 'zh-CN'},
    'deepl': {'func': translate_deepl, 'label': 'DeepL', 'needs_key': True, 'default_target': 'ZH'},
    'libre': {'func': translate_libre, 'label': 'LibreTranslate', 'needs_key': False, 'default_target': 'zh'},
}


def batch_translate(texts, engine='google', source='auto', target='zh-CN', api_key='', base_url='', batch_size=10):
    """
    Translate a list of texts in batches.
    Returns (translated_texts, errors).
    """
    engine_info = ENGINES.get(engine, ENGINES['google'])
    func = engine_info['func']
    results = []
    errors = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        # Join with separator for batch translation
        separator = '\n---\n'
        combined = separator.join(batch)
        try:
            if engine == 'libre':
                translated = func(combined, source=source, target=target, api_key=api_key, base_url=base_url or 'http://localhost:5001')
            elif engine == 'deepl':
                translated = func(combined, source=source, target=target, api_key=api_key)
                translated = func(combined, source=source if source != 'auto' else 'en', target=target, api_key=api_key)
            else:
                translated = func(combined, source=source, target=target, api_key=api_key)
            parts = translated.split('\n---\n')
            # If split count doesn't match, fall back to per-line
            if len(parts) == len(batch):
                results.extend(parts)
            else:
                # Translate one by one as fallback
                for text in batch:
                    try:
                        if engine == 'libre':
                            r = func(text, source=source, target=target, api_key=api_key, base_url=base_url or 'http://localhost:5001')
                        elif engine == 'deepl':
                            r = func(text, source=source, target=target, api_key=api_key)
                            r = func(text, source=source if source != 'auto' else 'en', target=target, api_key=api_key)
                        else:
                            r = func(text, source=source, target=target, api_key=api_key)
                        results.append(r)
                    except Exception as e:
                        results.append(text)
                        errors.append(f'Line {len(results)}: {str(e)}')
            time.sleep(0.3)  # Rate limit
        except Exception as e:
            results.extend(batch)  # Keep original on batch failure
            errors.append(f'Batch {i // batch_size + 1}: {str(e)}')

    return results, errors
