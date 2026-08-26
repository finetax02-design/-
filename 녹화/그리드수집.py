"""전표 목록 그리드의 DOM 구조만 집중해서 읽는다.

앞선 수집에서 입력칸과 버튼은 잡혔지만 정작 전표 목록이 안 나왔다.
위하고는 일반 <table> 이 아니라 직접 만든 그리드 부품을 쓰기 때문이다.
그 부품의 행과 칸이 어떤 태그와 class 로 되어 있는지 알아야
행을 읽고 계정과목을 채워 넣을 수 있다.

거래처명과 금액은 마스킹한다. 숫자는 #, 글자는 앞 2자만 남긴다.
"""
import traceback
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
OUT = HERE / "그리드구조.txt"
CDP = "http://localhost:9222"
lines: list[str] = []


def say(text: str = "") -> None:
    print(text[:300])
    lines.append(text)


# 그리드 후보를 찾고, 그 안의 행과 칸 구조를 마스킹해서 뽑는다.
SCRIPT = r"""() => {
  const mask = s => (s || '').trim().replace(/\d/g, '#').slice(0, 6);

  const desc = el => {
    const a = {};
    for (const at of el.attributes) {
      if (at.name === 'style') continue;
      a[at.name] = at.value.slice(0, 60);
    }
    return { tag: el.tagName.toLowerCase(), attrs: a };
  };

  // 1) 그리드로 보이는 컨테이너 찾기
  const candidates = [...document.querySelectorAll('div,section')].filter(el => {
    const c = (el.className || '').toString();
    return /grid|Grid|GRID|sheet|Sheet|LSGrid|table_body|list_body/.test(c)
           && el.offsetParent !== null && el.clientHeight > 80;
  }).slice(0, 12);

  const grids = candidates.map(g => {
    // 자식 중 같은 class 가 여러 번 반복되면 그게 '행' 이다
    const tally = {};
    for (const ch of g.children) {
      const k = ch.tagName.toLowerCase() + '.' + (ch.className || '').toString().slice(0, 40);
      tally[k] = (tally[k] || 0) + 1;
    }
    const repeated = Object.entries(tally).filter(([, n]) => n >= 3)
                           .sort((x, y) => y[1] - x[1]);

    let sample = null;
    if (repeated.length) {
      const key = repeated[0][0];
      const row = [...g.children].find(ch =>
        ch.tagName.toLowerCase() + '.' + (ch.className || '').toString().slice(0, 40) === key);
      if (row) {
        sample = {
          row: desc(row),
          cells: [...row.children].slice(0, 20).map(c => ({
            ...desc(c), text: mask(c.innerText),
          })),
        };
      }
    }
    return {
      grid: desc(g),
      childCount: g.children.length,
      repeated: repeated.slice(0, 4),
      sample,
    };
  });

  // 2) GRID_TOP_line 주변 구조 (그리드 위치를 알려주는 표지)
  const marker = document.getElementById('GRID_TOP_line');
  let around = null;
  if (marker) {
    const chain = [];
    let el = marker;
    for (let i = 0; i < 8 && el; i++) { chain.push(desc(el)); el = el.parentElement; }
    around = chain;
  }

  // 3) 화면 전체에서 '차변계정' 같은 글자가 들어간 요소의 위치
  const heads = [...document.querySelectorAll('div,span,th,td')]
    .filter(el => el.children.length === 0 &&
                  /차변계정|대변계정|전표상태|공급가액|품명|거래처/.test(el.innerText || ''))
    .slice(0, 30)
    .map(el => ({ text: (el.innerText || '').trim().slice(0, 12), ...desc(el),
                  parent: el.parentElement ? desc(el.parentElement) : null }));

  return { grids, around, heads };
}"""


def report(data: dict) -> None:
    say("\n" + "=" * 60)
    say(f"[그리드 후보 {len(data['grids'])}개]")
    for i, g in enumerate(data["grids"]):
        say(f"\n  --- 후보 {i + 1} ---")
        say(f"  컨테이너: {g['grid']}")
        say(f"  자식 수: {g['childCount']}")
        say(f"  반복되는 자식: {g['repeated']}")
        if g["sample"]:
            say(f"  행: {g['sample']['row']}")
            for j, c in enumerate(g["sample"]["cells"]):
                say(f"    칸{j + 1}: {c}")

    say("\n" + "=" * 60)
    say("[GRID_TOP_line 위쪽 계보]")
    for level in (data.get("around") or []):
        say(f"  {level}")

    say("\n" + "=" * 60)
    say("[제목 글자가 들어있는 요소]")
    for h in data.get("heads") or []:
        say(f"  \"{h['text']}\"  {h['tag']} {h['attrs']}")
        say(f"      부모: {h['parent']}")


print()
print("=" * 62)
print("  전표 목록 그리드 구조 수집")
print("=" * 62)
print()
print("  크롬열기.bat 으로 띄운 크롬에서")
print("  전자세금계산서 화면에 자료가 보이는 상태여야 합니다.")
print("  미추천 건이 한 건이라도 보이면 더 좋습니다.")
print()
input("  준비되었으면 Enter >>> ")

try:
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        pages = [pg for ctx in browser.contexts for pg in ctx.pages]
        target = next((pg for pg in pages if "smarta.wehago.com" in pg.url), None)
        if target is None:
            say("smarta.wehago.com 탭을 찾지 못했습니다.")
            say("열린 탭: " + ", ".join(pg.url[:80] for pg in pages))
        else:
            say(f"대상 탭: {target.url[:120]}")
            report(target.evaluate(SCRIPT))

            print()
            input("  전표 한 줄을 클릭하시고 Enter (건너뛰려면 그냥 Enter) >>> ")
            say("\n\n########## 행 클릭 후 ##########")
            report(target.evaluate(SCRIPT))

        browser.close()
except Exception:
    say("\n실패했습니다. 원인:")
    say(traceback.format_exc())

OUT.write_text("\n".join(lines), encoding="utf-8")
print()
print("=" * 62)
print(f"  저장됨: {OUT}")
print("  거래처명과 금액은 마스킹되어 있습니다.")
print("=" * 62)
print()
input("  창을 닫으려면 Enter >>> ")
