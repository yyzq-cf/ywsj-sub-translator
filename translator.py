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
    # Build URL: use /v1/ unless base_url already contains /v4/ or /v1/
    base = base_url.rstrip('/')
    if '/v4' in base or '/v1' in base:
        url = base + '/chat/completions'
    else:
        url = base + '/v1/chat/completions'
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

    resp = requests.post(url, json=payload, headers=headers, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    if 'choices' not in data:
        if 'msg' in data:
            raise Exception(data['msg'])
        if 'error' in data:
            err = data['error']
            raise Exception(err.get('message', str(err)) if isinstance(err, dict) else str(err))
        raise Exception(f'未知响应: {str(data)[:200]}')
    return data['choices'][0]['message']['content'].strip()


def test_llm_connection(base_url, api_key, model):
    """Test LLM connection, return (ok, message)."""
    try:
        # Build URL: use /v1/ unless base_url already contains /v4/ or /v1/
        base = base_url.rstrip('/')
        if '/v4' in base or '/v1' in base:
            url = base + '/chat/completions'
        else:
            url = base + '/v1/chat/completions'
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
        resp = requests.post(url, json=payload, headers=headers, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        # Check for non-standard error responses (e.g. 智谱 returns HTTP 200 with code:401)
        if 'choices' not in data:
            if 'msg' in data:
                return False, data['msg']
            if 'error' in data:
                err = data['error']
                if isinstance(err, dict):
                    return False, err.get('message', str(err))
                return False, str(err)
            return False, f'未知响应格式: {str(data)[:200]}'
        reply = data['choices'][0]['message']['content'].strip()
        return True, f'连接成功，模型回复: {reply}'
    except requests.exceptions.ConnectionError:
        return False, '无法连接到API地址'
    except requests.exceptions.Timeout:
        return False, '请求超时'
    except requests.exceptions.HTTPError as e:
        code = e.response.status_code
        try:
            err_body = e.response.json()
            if 'msg' in err_body:
                return False, f'HTTP {code}: {err_body["msg"]}'
            if 'error' in err_body:
                err = err_body['error']
                if isinstance(err, dict):
                    return False, f'HTTP {code}: {err.get("message", str(err))}'
                return False, f'HTTP {code}: {err}'
            return False, f'HTTP {code}: {str(err_body)[:200]}'
        except:
            return False, f'HTTP {code}'
    except KeyError as e:
        return False, f'响应格式异常，缺少字段: {e}'
    except Exception as e:
        return False, str(e)


def fetch_llm_models(base_url, api_key):
    """Fetch available models from OpenAI-compatible /v1/models endpoint."""
    base = base_url.rstrip('/')
    if '/v4' in base or '/v1' in base:
        url = base + '/models'
    else:
        url = base + '/v1/models'
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


# ===== Traditional translation API functions =====

def translate_tencent(text, source='auto', target='zh', api_key='', secret_key=''):
    """Use Tencent Machine Translation API."""
    import hashlib, hmac, time, random, base64
    secret_id = api_key
    secret_key_val = secret_key

    region = 'ap-beijing'
    endpoint = 'tmt.tencentcloudapi.com'
    params = {
        'SourceText': text,
        'Source': source if source != 'auto' else 'auto',
        'Target': target if target != 'zh-CN' else 'zh',
        'ProjectId': '0',
    }

    # Build signature
    service = 'tmt'
    timestamp = int(time.time())
    date = time.strftime('%Y-%m-%d', time.gmtime(timestamp))

    # Canonical request
    http_method = 'POST'
    canonical_uri = '/'
    canonical_querystring = ''
    canonical_headers = 'content-type:application/json; charset=utf-8\nhost:' + endpoint + '\nx-tc-action:TextTranslate\n'
    signed_headers = 'content-type;host;x-tc-action'
    hashed_payload = hashlib.sha256(json.dumps(params).encode('utf-8')).hexdigest()
    canonical_request = http_method + '\n' + canonical_uri + '\n' + canonical_querystring + '\n' + canonical_headers + '\n' + signed_headers + '\n' + hashed_payload

    # String to sign
    algorithm = 'TC3-HMAC-SHA256'
    credential_scope = date + '/' + service + '/tc3_request'
    hashed_canonical_request = hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()
    string_to_sign = algorithm + '\n' + str(timestamp) + '\n' + credential_scope + '\n' + hashed_canonical_request

    # Sign
    def _sign(key, msg):
        return hmac.new(key, msg.encode('utf-8'), hashlib.sha256).digest()

    secret_date = _sign(('TC3' + secret_key_val).encode('utf-8'), date)
    secret_service = _sign(secret_date, service)
    secret_signing = _sign(secret_service, 'tc3_request')
    signature = hmac.new(secret_signing, string_to_sign.encode('utf-8'), hashlib.sha256).hexdigest()

    authorization = algorithm + ' Credential=' + secret_id + '/' + credential_scope + ', SignedHeaders=' + signed_headers + ', Signature=' + signature

    headers = {
        'Authorization': authorization,
        'Content-Type': 'application/json; charset=utf-8',
        'Host': endpoint,
        'X-TC-Action': 'TextTranslate',
        'X-TC-Timestamp': str(timestamp),
        'X-TC-Version': '2018-03-21',
        'X-TC-Region': region,
    }

    resp = requests.post('https://' + endpoint, json=params, headers=headers, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return data['Response']['TargetText']


def translate_baidu(text, source='auto', target='zh', api_key='', secret_key=''):
    """Use Baidu Translate API."""
    import hashlib
    appid = api_key
    key = secret_key
    salt = str(random.randint(32768, 65536))
    sign_str = appid + text + salt + key
    sign = hashlib.md5(sign_str.encode('utf-8')).hexdigest()

    # Map language codes
    # Baidu language code mapping
    baidu_lang_map = {
        'zh-CN': 'zh', 'zh-TW': 'cht', 'en': 'en', 'ja': 'jp',
        'ko': 'kor', 'fr': 'fra', 'de': 'de', 'es': 'spa',
        'ru': 'ru', 'it': 'it', 'pt': 'pt', 'vi': 'vie',
        'th': 'th', 'ar': 'ara', 'auto': 'auto',
    }
    baidu_source = baidu_lang_map.get(source, source)
    baidu_target = baidu_lang_map.get(target, target)

    params = {
        'q': text,
        'from': baidu_source,
        'to': baidu_target,
        'appid': appid,
        'salt': salt,
        'sign': sign,
    }
    resp = requests.get('https://fanyi-api.baidu.com/api/trans/vip/translate', params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if 'error_code' in data:
        raise Exception(f"Baidu error {data['error_code']}: {data.get('error_msg', '')}")
    return chr(10).join(item['dst'] for item in data['trans_result'])


def translate_youdao(text, source='auto', target='zh-CHS', api_key='', secret_key=''):
    """Use Youdao Translate API (v3 signing)."""
    import hashlib, time as _time, uuid
    app_key = api_key
    app_secret = secret_key

    # Map language codes
    youdao_source = 'auto'
    youdao_target = target
    if target in ('zh-CN', 'zh'): youdao_target = 'zh-CHS'
    if target == 'zh-TW': youdao_target = 'zh-CHT'
    if target == 'en': youdao_target = 'en'
    if target == 'ja': youdao_target = 'ja'
    if target == 'ko': youdao_target = 'ko'
    if target == 'fr': youdao_target = 'fr'
    if target == 'de': youdao_target = 'de'
    if target == 'es': youdao_target = 'es'
    if target == 'ru': youdao_target = 'ru'
    if target == 'pt': youdao_target = 'pt'
    if target == 'vi': youdao_target = 'vi'
    if target == 'th': youdao_target = 'th'
    if target == 'ar': youdao_target = 'ara'

    # Build input (first 10 chars of text if > 10, else full text)
    input_str = text[:10] if len(text) > 10 else text
    salt = str(uuid.uuid4())
    curtime = str(int(_time.time()))
    # sign = sha256(appKey + input + salt + curtime + key)
    sign_str = app_key + input_str + salt + curtime + app_secret
    sign = hashlib.sha256(sign_str.encode('utf-8')).hexdigest()

    data = {
        'q': text,
        'from': youdao_source,
        'to': youdao_target,
        'appKey': app_key,
        'salt': salt,
        'sign': sign,
        'signType': 'v3',
        'curtime': curtime,
    }

    resp = requests.post('https://openapi.youdao.com/api', data=data, timeout=15)
    resp.raise_for_status()
    result = resp.json()
    if result.get('errorCode') != '0':
        raise Exception(f"Youdao error {result.get('errorCode')}: {result.get('errorCode', '')}")
    return chr(10).join(item['tgt'] for item in result.get('translation', []))


import random

# Traditional translation API presets
TRANSLATE_API_PRESETS = [
    {'name': '腾讯翻译', 'engine': 'tencent', 'key_name': 'SecretId', 'secret_name': 'SecretKey', 'key_url': 'https://console.cloud.tencent.com/cam/capi'},
    {'name': '百度翻译', 'engine': 'baidu', 'key_name': 'APP ID', 'secret_name': '密钥', 'key_url': 'https://fanyi-api.baidu.com/api/trans/product/desktop'},
    {'name': '有道翻译', 'engine': 'youdao', 'key_name': '应用ID', 'secret_name': '应用密钥', 'key_url': 'https://ai.youdao.com/console/'},
]


# Built-in LLM presets
LLM_PRESETS = [
    {'name': '硅基流动 SiliconFlow', 'base_url': 'https://api.siliconflow.cn', 'model': 'Qwen/Qwen2.5-7B-Instruct', 'key_url': 'https://cloud.siliconflow.cn/account/ak'},
    {'name': 'OpenAI', 'base_url': 'https://api.openai.com', 'model': 'gpt-4o-mini', 'key_url': 'https://platform.openai.com/api-keys'},
    {'name': 'DeepSeek', 'base_url': 'https://api.deepseek.com', 'model': 'deepseek-chat', 'key_url': 'https://platform.deepseek.com/api_keys'},
    {'name': '智谱 GLM', 'base_url': 'https://open.bigmodel.cn/api/paas/v4', 'model': 'glm-4-flash', 'key_url': 'https://open.bigmodel.cn/apikey/platform'},
    {'name': '月之暗面 Moonshot', 'base_url': 'https://api.moonshot.cn', 'model': 'moonshot-v1-8k', 'key_url': 'https://platform.moonshot.cn/console/api-keys'},
    {'name': 'OpenRouter (免费模型)', 'base_url': 'https://openrouter.ai/api/v1', 'model': 'nvidia/nemotron-3-super-120b-a12b:free', 'key_url': 'https://openrouter.ai/keys'},
    {'name': 'Ollama 本地', 'base_url': 'http://localhost:11434', 'model': 'qwen2.5:7b', 'key_url': ''},
    {'name': '自定义', 'base_url': '', 'model': '', 'key_url': ''},
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
# LLM batch size: 30
