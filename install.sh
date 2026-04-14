#!/usr/bin/env bash
# TableUp 설치 스크립트 — ~/.claude/skills/tableup 으로 심링크한다.
set -euo pipefail

SKILL_NAME="tableup"
TARGET_DIR="${HOME}/.claude/skills/${SKILL_NAME}"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "📦 TableUp 설치 중..."
echo "   소스: ${SRC_DIR}"
echo "   대상: ${TARGET_DIR}"

mkdir -p "$(dirname "${TARGET_DIR}")"

if [[ -e "${TARGET_DIR}" ]] && [[ ! -L "${TARGET_DIR}" ]]; then
    echo "❌ ${TARGET_DIR} 가 이미 존재합니다. 수동으로 제거 후 재시도하세요."
    exit 1
fi

if [[ -L "${TARGET_DIR}" ]]; then
    rm "${TARGET_DIR}"
fi

ln -s "${SRC_DIR}" "${TARGET_DIR}"
echo "✅ 심링크 생성 완료"

echo ""
echo "🔧 의존성 설치:"
echo "   pip install -r ${SRC_DIR}/requirements.txt"
echo ""
echo "🔑 API 키 설정 (아직 안 했다면):"
echo "   export UPSTAGE_API_KEY=\"up_...\"   # https://console.upstage.ai 에서 발급"
echo ""
echo "🚀 Claude Code 재시작 후 /tableup 으로 호출 가능합니다."
