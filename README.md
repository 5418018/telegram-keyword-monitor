# Telegram keyword monitor

GitHub Actions가 구독 중인 텔레그램 채널을 주기적으로 확인하고, 키워드에 맞는 새 글만 개인 텔레그램 봇으로 전송합니다. 공개 저장소의 표준 GitHub-hosted runner를 이용하는 구성을 전제로 합니다.

## 보안 원칙

- `TELEGRAM_SESSION`, `TELEGRAM_API_HASH`, `BOT_TOKEN`은 절대 파일에 적거나 커밋하지 않습니다.
- 모든 인증정보와 개인 설정은 GitHub Repository Secrets에만 저장합니다.
- 저장소에는 본인 외의 collaborator를 추가하지 않는 것을 권장합니다.
- 세션 문자열이 유출되었다면 텔레그램의 설정 → 기기에서 해당 세션을 즉시 종료합니다.

## 필요한 GitHub Secrets

- `TELEGRAM_API_ID`
- `TELEGRAM_API_HASH`
- `TELEGRAM_SESSION`
- `BOT_TOKEN`
- `ALERT_CHAT_ID`
- `CONFIG_JSON`

`CONFIG_JSON` 형식은 `config.example.json`을 참고하세요. `channels`에는 `@채널사용자명` 또는 텔레그램에서 식별 가능한 채널명을 넣습니다. 비공개 채널은 인증한 사용자 계정이 이미 가입한 채널이어야 합니다.

## 동작 특성

- 첫 실행에서는 현재 최신 글을 기준점으로 저장하며 과거 글을 알리지 않습니다.
- 이후 실행부터 새 글만 검사합니다.
- GitHub Actions 캐시에 채널별 마지막 메시지 ID만 저장하여 중복을 막습니다.
- 캐시가 유실되면 새 기준점을 만들고 초기화 알림을 보냅니다.
- GitHub 예약 실행은 정확한 실시간을 보장하지 않으며 지연될 수 있습니다.

## 로컬 테스트

```sh
python -m unittest discover -s tests -v
python -m compileall -q .
```
