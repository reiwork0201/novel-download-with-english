import os
import re
import requests
import subprocess
from bs4 import BeautifulSoup
from deepl import DeepLCLI

BASE_URL = 'https://ncode.syosetu.com'
HISTORY_FILE = '小説家になろうダウンロード経歴.txt'
LOCAL_HISTORY_PATH = f'/tmp/{HISTORY_FILE}'
REMOTE_HISTORY_PATH = f'drive:{HISTORY_FILE}'

DEEPL_LIMIT = 1500
TRANSLATABLE_ENDINGS = '[。！？⁈⁉?!]'
BRACKET_ENDINGS = '[」』】）]'

deepl = DeepLCLI("ja", "en")

def fetch_url(url):
    headers = {'User-Agent': 'Mozilla/5.0'}
    return requests.get(url, headers=headers)

def load_history():
    if not os.path.exists(LOCAL_HISTORY_PATH):
        subprocess.run(['rclone', 'copyto', REMOTE_HISTORY_PATH, LOCAL_HISTORY_PATH], check=False)
    history = {}
    if os.path.exists(LOCAL_HISTORY_PATH):
        with open(LOCAL_HISTORY_PATH, 'r', encoding='utf-8') as f:
            for line in f:
                match = re.match(r'(https?://[^\s|]+)\s*\|\s*(\d+)', line.strip())
                if match:
                    url, last = match.groups()
                    history[url.rstrip('/')] = int(last)
    return history

def save_history(history):
    with open(LOCAL_HISTORY_PATH, 'w', encoding='utf-8') as f:
        for url, last in history.items():
            f.write(f'{url}  |  {last}\n')
    subprocess.run(['rclone', 'copyto', LOCAL_HISTORY_PATH, REMOTE_HISTORY_PATH], check=True)

def is_inside_brackets(text, idx):
    bracket_stack = []
    brackets = {'「': '」', '『': '』', '【': '】', '(': ')'}
    for i, char in enumerate(text):
        if char in brackets:
            bracket_stack.append(brackets[char])
        elif char in brackets.values():
            if bracket_stack and bracket_stack[-1] == char:
                bracket_stack.pop()
        if i >= idx:
            break
    return bool(bracket_stack)

def split_text(text, limit=DEEPL_LIMIT):
    chunks = []
    position = 0
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    
    while position < len(text):
        last_good_boundary = None
        for match in re.finditer(f'{TRANSLATABLE_ENDINGS}|{BRACKET_ENDINGS}', text[position:position+limit+1]):
            end = position + match.end()
            if end - position > limit:
                break
            if not is_inside_brackets(text[position:end], match.end()-1):
                last_good_boundary = end

        if not last_good_boundary:
            end = min(position + limit, len(text))
            while end > position and not re.match(f'{TRANSLATABLE_ENDINGS}|{BRACKET_ENDINGS}', text[end - 1]):
                end -= 1
            last_good_boundary = end if end > position else position + limit

        chunk = text[position:last_good_boundary].strip()
        if chunk:
            chunks.append(chunk)
        position = last_good_boundary
    return chunks

def clean_and_retry_translation(chunk):
    translated = deepl.translate(chunk)
    # 残った日本語部分の抽出と再翻訳
    jp_regex = re.compile(r'[\u3040-\u30FF\u4E00-\u9FFF]+')
    if jp_regex.search(translated):
        for jp in jp_regex.findall(translated):
            try:
                en = deepl.translate(jp)
                translated = translated.replace(jp, en)
            except:
                continue
    return translated

script_dir = os.path.dirname(__file__)
url_file_path = os.path.join(script_dir, '小説家になろう.txt')
with open(url_file_path, 'r', encoding='utf-8') as f:
    urls = [line.strip().rstrip('/') for line in f if line.strip().startswith('http')]

history = load_history()

for novel_url in urls:
    try:
        print(f'\n=== 処理開始: {novel_url} ===')
        url = novel_url
        sublist = []

        while True:
            res = fetch_url(url)
            if not res.ok:
                raise Exception(f"HTTPエラー: {res.status_code}")
            soup = BeautifulSoup(res.text, 'html.parser')
            title_text = soup.find('title').get_text()
            sublist += soup.select('.p-eplist__sublist .p-eplist__subtitle')
            next_page = soup.select_one('.c-pager__item--next')
            if next_page and next_page.get('href'):
                url = f'{BASE_URL}{next_page.get("href")}'
            else:
                break

        for char in '<>:"/\\|?*':
            title_text = title_text.replace(char, '')
        title_text = title_text.strip()

        download_from = history.get(novel_url, 0)
        new_max = download_from

        for i, sub in enumerate(sublist):
            if i + 1 <= download_from:
                continue

            sub_title = sub.text.strip()
            link = sub.get('href')
            file_name = f'{i+1:03d}.txt'
            folder_num = (i // 999) + 1
            folder_name = f'{folder_num:03d}'

            base_path = f'/tmp/narou_dl/{title_text}'
            os.makedirs(base_path, exist_ok=True)
            jp_path = os.path.join(base_path, 'japanese', folder_name)
            en_path = os.path.join(base_path, 'english', folder_name)
            os.makedirs(jp_path, exist_ok=True)
            os.makedirs(en_path, exist_ok=True)
            jp_file = os.path.join(jp_path, file_name)
            en_file = os.path.join(en_path, file_name)

            res = fetch_url(f'{BASE_URL}{link}')
            soup = BeautifulSoup(res.text, 'html.parser')
            sub_body = soup.select_one('.p-novel__body')
            sub_body_text = sub_body.get_text() if sub_body else '[本文が取得できませんでした]'

            with open(jp_file, 'w', encoding='utf-8') as f:
                f.write(f'{sub_title}\n\n{sub_body_text}')

            translated_chunks = []
            for chunk in split_text(sub_body_text):
                try:
                    translated = clean_and_retry_translation(chunk)
                    translated_chunks.append(translated)
                except Exception as e:
                    print(f'翻訳エラー: {e}')
                    translated_chunks.append("[翻訳失敗]")

            translated_text = '\n'.join(translated_chunks)
            with open(en_file, 'w', encoding='utf-8') as f:
                f.write(f'{sub_title}\n\n{translated_text}')

            print(f'{file_name} saved & translated in {folder_name} ({i+1}/{len(sublist)})')
            new_max = i + 1

        history[novel_url] = new_max

    except Exception as e:
        print(f'[エラー] {novel_url} → {e}')
        continue

save_history(history)
subprocess.run(['rclone', 'copy', '/tmp/narou_dl', 'drive:', '--transfers=4', '--checkers=8', '--fast-list'], check=True)
