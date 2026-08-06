from flask import Flask, jsonify, request, render_template, session, redirect, url_for
from urllib.parse import urlparse, urljoin
from functools import wraps
import json
import os
import re
import urllib.request
from datetime import datetime, timedelta, timezone

# app.py はプロジェクト直下に置く。
# 実体（templates / static / data）は bousai_app/ 配下にあるので、そこを参照する。
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(BASE_DIR, 'bousai_app')

app = Flask(
    __name__,
    template_folder=os.path.join(APP_DIR, 'templates'),
    static_folder=os.path.join(APP_DIR, 'static'),
)
app.secret_key = 'your-secret-key-here'

# 管理者認証情報
ADMIN_CREDENTIALS = {
    'admin': '123'
}

# ────────────────────────────────
# 気象警報・注意報設定
PREFECTURE_CODE = "020000"  # 青森県
AREA_NAME = "青森市"

# 青森市の気象庁警報・注意報コード
# 既存の市区町村コードに加え、気象庁の class20Items で使われるコードも受け付ける
AREA_CODES = ("0220100", "1420500")

WARNING_URL = (
    f"https://www.jma.go.jp/bosai/warning/data/r8/{PREFECTURE_CODE}.json"
)

JST = timezone(timedelta(hours=9))

# 警報・注意報のコード一覧
WARNING_CODES = {
    "00": "解除",
    "02": "暴風雪警報",
    "03": "レベル3大雨警報",
    "04": "洪水警報",
    "05": "暴風警報",
    "06": "大雪警報",
    "07": "波浪警報",
    "08": "レベル3高潮警報",
    "09": "レベル3土砂災害警報",
    "10": "レベル2大雨注意報",
    "12": "大雪注意報",
    "13": "風雪注意報",
    "14": "雷注意報",
    "15": "強風注意報",
    "16": "波浪注意報",
    "17": "融雪注意報",
    "18": "洪水注意報",
    "19": "レベル2高潮注意報",
    "20": "濃霧注意報",
    "21": "乾燥注意報",
    "22": "なだれ注意報",
    "23": "低温注意報",
    "24": "霜注意報",
    "25": "着氷注意報",
    "26": "着雪注意報",
    "27": "その他の注意報",
    "29": "レベル2土砂災害注意報",
    "32": "暴風雪特別警報",
    "33": "レベル5大雨特別警報",
    "35": "暴風特別警報",
    "36": "大雪特別警報",
    "37": "波浪特別警報",
    "38": "レベル5高潮特別警報",
    "39": "レベル5土砂災害特別警報",
    "43": "レベル4大雨危険警報",
    "48": "レベル4高潮危険警報",
    "49": "レベル4土砂災害危険警報"
}

# ────────────────────────────────
# サンプルデータの読み込み
DATA_FILE = os.path.join(APP_DIR, 'data', 'shelters.json')
INSTRUCTIONS_FILE = os.path.join(APP_DIR, 'data', 'instructions.json')

def load_json(path, default):
    """JSONファイルを読み込む（存在しない・壊れている場合は default を返す）"""
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default

shelters = load_json(DATA_FILE, [])
instructions = load_json(INSTRUCTIONS_FILE, [])


def load_shelters():
    """現在のデータファイルから避難所一覧を読み込む"""
    global shelters
    shelters = load_json(DATA_FILE, [])
    return shelters


