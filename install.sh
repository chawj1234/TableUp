#!/usr/bin/env bash
# UpParse 설치 스크립트 — Claude Code skills 디렉터리에 심링크를 만든다.
#
# 설치 위치 결정 순서:
#   1. --target <dir>  (명시적 지정) → 그 디렉터리에만 설치
#   2. 그 외 → 발견된 모든 프로필에 자동 설치:
#        - $HOME/.claude
#        - $HOME/.claude-*  (claude-work, claude-personal 등)
#        - $CLAUDE_CONFIG_DIR  (위에 안 잡힌 추가 경로)
set -euo pipefail

SKILL_NAME="upparse"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="${REPO_DIR}/skills/upparse"

if [[ ! -f "${SRC_DIR}/SKILL.md" ]]; then
    echo "❌ 스킬 디렉터리를 찾지 못했습니다: ${SRC_DIR}" >&2
    exit 1
fi

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

# ---- 인자 파싱 ----
EXPLICIT_TARGET=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --target)
            EXPLICIT_TARGET="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [--target <dir>]"
            echo "  --target 미지정 시: \$HOME/.claude, \$HOME/.claude-*, \$CLAUDE_CONFIG_DIR 모두 자동 설치"
            exit 0
            ;;
        *)
            echo "알 수 없는 옵션: $1" >&2
            exit 1
            ;;
    esac
done

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

# ---- 설치 대상 프로필 디렉터리 수집 ----
PROFILES=()

if [[ -n "$EXPLICIT_TARGET" ]]; then
    # --target 명시: 그 디렉터리(skills/<skill> 까지의 전체 경로)에만
    PROFILES+=("$EXPLICIT_TARGET")
else
    # ~/.claude 와 ~/.claude-* 디렉터리 자동 발견
    [[ -d "$HOME/.claude" ]] && PROFILES+=("$HOME/.claude/skills/${SKILL_NAME}")
    # nullglob 으로 매칭 없을 때 패턴 자체가 남는 걸 방지
    shopt -s nullglob
    for d in "$HOME"/.claude-*; do
        [[ -d "$d" ]] && PROFILES+=("$d/skills/${SKILL_NAME}")
    done
    shopt -u nullglob

    # CLAUDE_CONFIG_DIR 가 위 목록에 안 잡힌 추가 경로면 합치기
    if [[ -n "${CLAUDE_CONFIG_DIR:-}" ]]; then
        EXTRA="${CLAUDE_CONFIG_DIR}/skills/${SKILL_NAME}"
        ALREADY=0
        for p in "${PROFILES[@]:-}"; do
            [[ "$p" == "$EXTRA" ]] && ALREADY=1 && break
        done
        [[ $ALREADY -eq 0 ]] && PROFILES+=("$EXTRA")
    fi

    # 아무 것도 못 찾았으면 기본값(~/.claude)으로 설치
    if [[ ${#PROFILES[@]} -eq 0 ]]; then
        PROFILES+=("$HOME/.claude/skills/${SKILL_NAME}")
    fi
fi

echo "📦 UpParse 설치 중..."
echo "   소스: ${SRC_DIR}"
echo "   대상 프로필: ${#PROFILES[@]}개"

# ---- 각 프로필에 심링크 생성 ----
SUCCESS=0
FAIL=0
for TARGET_DIR in "${PROFILES[@]}"; do
    TARGET_PARENT="$(dirname "${TARGET_DIR}")"

    if ! mkdir -p "${TARGET_PARENT}" 2>/dev/null; then
        echo "   ❌ ${TARGET_DIR}  (부모 디렉터리 생성 실패)" >&2
        FAIL=$((FAIL + 1))
        continue
    fi

    # 기존 경로가 일반 디렉터리/파일이면 건너뜀
    if [[ -e "${TARGET_DIR}" ]] && [[ ! -L "${TARGET_DIR}" ]]; then
        echo "   ⚠️  ${TARGET_DIR}  (심링크 아닌 디렉터리/파일 존재 — 건너뜀)" >&2
        FAIL=$((FAIL + 1))
        continue
    fi

    # ln -snf : -s 심링크, -f 기존 심링크 덮어쓰기, -n 디렉터리 심링크 역참조 방지
    if ln -snf "${SRC_DIR}" "${TARGET_DIR}" 2>/dev/null; then
        echo "   ✅ ${TARGET_DIR}"
        SUCCESS=$((SUCCESS + 1))
    else
        echo "   ❌ ${TARGET_DIR}  (심링크 생성 실패)" >&2
        FAIL=$((FAIL + 1))
    fi
done

echo ""
if [[ $FAIL -gt 0 ]]; then
    echo "결과: ${SUCCESS}개 성공, ${FAIL}개 실패"
else
    echo "결과: ${SUCCESS}개 프로필에 설치 완료"
fi

echo ""
echo "🔧 의존성 설치:"
echo "   pip install -r ${REPO_DIR}/requirements.txt"
echo ""
echo "🔑 API 키 설정 (아직 안 했다면):"
echo "   ${REPO_DIR}/.env 파일에 UPSTAGE_API_KEY=... 로 저장"
echo ""
echo "🚀 Claude Code 재시작 후 /upparse 로 호출 가능합니다."

[[ $SUCCESS -gt 0 ]] || exit 1
