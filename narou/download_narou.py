import os
import re
import requests
import subprocess
from bs4 import BeautifulSoup
from deepl import DeepLCLI  # 自作のCLIラッパー

BASE_URL = 'https://ncode.syosetu.com'
HISTORY_FILE = '小説家になろうダウンロード経歴.txt'
LOCAL_HISTORY_PATH = f'/tmp/{HISTORY_FILE}'
REMOTE_HISTORY_PATH = f'drive:{HISTORY_FILE}'

DEEPL_RETRY = 3

DEEPL = DeepLCLI("ja", "en")

# rcloneアップロード前のエラー防止用に事前作成
os.makedirs('/tmp/narou_dl', exist_ok=True)

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

def clean_text(text):
    return re.sub(r'[\r\n]+', '', text).strip()

def split_by_delimiters(text):
    delimiters = set('。！？⁈⁉?!.」』】）]”>》}')
    open_brackets = {'「', '『', '【', '（', '[', '“', '<', '《', '{'}
    close_brackets = {'」', '』', '】', '）', ']', '”', '>', '》', '}'}

    chunks = []
    buf = ''
    stack = []

    for ch in text:
        buf += ch
        if ch in open_brackets:
            stack.append(ch)
        elif ch in close_brackets and stack:
            stack.pop()
        elif ch in delimiters and not stack:
            chunks.append(buf.strip())
            buf = ''

    if buf.strip():
        chunks.append(buf.strip())
    return chunks

def group_chunks(chunks, n=10):
    return [''.join(chunks[i:i+n]) for i in range(0, len(chunks), n)]

def translate_with_retry(text):
    for _ in range(DEEPL_RETRY):
        try:
            return DEEPL.translate(text)
        except Exception as e:
            print(f'翻訳失敗、リトライ: {e}')
    return '[翻訳失敗]'

def fix_incomplete_translation(original, translated):
    jp_in_en = re.findall(r'[\u3040-\u30ff\u4e00-\u9fff]+', translated)
    for frag in jp_in_en:
        translated_frag = translate_with_retry(frag)
        translated = translated.replace(frag, translated_frag)
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
            sub_body_text = clean_text(sub_body_text)

            with open(jp_file, 'w', encoding='utf-8') as f:
                f.write(f'{sub_title}\n\n{sub_body_text}')

            # 分割＆翻訳処理
            chunks = split_by_delimiters(sub_body_text)
            grouped_chunks = group_chunks(chunks, n=10)

            translated_chunks = []
            for group in grouped_chunks:
                translated = translate_with_retry(group)
                translated = fix_incomplete_translation(group, translated)
                translated_chunks.append(translated)

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
