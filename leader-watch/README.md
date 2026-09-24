# 주도주 레이더 클라우드 실행

기존 Yebro/global-52-week-highs-automation 계정, GitHub Pages, Telegram 비밀값을 재사용한다.
기존 신고가 트래커와 독립된 수집·점수·메시지를 사용하되 Pages 배포는 같은 동시실행 그룹에서 직렬화하고 두 데이터 파일을 모두 보존한다.

- 한국시간 평일 16:00 시작, 16:20/16:40 복구 시도. 이미 정상 발송한 날에는 재실행하지 않는다. GitHub 예약 실행은 지연 또는 누락 가능.
- XKRX 캘린더로 휴장일과 특별 거래 종료시간을 확인. 임시 휴장·거래시간 변경은 캘린더 업데이트로 반영해야 한다. 개장일의 오래된 시세는 오류이며 휴장으로 간주하지 않는다.
- 전체 코스피·코스닥 목록을 새로 수집. 시총 4천억 이상과 이전 후보 관찰, 기존 5천억 기준 점수 산식 보존.
- state/snapshots: 원본 일별 snapshot의 gzip 기록. state/raw: 수집 원자료·해시 목록. 비교는 직전 성공한 날짜 기준이며 누락 거래일을 꾸며내지 않는다.
- public: 공개 가능한 후보 요약·화면 조각만 게시. 웹의 Case Library와 과거 보고서는 기존 Sites에 유지.
- Telegram: 기존 정식 후보의 양의 점수 증가폭 상위 3개. 신규 편입은 별도. 첫 기록/버전 불일치는 순위 없음. 점수 증가에 과열 감점 해제가 기여하면 그대로 설명.
- 발송 예약 상태를 원격에 먼저 저장한 후 보내고, 성공 응답의 message_id를 다시 저장. 응답 유실이나 실행 강제 종료로 상태가 pending이면 자동 재발송을 막는다. 수신함 확인 후 해당 영수증만 관리자가 정리해야 한다.
- 정상 발송은 웹 데이터 게시 성공 뒤 수행. 실패는 하루 한 번 별도 알림. 봇 자체가 불능이면 GitHub Actions 실패 상태로 확인.
- workflow_dispatch의 setup-test는 저장된 기준일을 명시하는 실제 연결 테스트. 신규 시세나 수익률을 만들지 않는다.

필요한 기존 설정: secrets.TELEGRAM_BOT_TOKEN, vars.TELEGRAM_CHAT_ID. 소스나 로그에 값을 적지 않는다.

공개 사이트: https://kr-leader-radar-sep26.paullee0618.chatgpt.site/
공개 피드: https://yebro.github.io/global-52-week-highs-automation/leaders/monitor-fragment.json
