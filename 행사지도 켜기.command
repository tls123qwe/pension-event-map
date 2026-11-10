#!/bin/bash
# 더블클릭하면 행사지도 서버를 켜고 브라우저를 엽니다.
# 끄려면 이 터미널 창을 닫거나 Ctrl+C 를 누르세요.

cd "$(dirname "$0")" || exit 1
PORT=8080
URL="http://localhost:$PORT"

# GitHub에서 매주 자동 업데이트된 행사 데이터를 받아옴(실패해도 그냥 진행)
if [ -d .git ]; then
  git pull --ff-only -q 2>/dev/null && echo "최신 행사 데이터를 받았습니다." || echo "행사 데이터를 받지 못했습니다(인터넷 연결 확인). 기존 데이터로 엽니다."
fi

# 이미 켜져 있으면 브라우저만 열고 끝냄
if curl -s -o /dev/null --max-time 1 "$URL/api/memos"; then
  echo "행사지도가 이미 켜져 있습니다. 브라우저를 엽니다."
  open "$URL"
  sleep 1
  exit 0
fi

# 서버가 준비되면 브라우저 열기
(
  for _ in $(seq 1 40); do
    if curl -s -o /dev/null --max-time 1 "$URL/"; then
      open "$URL"
      break
    fi
    sleep 0.5
  done
) &

python3 serve.py "$PORT"
