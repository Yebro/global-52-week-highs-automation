"""Deterministic score-change briefing; no invented news or investment signals."""
import argparse
import json
from pathlib import Path


def components(r):
    return {
        '20일 상대강도 순위': 40 * r['rs20_percentile'],
        '60일 상대강도 순위': 25 * r['rs60_percentile'],
        '상대강도 순위 개선': 10 * max(0, min(1, r['rank_change'] / .2)),
        '거래대금 증가(근사)': 10 * min(1, r['value_acceleration'] / 1.5),
        '20일선 상회': 10 * (r['close'] > r['ma20']),
        '20일선 상승': 5 * (r['ma20_slope'] > 0),
        '과열 감점': -15 * r['extended'],
    }


def make_brief(current, previous=None):
    if current.get('score_version')=='entry-readiness-v2':
        from entry_brief import make_brief as entry_brief
        return entry_brief(current, previous)
    comparable = (previous is not None
                  and current.get('previous_asof') == previous['asof']
                  and current['score_version'] == previous['score_version'] == 'rs-price-v1')
    old = {r['code']: r for r in previous['metrics']} if comparable else {}
    candidates = [r for r in current['metrics'] if r['pool'] == 'candidate']
    ranked = []
    for r in candidates:
        p = old.get(r['code'])
        if not p or p['pool'] != 'candidate':
            continue
        delta = round(r['priority_score'] - p['priority_score'], 2)
        if delta <= 0:
            continue
        before, after = components(p), components(r)
        if abs(sum(after.values()) - r['priority_score']) > .011 or abs(sum(before.values()) - p['priority_score']) > .011:
            raise ValueError('Score component reconciliation failed')
        reasons = sorted([(k, round(after[k] - before[k], 2)) for k in after], key=lambda x: -x[1])
        ranked.append({'row': r, 'previous': p['priority_score'], 'delta': delta, 'reasons': reasons})
    ranked.sort(key=lambda x: (-x['delta'], -x['row']['priority_score'], x['row']['code']))
    lines = [f"주도주 레이더 | {current['asof']} 종가", f"정식 후보 {len(candidates)}종목 · 관찰 점수 상승 TOP 3"]
    if comparable:
        lines.append(f"비교: {previous['asof']} → {current['asof']} (직전 성공 수집일)")
    else:
        lines.append('비교 가능한 이전 기록이 없어 상승 순위를 산출하지 않았습니다.')
    if comparable and not ranked:
        lines.append('기존 후보 중 관찰 점수가 상승한 종목이 없습니다.')
    for i, item in enumerate(ranked[:3], 1):
        r = item['row']
        lines += ['', f"{i}. {r['name']} ({r['code']}) | {item['previous']:.2f} → {r['priority_score']:.2f}점 (+{item['delta']:.2f})"]
        positive = [(k, v) for k, v in item['reasons'] if v > 0]
        lines.append('상승 기여: ' + ', '.join(f'{k} +{v:.2f}점' for k, v in positive[:3]))
        negative = [(k, v) for k, v in item['reasons'] if v < 0]
        if negative:
            lines.append('감소 기여: ' + ', '.join(f'{k} {v:.2f}점' for k, v in negative))
        lines.append(f"가격: {r['close']:,.0f}원 · RS20 {r['rs20']:+.1%} · 20일선 이격 {r['distance_ma20']:+.1%}")
        lines.append(f"상태: {r['state']} · 60일 종가 고점 대비 {r['drawdown60']:+.1%}")
        flow = current.get('flows', {}).get(r['code'], {}).get('periods', {}).get('5', {})
        groups = flow.get('groups', {})
        if flow.get('observed_days') == 5 and all(groups.get(k, {}).get('net_shares') is not None for k in ['개인', '기관', '외국인']):
            lines.append('5거래일 수급(주): ' + ' / '.join(f"{k} {groups[k]['net_shares']:+,.0f}" for k in ['개인', '기관', '외국인']))
        else:
            lines.append('5거래일 수급: 데이터 확인 필요')
    if comparable and 0 < len(ranked) < 3:
        lines += ['', f'상승 종목이 {len(ranked)}개여서 해당 종목만 표시했습니다.']
    new_codes = {x['code'] for x in current.get('changes', {}).get('new', [])}
    new = sorted([r for r in candidates if r['code'] in new_codes], key=lambda r: (-r['priority_score'], r['code'])) if comparable else []
    lines += ['', f'신규 편입: {len(new)}종목' if comparable else '신규 편입: 비교 대기']
    if new:
        lines.append(', '.join(f"{r['name']} {r['priority_score']:.2f}점" for r in new[:5]) + (f' 외 {len(new)-5}종목' if len(new)>5 else ''))
    lines += ['', '점수는 관찰 우선순위이며 매수 신호가 아닙니다. 과열 감점 해제만으로도 점수가 오를 수 있습니다.',
              '상승 기여는 점수 산식의 변화입니다. 뉴스·실적의 인과관계는 별도 확인이 필요합니다.',
              '수급은 잠정치일 수 있으며 수량 기준입니다. 상대강도 순위는 비교 종목군 변화의 영향도 받습니다.']
    return '\n'.join(lines), [x['row']['code'] for x in ranked[:3]]


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('snapshot', type=Path)
    parser.add_argument('--previous', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    current = json.loads(args.snapshot.read_text(encoding='utf-8'))
    previous = json.loads(args.previous.read_text(encoding='utf-8')) if args.previous else None
    text, _ = make_brief(current, previous)
    args.output.write_text(text, encoding='utf-8')
