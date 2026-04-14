#!/usr/bin/env bash
# TableUp 설치 스크립트 — Claude Code skills 디렉터리에 심링크를 만든다.
#
# 설치 위치 결정 순서:
#   1. --target <dir>  (명시적 지정)
#   2. $CLAUDE_CONFIG_DIR/skills/tableup  (claude-work, claude-personal 등 alias 사용자)
#   3. $HOME/.claude/skills/tableup  (기본값)
set -euo pipefail

SKILL_NAME="tableup"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---- OS 감지 ----
UNAME_S="$(uname -s 2>/dev/null || echo unknown)"
case "$UNAME_S" in
    MINGW*|MSYS*|CYGWIN*)
        echo "❌ Windows 네이티브 쉘(Git Bash/MSYS/Cygwin)은 심링크 생성이 제한됩니다."
        echo "   WSL2 환경에서 재실행하거나, 수동으로 디렉터리를 복사하세요:"
        echo "   cp -r \"${SRC_DIR}\" \"%USERPROFILE%\\.claude\\skills\\${SKILL_NAME}\""
        exit 1
        ;;
esac

# ---- 설치 대상 디렉터리 결정 ----
TARGET_DIR=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --target)
            TARGET_DIR="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [--target <dir>]"
            echo "  기본 대상: \${CLAUDE_CONFIG_DIR:-\$HOME/.claude}/skills/${SKILL_NAME}"
            exit 0
            ;;
        *)
            echo "알 수 없는 옵션: $1" >&2
            exit 1
            ;;
    esac
done

if [[ -z "$TARGET_DIR" ]]; then
    CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-${HOME}/.claude}"
    TARGET_DIR="${CLAUDE_DIR}/skills/${SKILL_NAME}"
fi

echo "📦 TableUp 설치 중..."
echo "   소스: ${SRC_DIR}"
echo "   대상: ${TARGET_DIR}"
if [[ -n "${CLAUDE_CONFIG_DIR:-}" ]]; then
    echo "   ℹ️  CLAUDE_CONFIG_DIR=${CLAUDE_CONFIG_DIR} 감지됨"
fi

# ---- Python 버전 체크 (경고만) ----
if command -v python3 >/dev/null 2>&1; then
    PY_VERSION="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "?")"
    PY_OK="$(python3 -c 'import sys; print("ok" if sys.version_info >= (3, 10) else "no")' 2>/dev/null || echo "no")"
    if [[ "$PY_OK" != "ok" ]]; then
        echo "⚠️  Python 3.10 이상 필요 (현재: ${PY_VERSION}). 실행 시 SyntaxError 가 날 수 있습니다."
    fi
else
    echo "⚠️  python3 를 찾지 못했습니다. 설치 후 requirements.txt 를 설치하세요."
fi

# ---- 대상 디렉터리 준비 ----
TARGET_PARENT="$(dirname "${TARGET_DIR}")"
if ! mkdir -p "${TARGET_PARENT}"; then
    echo "❌ ${TARGET_PARENT} 생성 실패. 권한을 확인하세요." >&2
    exit 1
fi

# 기존 경로가 일반 디렉터리/파일이면 덮어쓰지 않고 중단
if [[ -e "${TARGET_DIR}" ]] && [[ ! -L "${TARGET_DIR}" ]]; then
    echo "❌ ${TARGET_DIR} 가 이미 존재하며 심링크가 아닙니다." >&2
    echo "   수동으로 제거(또는 이동)한 뒤 재시도하세요." >&2
    exit 1
fi

# ln -snf : -s 심링크, -f 기존 심링크 덮어쓰기, -n 대상이 디렉터리 심링크일 때 역참조 방지
# (기존 rm + ln 두 단계 대신 한 번에 처리해 race/중간 상태를 없앤다)
if ! ln -snf "${SRC_DIR}" "${TARGET_DIR}"; then
    echo "❌ 심링크 생성 실패: ${TARGET_DIR}" >&2
    exit 1
fi
echo "✅ 심링크 생성 완료"

echo ""
echo "🔧 의존성 설치:"
echo "   pip install -r ${SRC_DIR}/requirements.txt"
echo ""
echo "🔑 API 키 설정 (아직 안 했다면):"
echo "   export UPSTAGE_API_KEY=\"up_...\"   # https://console.upstage.ai 에서 발급"
echo "   또는 ${SRC_DIR}/.env 파일에 UPSTAGE_API_KEY=... 로 저장"
echo ""
echo "🚀 Claude Code 재시작 후 /tableup 으로 호출 가능합니다."
