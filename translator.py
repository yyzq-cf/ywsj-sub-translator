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


def translate_mymemory(text, source='en', target='zh-CN', api_key=''):
    """Use MyMemory free translation API."""
    url = 'https://api.mymemory.translated.net/get'
    params = {
        'q': text,
        'langpair': f'{source}|{target}',
    }
    if api_key:
        params['de'] = api_key
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()['responseData']['translatedText']


ENGINES = {
    'google': {'func': translate_google, 'label': 'Google翻译', 'needs_key': False, 'default_target': 'zh-CN'},
    'deepl': {'func': translate_deepl, 'label': 'DeepL', 'needs_key': True, 'default_target': 'ZH'},
    'libre': {'func': translate_libre, 'label': 'LibreTranslate', 'needs_key': False, 'default_target': 'zh'},
    'mymemory': {'func': translate_mymemory, 'label': 'MyMemory', 'needs_key': False, 'default_target': 'zh-CN'},
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
            elif engine == 'mymemory':
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
                        elif engine == 'mymemory':
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
