import importlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_shelter_register_reports_missing_required_fields(tmp_path):
    app_module = importlib.import_module('app')
    app = app_module.app
    app.config['TESTING'] = True
    app_module.shelters[:] = []
    app_module.DATA_FILE = str(tmp_path / 'shelters.json')
    app_module.save_shelters()

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['logged_in'] = True
            sess['username'] = 'admin'

        response = client.post('/shelter_register', data={
            'name': '',
            'capacity': '',
            'address': '',
            'label': '',
            'accessibility': '',
            'toilets-male': '',
            'toilets-female': '',
            'toilets-common': '',
            'features': ''
        })

    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert '避難所名を入力してください。' in html
    assert '収容人数を入力してください。' in html
    assert '住所を入力してください。' in html
    assert '住所ラベルを選択してください。' in html


def test_parse_area_warnings_matches_aomori_city_code():
    app_module = importlib.import_module('app')
    warning_data = [
        {
            "reportDatetime": "2026-08-05T15:38:00+09:00",
            "headlineText": "濃霧注意報を発表します。",
            "warning": {
                "class20Items": [
                    {
                        "areaCode": "0220100",
                        "kinds": [
                            {"code": "20", "status": "発表"}
                        ]
                    }
                ]
            }
        }
    ]

    warnings, report_datetime, headline_text = app_module.parse_area_warnings(warning_data)

    assert warnings[0]["name"] == "濃霧注意報"
    assert warnings[0]["status"] == "発表"
    assert report_datetime == "2026-08-05T15:38:00+09:00"
    assert headline_text == "濃霧注意報を発表します。"


def test_shelter_register_shows_success_message(tmp_path):
    app_module = importlib.import_module('app')
    app = app_module.app
    app.config['TESTING'] = True
    app_module.shelters[:] = []
    app_module.DATA_FILE = str(tmp_path / 'shelters.json')
    app_module.save_shelters()

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['logged_in'] = True
            sess['username'] = 'admin'

        response = client.post('/shelter_register', data={
            'name': '新しい避難所',
            'capacity': '120',
            'address': '青森市花園',
            'label': '学校',
            'accessibility': 'あり',
            'toilets-male': '2',
            'toilets-female': '2',
            'toilets-common': '1',
            'features': '近くに公園あり'
        })

    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert '避難所を登録しました。' in html
    assert (tmp_path / 'shelters.json').exists()
    assert app_module.shelters[0]['name'] == '新しい避難所'
    assert app_module.shelters[0]['address'] == '青森市花園'


def test_home_page_has_text_size_and_language_controls():
    app_module = importlib.import_module('app')
    app = app_module.app
    app.config['TESTING'] = True

    with app.test_client() as client:
        response = client.get('/')

    html = response.get_data(as_text=True)
    assert '文字サイズを選択してください' in html
    assert '大' in html and '中' in html and '小' in html
    assert '日本語' in html and 'English' in html
    assert 'data-selected-size="small"' in html
    assert 'data-selected-language="ja"' in html


def test_similarity_endpoint_returns_matches():
    app_module = importlib.import_module('app')
    app = app_module.app
    app.config['TESTING'] = True
    app_module.shelters[:] = [{
        'id': 1,
        'name': '御所見小学校',
        'address': '青森市大字御所見',
        'capacity': 100,
        'label': '学校',
        'accessibility': 'あり',
        'toilets': {'male': '2', 'female': '2', 'common': '1'},
        'features': '近くに公園あり'
    }]

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['logged_in'] = True
            sess['username'] = 'admin'

        response = client.get('/shelter_similarity', query_string={'name': '御所見', 'address': '青森市'})

    data = json.loads(response.get_data(as_text=True))
    assert response.status_code == 200
    assert data['shelters']
    assert data['shelters'][0]['name'] == '御所見小学校'
