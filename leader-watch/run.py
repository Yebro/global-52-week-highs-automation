"""Cloud entry point. Public dashboard data and private durable observations are separate."""
import argparse
import datetime as dt
import gzip
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
from daily_brief import make_brief
from telegram_delivery import send_once

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
STATE = ROOT / 'state'
DB = ROOT / 'leader-case-db'
TZ = dt.timezone(dt.timedelta(hours=9))
SITE = 'https://kr-leader-radar-sep26.paullee0618.chatgpt.site/'
FEED = 'https://yebro.github.io/global-52-week-highs-automation/leaders/'


def output(key, value):
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as f:
            f.write(f'{key}={value}\n')
    print(f'{key}={value}')


def persist():
    for args in [
        ['config', 'user.name', 'github-actions[bot]'],
        ['config', 'user.email', '41898282+github-actions[bot]@users.noreply.github.com'],
        ['add', 'leader-watch/state', 'leader-watch/public'],
    ]:
        subprocess.run(['git', *args], cwd=REPO, check=True)
    if subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=REPO).returncode:
        subprocess.run(['git', 'commit', '-m', 'Update leader watch observations and delivery state'], cwd=REPO, check=True)
        subprocess.run(['git', 'pull', '--rebase', 'origin', 'main'], cwd=REPO, check=True)
        subprocess.run(['git', 'push', 'origin', 'HEAD:main'], cwd=REPO, check=True)


def restore():
    files = sorted((STATE / 'snapshots').glob('*.json.gz'))
    if not files:
        raise RuntimeError('Previous snapshots missing; refuse to silently reset baseline')
    for file in files:
        day = file.name.removesuffix('.json.gz')
        dest = DB / 'monitoring' / day / 'snapshot.json'
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(gzip.decompress(file.read_bytes()))


def session_status(now):
    import exchange_calendars as xcals
    day = now.date().isoformat()
    calendar = xcals.get_calendar('XKRX')
    # Never extrapolate a holiday calendar beyond its known bounds.
    if not calendar.is_session(day):
        return 'holiday'
    if now.hour < 16 or now < calendar.session_close(day).to_pydatetime():
        return 'before_close'
    return 'open_day'


def prepare(mode):
    now = dt.datetime.now(TZ)
    today = now.date().isoformat()
    if mode != 'setup-test':
        status = session_status(now)
        if status != 'open_day':
            output('publish', 'false')
            output('status', status)
            return
        receipts = list((STATE / 'delivery').glob(today + '-*.json'))
        if any(json.loads(p.read_text(encoding='utf-8')).get('status') == 'sent' for p in receipts):
            output('publish', 'false')
            output('status', 'already_sent')
            return
    restore()
    if mode != 'setup-test':
        subprocess.run([sys.executable, str(ROOT / 'leader-radar/tools/monitor_market.py')], check=True)
        target = DB / 'monitoring' / today / 'snapshot.json'
        if not target.exists():
            raise RuntimeError('Open-day closing data unavailable; do not publish old quotes')
    else:
        # Probe the live source from the cloud too; do not relabel old data as today.
        subprocess.run([sys.executable, str(ROOT / 'leader-radar/tools/monitor_market.py')], check=True)
        target = sorted((DB / 'monitoring').glob('*/snapshot.json'))[-1]
    current = json.loads(target.read_text(encoding='utf-8'))
    before = current.get('previous_asof')
    previous = json.loads((DB / 'monitoring' / before / 'snapshot.json').read_text(encoding='utf-8')) if before else None
    message, top = make_brief(current, previous)
    if mode == 'setup-test':
        message = '클라우드 연결 테스트 · 과거 기준 자료, 오늘 시세 아님\n\n' + message
    message += '\n\n전체 후보: ' + SITE
    subprocess.run([sys.executable, str(ROOT / 'leader-radar/tools/build_monitor_page.py')], check=True)
    public = ROOT / 'public'
    public.mkdir(exist_ok=True)
    dashboard = (ROOT / 'leader-radar/dist/index.html').read_text(encoding='utf-8')
    fragment = re.search(r'<main>(.*?)</main>', dashboard, re.S).group(1)
    fragment = fragment.replace('매 개장일 16:00 점검 예정', '개장일 16:00 클라우드 점검 · 실행 지연 가능')
    fragment = fragment.replace('실제 점검에는 연결된 작업 환경과 데이터 접근이 필요합니다.', '코덱스와 PC가 꺼져 있어도 클라우드에서 실행합니다. 예약 실행과 데이터 반영은 지연될 수 있습니다.')
    fragment = fragment.replace('모든 상승을 표에 표시하고 +5점 이상은 주요 변화로 알립니다.', '모든 상승을 표에 표시하고, 기존 후보의 점수 상승폭 상위 3개를 개장일마다 텔레그램으로 요약합니다.')
    fragment = fragment.replace('href="monitor-latest.json"', f'href="{FEED}monitor-latest.json"')
    (public / 'monitor-fragment.json').write_text(json.dumps({'asof': current['asof'], 'html': fragment}, ensure_ascii=False), encoding='utf-8')
    (public / 'monitor-latest.json').write_bytes((ROOT / 'leader-radar/dist/monitor-latest.json').read_bytes())
    (STATE / 'snapshots' / f"{current['asof']}.json.gz").write_bytes(gzip.compress(target.read_bytes(), mtime=0))
    raw = target.parent / 'raw'
    if raw.exists() and any(raw.iterdir()):
        archives = STATE / 'raw'
        archives.mkdir(exist_ok=True)
        with tarfile.open(archives / f"{current['asof']}.tar.gz", 'w:gz') as archive:
            archive.add(raw, arcname='raw')
            manifest = target.parent / 'raw-manifest.json'
            if manifest.exists():
                archive.add(manifest, arcname='raw-manifest.json')
    key = ('setup-' + os.environ.get('GITHUB_RUN_ID', today)) if mode == 'setup-test' else current['asof']
    (ROOT / 'run-plan.json').write_text(json.dumps({'asof': current['asof'], 'key': key, 'text': message, 'mode': mode, 'top': top}, ensure_ascii=False), encoding='utf-8')
    output('publish', 'true')
    output('asof', current['asof'])


def notify():
    plan = json.loads((ROOT / 'run-plan.json').read_text(encoding='utf-8'))
    # This stage only runs after successful Pages deployment.
    status = send_once(plan['text'], plan['key'], STATE / 'delivery', checkpoint=persist)
    output('telegram', status)


def failure():
    day = dt.datetime.now(TZ).date().isoformat()
    run = os.environ.get('GITHUB_RUN_ID', '')
    text = f'주도주 레이더 {day}: 자동 갱신 또는 발송을 완료하지 못했습니다. 기존 성공 기록을 유지합니다.\n확인: https://github.com/Yebro/global-52-week-highs-automation/actions/runs/{run}'
    output('failure_notification', send_once(text, 'failure-' + day, STATE / 'delivery', checkpoint=persist))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['prepare', 'persist', 'notify', 'failure'])
    parser.add_argument('--mode', choices=['daily', 'setup-test'], default='daily')
    args = parser.parse_args()
    if args.action == 'prepare':
        prepare(args.mode)
    else:
        globals()[args.action]()
