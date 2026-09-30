import sqlite3


def _login(client):
    with client.session_transaction() as s:
        s['admin_logged_in'] = True


def _seed(status, roll, checked_in=False):
    with sqlite3.connect('students.db') as conn:
        conn.execute(
            "INSERT INTO students (name,email,roll_number,trans_id,status,placard_path,email_status,checked_in_at) "
            "VALUES (?,?,?,?,?,'p.jpg','sent',?)",
            ('Name ' + roll, roll.lower() + '@x.com', roll, 'T' + roll, status,
             '2026-01-01 10:00:00' if checked_in else None))


def test_confirmed_registration_visible_without_searching(client):
    _seed('CONFIRMED', 'CONF100')
    _login(client)
    html = client.get('/admin').get_data(as_text=True)
    assert 'CONF100' in html


def test_dashboard_shows_counts_per_status(client):
    _seed('CONFIRMED', 'CNT1')
    _seed('CONFIRMED', 'CNT2', checked_in=True)
    _seed('PENDING', 'CNT3')
    _seed('REJECTED', 'CNT4')
    _login(client)
    html = client.get('/admin').get_data(as_text=True)
    assert 'data-stat="total">4<' in html
    assert 'data-stat="confirmed">2<' in html
    assert 'data-stat="pending">1<' in html
    assert 'data-stat="rejected">1<' in html
    assert 'data-stat="checked-in">1<' in html


def test_status_filter_limits_the_list(client):
    _seed('CONFIRMED', 'FLT1')
    _seed('REJECTED', 'FLT2')
    _login(client)
    html = client.get('/admin?status=REJECTED').get_data(as_text=True)
    table = html.split('id="registrations"')[1].split('Pending Payment Verifications')[0]
    assert 'FLT2' in table and 'FLT1' not in table


def test_invalid_status_filter_is_ignored(client):
    _seed('CONFIRMED', 'FLT3')
    _login(client)
    resp = client.get("/admin?status=' OR 1=1 --")
    assert resp.status_code == 200 and 'FLT3' in resp.get_data(as_text=True)


def test_search_still_works_and_overrides_filter(client):
    _seed('CONFIRMED', 'SRCH1')
    _seed('CONFIRMED', 'OTHER1')
    _login(client)
    table = client.get('/admin?q=SRCH1').get_data(as_text=True).split('id="registrations"')[1]
    assert 'SRCH1' in table.split('Pending Payment Verifications')[0]
    assert 'OTHER1' not in table.split('Pending Payment Verifications')[0]
