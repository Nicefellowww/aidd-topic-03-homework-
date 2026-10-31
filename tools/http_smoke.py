"""End-to-end smoke against a running local demo server using its database.
Run from repository root: .venv/bin/python tools/http_smoke.py http://127.0.0.1:8765
Creates two unique local test users; never prints or persists their passwords.
"""
import base64
import http.cookiejar
import json
import re
import secrets
import subprocess
import sys
from urllib.error import HTTPError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, build_opener, HTTPCookieProcessor

BASE = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8765'
assert urlparse(BASE).hostname in ('localhost', '127.0.0.1'), 'Local server only'


class Browser:
    def __init__(self):
        self.cookies = http.cookiejar.CookieJar()
        self.http = build_opener(HTTPCookieProcessor(self.cookies))
        self.checks = 0

    def request(self, path, data=None, method=None, expected=200, headers=None):
        body = urlencode(data).encode() if data is not None else None
        try:
            response = self.http.open(Request(BASE+path, body, headers or {}, method=method))
        except HTTPError as exc:
            response = exc
        text = response.read().decode()
        assert response.status == expected, (path, response.status, text[:200])
        self.checks += 1
        return text, response.geturl()

    def post(self, path, data, expected=200):
        text, _ = self.request(path)
        token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', text).group(1)
        return self.request(path, dict(data, csrfmiddlewaretoken=token), expected=expected)

    def register(self):
        self.email = 'http-'+secrets.token_hex(6)+'@example.test'
        self.password = secrets.token_urlsafe(24)
        self.post('/user/registration/', dict(email=self.email, password1=self.password, password2=self.password))


def command(*args):
    subprocess.run([sys.executable, 'manage.py', *args], check=True, capture_output=True)


owner, other = Browser(), Browser()
owner.request('/')
owner.request('/user/login/')
owner.request('/admin/')  # redirects to admin login
owner.request('/api/v1/shares/', {}, expected=403)
for path in ('/watches/', '/portfolios/', '/strategies/'):
    assert '/user/login/' in owner.request(path)[1]
owner.register()
shares = json.loads(owner.request('/api/v1/shares/?ticker=DEMO1')[0])['results']
share = shares[0]['id']
assert json.loads(owner.request('/api/v1/shares/?search=DEMO&ordering=-ticker&limit=1')[0])['results'][0]['ticker'] == 'DEMO3'
command('demo_price', 'DEMO1', '100')  # explicit initial price before strategy
owner.post('/watches/', dict(share=share, direction='le', target='95'))
_, path = owner.post('/portfolios/', dict(name='HTTP private portfolio', currency='rub'))
portfolio_path = path.removeprefix(BASE)
for side, quantity, price in [('buy', 2, 100), ('buy', 3, 120), ('sell', 2, 130)]:
    owner.post(portfolio_path, dict(share=share, side=side, quantity=quantity, price=price))
text, _ = owner.post(portfolio_path, dict(share=share, side='sell', quantity=4, price=130))
assert 'сверх позиции' in text
_, path = owner.post('/strategies/', dict(name='HTTP private strategy', share=share,
    buy_below=100, sell_above=120, quantity=2, initial_capital=1000, enabled='on'))
strategy_path = path.removeprefix(BASE)
command('demo_price', 'DEMO1', '90')
text, _ = owner.request('/watches/')
assert 'DEMO1: 90' in text
read_path = re.search(r'action="(/notifications/\d+/read/)"', text).group(1)
# Owner POST-only forms: supply the session CSRF cookie.
token = next(cookie.value for cookie in owner.cookies if cookie.name == 'csrftoken')
owner.request(read_path, {'csrfmiddlewaretoken': token})
command('demo_price', 'DEMO1', '125')
command('process_investing'); command('process_investing')
text, _ = owner.request(strategy_path)
assert '1070' in text and '70' in text
text, _ = owner.request(portfolio_path)
assert all(value in text for value in ('112', '375', '39', '36'))
text, _ = owner.request(f'/history/{share}/')
assert 'Plotly.newPlot' in text and 'demo' in text
text, _ = owner.request(f'/history/{share}/?start=2000-01-01&end=2000-01-02')
assert 'сохранённых котировок нет' in text
text, _ = owner.request(f'/{share}')
assert 'Plotly.newPlot' in text and 'height' in text
other.register()
for path in (portfolio_path, strategy_path):
    other.request(path, expected=404)
    token2 = next(cookie.value for cookie in other.cookies if cookie.name == 'csrftoken')
    other.request(path, {'csrfmiddlewaretoken': token2}, expected=404)
text, _ = other.request('/watches/')
assert 'DEMO1: 90' not in text
for path, secret in [('/portfolios/', 'HTTP private portfolio'), ('/strategies/', 'HTTP private strategy')]:
    assert secret not in other.request(path)[0]
watch_delete = re.search(r'action="(/watches/\d+/delete/)"', owner.request('/watches/')[0]).group(1)
other.request(watch_delete, {'csrfmiddlewaretoken': token2}, expected=404)
other.request(read_path, {'csrfmiddlewaretoken': token2}, expected=404)
owner.request(watch_delete, {'csrfmiddlewaretoken': token})
# Preserve and exercise old HTML CRUD on an unrelated instrument.
unique = secrets.token_hex(3)
data = dict(figi='HTTP-'+unique, uid='HTTP-'+unique, isin='HTTP-'+unique,
            ticker='H'+unique, name='HTTP CRUD', currency='rub', last_price='10.5')
owner.post('/create', data)
item = json.loads(owner.request('/api/v1/shares/?ticker='+data['ticker'])[0])['results'][0]
owner.post('/update/'+str(item['id']), dict(data, name='HTTP updated'))
owner.post('/delete/'+str(item['id']), {})
# API CRUD with Basic authentication on disposable, unreferenced share.
auth = 'Basic '+base64.b64encode(f'{owner.email}:{owner.password}'.encode()).decode()
api = Browser()
headers = {'Authorization': auth}
text, _ = api.request('/api/v1/shares/', data, expected=201, headers=headers)
api_id = json.loads(text)['id']
api.request(f'/api/v1/shares/{api_id}/', {'name': 'API updated'}, method='PATCH', headers=headers)
api.request(f'/api/v1/shares/{api_id}/', method='DELETE', expected=204, headers=headers)
owner.request('/user/logout/', {'csrfmiddlewaretoken': token})
owner.post('/user/login/', dict(email=owner.email, password=owner.password))
print(f'PASS: {owner.checks+other.checks+api.checks} real HTTP requests; personal flows, ownership, old HTML/API CRUD, auth, history and graphs.')
print('Strategy page:', BASE+strategy_path)
print('History page:', f'{BASE}/history/{share}/')