def save_instructions():
    """指示ボードのデータをファイルに保存する"""
    try:
        with open(INSTRUCTIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump(instructions, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def save_shelters():
    """避難所データをファイルに保存する"""
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(shelters, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def normalize_text(value):
    """類似度計算用に文字列を正規化する"""
    if not value:
        return ''
    normalized = re.sub(r'[^0-9A-Za-zぁ-んァ-ン一-龥]+', '', str(value)).lower()
    return normalized


def levenshtein_distance(left, right):
    """Levenshtein 距離を計算する"""
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)

    previous = list(range(len(right) + 1))
    for i, left_char in enumerate(left, start=1):
        current = [i]
        for j, right_char in enumerate(right, start=1):
            insertion = current[j - 1] + 1
            deletion = previous[j] + 1
            substitution = previous[j - 1] + (0 if left_char == right_char else 1)
            current.append(min(insertion, deletion, substitution))
        previous = current
    return previous[-1]


def similarity_score(left, right):
    """類似度スコアを 0.0 〜 1.0 で返す"""
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0

    normalized_left = normalize_text(left)
    normalized_right = normalize_text(right)
    if not normalized_left or not normalized_right:
        return 0.0

    distance = levenshtein_distance(normalized_left, normalized_right)
    max_length = max(len(normalized_left), len(normalized_right))
    return max(0.0, 1.0 - (distance / max_length))


def sliding_window_distances(query, text):
    """入力文字に対して、データ文字列を長さ query+1 の窓でスライド比較し、最小編集距離を返す"""
    if not query:
        return 0

    normalized_query = normalize_text(query)
    normalized_text = normalize_text(text)
    if not normalized_query or not normalized_text:
        return float('inf')

    if normalized_query in normalized_text:
        return 0

    window_length = len(normalized_query) + 1
    windows = []
    for start in range(0, len(normalized_text) - window_length + 1):
        windows.append(normalized_text[start:start + window_length])

    if not windows:
        windows = [normalized_text]

    return min(levenshtein_distance(normalized_query, window) for window in windows)


def get_similar_shelters(name='', address='', limit=5):
    """入力中の名前・住所に類似する既存避難所を返す"""
    queries = [value for value in (normalize_text(name), normalize_text(address)) if value]
    if not queries:
        return []

    matches = []
    for shelter in shelters:
        shelter_name = shelter.get('name', '')
        shelter_address = shelter.get('address', '')

        words = []
        for source in (shelter_name, shelter_address):
            words.extend(re.findall(r'[0-9A-Za-zぁ-んァ-ン一-龥]+', normalize_text(source)))

        if not words:
            continue

        distances = []
        for query in queries:
            distances.append(min(sliding_window_distances(query, word) for word in words if word))

        best_distance = min(distances) if distances else float('inf')
        if best_distance == float('inf'):
            continue

        score = max(0.0, 1.0 - (best_distance / max(1, len(queries[0]))))
        matches.append({
            'id': shelter.get('id'),
            'name': shelter_name,
            'address': shelter_address,
            'score': score,
            'distance': best_distance,
        })

    matches.sort(key=lambda item: item['distance'])
    return matches[:limit]
# ────────────────────────────────

# ────────────────────────────────
# 認証関連の設定とヘルパー関数
def is_safe_url(target):
    """リダイレクト先URLが安全かどうかチェック"""
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc

def login_required(f):
    """認証が必要なページに付けるデコレータ"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            # 現在のURLをnextパラメータとしてログイン画面にリダイレクト
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def get_japan_time():
    """日本時間（JST）の現在時刻を取得する"""
    return datetime.now(JST).strftime("%Y年%m月%d日 %H:%M")


def format_report_time(iso_str):
    """気象庁の発表時刻（ISO形式）をJSTの表示用文字列に変換する"""
    if not iso_str:
        return "不明"
    try:
        parsed = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
        if parsed.tzinfo:
            parsed = parsed.astimezone(JST)
        return parsed.strftime("%Y年%m月%d日 %H:%M")
    except ValueError:
        return iso_str


def filter_shelters(district=None):
    """district 指定があれば一致する避難所のみ、なければ全件を返す"""
    return [s for s in shelters if not district or s.get('district') == district]


def parse_area_warnings(warning_data):
    """気象庁の新形式JSONから対象市区町村の発表・継続中の情報を抽出する"""
    if not isinstance(warning_data, list):
        raise ValueError("気象庁の警報・注意報データが新形式の配列ではありません")

    warnings = []
    seen_codes = set()
    report_datetimes = []
    headline_text = ""

    for report in warning_data:
        if not isinstance(report, dict):
            continue

        report_datetime = report.get("reportDatetime")
        if isinstance(report_datetime, str) and report_datetime:
            report_datetimes.append(report_datetime)

        if not headline_text:
            headline = report.get("headlineText")
            if isinstance(headline, str) and headline:
                headline_text = headline

        warning = report.get("warning")
        if not isinstance(warning, dict):
            continue

        area_items = []
        for key in ("class10Items", "class20Items"):
            items = warning.get(key, [])
            if isinstance(items, list):
                area_items.extend(items)

        area = next(
            (
                item for item in area_items
                if isinstance(item, dict)
                and item.get("areaCode") in AREA_CODES
            ),
            None
        )
        if not area:
            continue

        kinds = area.get("kinds", [])
        if not isinstance(kinds, list):
            continue

        for kind in kinds:
            if not isinstance(kind, dict):
                continue

            status = kind.get("status", "")
            code = kind.get("code", "")
            if status not in ("発表", "継続") or not code or code in seen_codes:
                continue

            warnings.append({
                "name": WARNING_CODES.get(
                    code,
                    f"不明な警報・注意報 (コード: {code})"
                ),
                "code": code,
                "status": status
            })
            seen_codes.add(code)

    latest_report_datetime = max(report_datetimes, default="")
    return warnings, latest_report_datetime, headline_text


def get_weather_warnings():
    """対象市区町村の警報・注意報を取得する"""
    try:
        # 青森県の新形式（令和8年～）警報・注意報データを取得
        with urllib.request.urlopen(url=WARNING_URL, timeout=10) as res:
            warning_data = json.loads(res.read())

        warnings, report_datetime, headline_text = parse_area_warnings(warning_data)

        return {
            "area_name": AREA_NAME,
            "warnings": warnings,
            "headline_text": headline_text,
            "report_time": format_report_time(report_datetime),
            "last_fetch_time": get_japan_time()
        }

    except Exception:
        return {
            "area_name": AREA_NAME,
            "warnings": [],
            "headline_text": "気象情報の取得に失敗しました。",
            "report_time": "取得失敗",
            "last_fetch_time": get_japan_time(),
            "error": True
        }


# トップページ：templates/index.html を返す（住民向け指示も表示する）
@app.route('/')
def index():
    resident_notices = [i for i in instructions if i.get('target') == '住民']
    return render_template('index.html', resident_notices=resident_notices)

# ログインページ
@app.route('/login', methods=['GET', 'POST'])
def login():
    # リダイレクト先を取得（デフォルトは避難所登録画面）
    next_url = request.args.get('next') or request.form.get('next')

    # 安全でないURLの場合はデフォルトページにリダイレクト
    if not next_url or not is_safe_url(next_url):
        next_url = url_for('shelter_register')

    if request.method == 'POST':
        password = request.form.get('password', '').strip()

        # 認証チェック
        username = next(
            (name for name, registered_password in ADMIN_CREDENTIALS.items()
             if registered_password == password),
            None
        )
        if username:
            session['logged_in'] = True
            session['username'] = username
            # ログイン成功後は指定されたページにリダイレクト
            return redirect(next_url)
        return render_template('login.html', error=True, message="パスワードが正しくありません。", next=next_url)

    # ログイン済みの場合は指定されたページにリダイレクト
    if session.get('logged_in'):
        return redirect(next_url)

    return render_template('login.html', next=next_url)

# ログアウト
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# 避難所登録ページ
@app.route('/shelter_register', methods=['GET', 'POST'])
@login_required
def shelter_register():
    default_form = {
        'name': '',
        'capacity': '',
        'address': '',
        'label': '',
        'accessibility': '',
        'toilets_male': '',
        'toilets_female': '',
        'toilets_common': '',
        'features': ''
    }

    if request.method == 'POST':
        form_data = {
            'name': request.form.get('name', '').strip(),
            'capacity': request.form.get('capacity', '').strip(),
            'address': request.form.get('address', '').strip(),
            'label': request.form.get('label', '').strip(),
            'accessibility': request.form.get('accessibility', '').strip(),
            'toilets_male': request.form.get('toilets-male', '').strip(),
            'toilets_female': request.form.get('toilets-female', '').strip(),
            'toilets_common': request.form.get('toilets-common', '').strip(),
            'features': request.form.get('features', '').strip(),
        }

        errors = []
        if not form_data['name']:
            errors.append('避難所名を入力してください。')
        if not form_data['capacity']:
            errors.append('収容人数を入力してください。')
        else:
            try:
                int(form_data['capacity'])
            except ValueError:
                errors.append('収容人数は数値で入力してください。')
        if not form_data['address']:
            errors.append('住所を入力してください。')
        if not form_data['label']:
            errors.append('住所ラベルを選択してください。')

        if errors:
            similar_shelters = get_similar_shelters(form_data['name'], form_data['address'])
            return render_template(
                'shelter_register.html',
                success=False,
                errors=errors,
                form_data=form_data,
                similar_shelters=similar_shelters,
                message=''
            )

        shelter_id = max((s.get('id', 0) for s in shelters), default=0) + 1
        shelters.append({
            'id': shelter_id,
            'name': form_data['name'],
            'capacity': int(form_data['capacity']),
            'address': form_data['address'],
            'label': form_data['label'],
            'accessibility': form_data['accessibility'],
            'toilets': {
                'male': form_data['toilets_male'],
                'female': form_data['toilets_female'],
                'common': form_data['toilets_common'],
            },
            'features': form_data['features'],
        })
        save_shelters()

        return render_template(
            'shelter_register.html',
            success=True,
            errors=[],
            form_data=default_form,
            similar_shelters=[],
            message='避難所を登録しました。'
        )

    return render_template(
        'shelter_register.html',
        success=False,
        errors=[],
        form_data=default_form,
        similar_shelters=[],
        message=''
    )

# 避難所検索ページ
@app.route('/shelter_search')
def shelter_search():
    return render_template('shelter_search.html', shelters=shelters[:5])


@app.route('/shelter_similarity')
@login_required
def shelter_similarity():
    name = request.args.get('name', '').strip()
    address = request.args.get('address', '').strip()
    matches = get_similar_shelters(name, address, limit=5)
    return jsonify({'shelters': matches})

# 全施設一覧ページ
@app.route('/all_shelters')
def all_shelters():
    return render_template('search_results.html', results=shelters)


# 指示ボード：住民向けの指示を一覧で確認する
@app.route('/board')
@login_required
def board():
    resident_instructions = [i for i in instructions if i.get('target') == '住民']
    return render_template('board.html', instructions=resident_instructions)

# 検索結果ページ：templates/search_results.html を返す
@app.route('/search_results')
def search_results():
    # クエリパラメータを取得
    search_type = request.args.get('type', 'name')
    q = (request.args.get('q') or '').strip()
    include_crowded = request.args.get('include_crowded')
    only_accessible = request.args.get('only_accessible')

    # 空検索は全件表示
    if not q:
        results = list(shelters)
    else:
        q_lower = q.lower()
        results = []
        for s in shelters:
            if search_type == 'district':
                target = (s.get('district') or '').lower()
            else:
                target = (s.get('name') or '').lower()

            if q_lower in target:
                results.append(s)

    # 「混雑している避難所も含める」が未指定の場合は混雑フラグのある避難所を除外する
    if include_crowded != 'on':
        filtered = []
        for s in results:
            crowded = s.get('crowded') or s.get('status') == '混雑'
            if not crowded:
                filtered.append(s)
        results = filtered

    # バリアフリーのみフィルタ
    if only_accessible == 'on':
        results = [s for s in results if s.get('accessibility')]

    return render_template('search_results.html', results=results)

# JSON API：/shelters?district=地区名
@app.route('/shelters', methods=['GET'])
def get_shelters():
    results = filter_shelters(request.args.get('district'))

    if not results:
        # 見つからなければエラー JSON を返す
        return jsonify({'error': 'No shelters found'}), 404

    # 見つかったらリストを JSON で返す
    return jsonify(results)

# 気象警報・注意報API
@app.route('/api/weather_warnings')
def api_weather_warnings():
    """気象警報・注意報をJSON形式で返すAPI"""
    return jsonify(get_weather_warnings())

if __name__ == '__main__':
    app.run(debug=True, port=5000)
