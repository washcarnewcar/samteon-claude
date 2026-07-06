# 한글 폭(2칸) 보정 텍스트 다이어그램 조립 헬퍼.
# 절대 규칙: 박스·연결선 배치는 반드시 이 헬퍼(box / cat / at)로만 한다.
import unicodedata


def dw(s: str) -> int:
    """display width — 한글·전각(W/F) 2칸, 나머지 1칸.
    박스 문자(─│┌┐└┘ 등)는 Ambiguous 라 1칸으로 계산한다."""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def pad(s: str, n: int) -> str:
    """표시 폭 기준 우측 공백 패딩."""
    return s + " " * max(0, n - dw(s))


def box(lines, w=None):
    """엔티티/노드 박스. lines[0]이 제목 줄 역할.
    반환: 줄 list (폭 균일). w 로 최소 폭 강제 가능(가로 배너 박스 등)."""
    width = w or (max(dw(s) for s in lines) + 2)
    out = ["┌" + "─" * width + "┐"]
    out += ["│ " + pad(s, width - 2) + " │" for s in lines]
    out += ["└" + "─" * width + "┘"]
    return out


def cat(*cols):
    """여러 컬럼(줄 list)을 가로로 합친다. 박스 사이 connector 컬럼은
    ["", "  라벨", " ◀──────", "  카디널리티"] 식의 줄 list 로 끼워 넣는다."""
    h = max(len(c) for c in cols)
    widths = [max(dw(l) for l in c) for c in cols]
    out = []
    for i in range(h):
        row = ""
        for c, wd in zip(cols, widths):
            cell = c[i] if i < len(c) else ""
            row += pad(cell, wd)
        out.append(row.rstrip())
    return out


def at(*pairs):
    """(표시컬럼, 텍스트) 들을 절대 컬럼에 배치한 한 줄 생성.
    박스 사이 세로 연결(▲ │)이나 자유 배치 라벨에 사용."""
    line = ""
    for col, txt in sorted(pairs):
        line += " " * max(0, col - dw(line)) + txt
    return line
