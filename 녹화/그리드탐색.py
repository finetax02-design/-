"""페이지 안의 RealGrid 객체를 찾아 다룰 수 있는지 확인한다.

위하고 전표 목록은 RealGrid 로 그려진다. RealGrid 는 canvas 에 직접
그리므로 HTML 을 뒤져도 행이 나오지 않는다. 대신 자바스크립트 API 가 있어서
그 객체만 잡으면 데이터를 읽고 쓸 수 있다.

이 스크립트는 그 객체를 어디서 찾을 수 있는지, 컬럼과 행이 몇 개인지,
값을 읽어올 수 있는지까지 확인한다.

거래처명과 금액은 마스킹한다.
"""
import json
import traceback
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
OUT = HERE / "그리드탐색.txt"
CDP = "http://localhost:9222"
lines: list[str] = []


def say(text: str = "") -> None:
    print(text[:400])
    lines.append(text)


PROBE = r"""() => {
  const out = { globals: [], namespace: {}, elementKeys: {}, grids: [] };
  const mask = v => {
    if (v === null || v === undefined) return null;
    const s = String(v);
    return s.replace(/\d/g, '#').slice(0, 10);
  };

  // 1) RealGrid 전역 이름이 있는지
  for (const n of ['RealGrid', 'RealGridJS', 'realgrid', 'RealGrid2']) {
    try { out.namespace[n] = typeof window[n]; } catch (e) { out.namespace[n] = 'err'; }
  }

  // 2) window 안에서 그리드처럼 생긴 객체 찾기
  const gridish = o => o && typeof o === 'object' &&
    (typeof o.getDataSource === 'function' || typeof o.setDataSource === 'function' ||
     typeof o.getItemCount === 'function' || typeof o.getColumns === 'function' ||
     typeof o.getJsonRows === 'function' || typeof o.getRowCount === 'function');

  let keys = [];
  try { keys = Object.keys(window); } catch (e) {}
  for (const k of keys) {
    let v;
    try { v = window[k]; } catch (e) { continue; }
    if (gridish(v)) {
      out.globals.push({ where: 'window.' + k,
        methods: ['getDataSource','getItemCount','getColumns','getJsonRows','getRowCount','setValue','getValues']
          .filter(m => typeof v[m] === 'function') });
    }
  }

  // 3) 그리드 컨테이너 요소에 붙어 있는 내부 참조 (Vue / React 등)
  for (const id of ['GRID_TOP', 'GRID_DOWN']) {
    const el = document.getElementById(id);
    if (!el) { out.elementKeys[id] = '요소 없음'; continue; }
    out.elementKeys[id] = Object.keys(el).filter(k => k.startsWith('_') || k.startsWith('$')).slice(0, 20);
  }

  // 4) 찾은 그리드에서 실제로 컬럼과 값을 꺼내본다
  const probe = (label, g) => {
    const info = { label, ok: false };
    try {
      let cols = [];
      if (typeof g.getColumns === 'function') {
        cols = g.getColumns().map(c => ({ name: c.name || c.fieldName || '',
                                          header: (c.header && (c.header.text || c.header)) || '' }));
      }
      info.columns = cols.slice(0, 30);

      let dp = null;
      try { dp = typeof g.getDataSource === 'function' ? g.getDataSource() : null; } catch (e) {}
      const src = dp || g;
      if (typeof src.getRowCount === 'function') info.rowCount = src.getRowCount();
      else if (typeof src.getItemCount === 'function') info.rowCount = src.getItemCount();

      if (typeof src.getValues === 'function' && info.rowCount > 0) {
        info.sampleRow = src.getValues(0).map(mask);
      } else if (typeof src.getJsonRows === 'function') {
        const rows = src.getJsonRows(0, 0);
        if (rows && rows[0]) {
          info.sampleRow = {};
          for (const k of Object.keys(rows[0])) info.sampleRow[k] = mask(rows[0][k]);
        }
      }
      info.writable = typeof src.setValue === 'function' || typeof g.setValue === 'function';
      info.ok = true;
    } catch (e) {
      info.error = String(e).slice(0, 200);
    }
    return info;
  };

  for (const g of out.globals) {
    try { out.grids.push(probe(g.where, window[g.where.replace('window.', '')])); } catch (e) {}
  }
  return out;
}"""


print()
print("=" * 62)
print("  RealGrid 객체 탐색")
print("=" * 62)
print()
print("  크롬열기.bat 으로 띄운 크롬에서")
print("  전자세금계산서 화면에 자료가 보이는 상태여야 합니다.")
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
            say(f"대상 탭: {target.url[:120]}\n")
            data = target.evaluate(PROBE)

            say("=" * 60)
            say("[RealGrid 전역 이름]")
            say(json.dumps(data["namespace"], ensure_ascii=False))

            say("\n[window 안의 그리드 같은 객체]")
            if data["globals"]:
                for g in data["globals"]:
                    say(f"  {g['where']}  메서드: {g['methods']}")
            else:
                say("  없음 — 전역에 노출되지 않았습니다.")

            say("\n[그리드 요소에 붙은 내부 참조]")
            for k, v in data["elementKeys"].items():
                say(f"  {k}: {v}")

            say("\n[꺼내본 결과]")
            for g in data["grids"]:
                say(f"\n  --- {g['label']} ---")
                say(f"  성공 여부: {g['ok']}  행수: {g.get('rowCount')}  쓰기가능: {g.get('writable')}")
                if g.get("error"):
                    say(f"  오류: {g['error']}")
                for c in (g.get("columns") or []):
                    say(f"    컬럼: name={c['name']}  header={c['header']}")
                if g.get("sampleRow") is not None:
                    say(f"    샘플행(마스킹): {json.dumps(g['sampleRow'], ensure_ascii=False)[:600]}")

        browser.close()
except Exception:
    say("\n실패했습니다. 원인:")
    say(traceback.format_exc())

OUT.write_text("\n".join(lines), encoding="utf-8")
print()
print("=" * 62)
print(f"  저장됨: {OUT}")
print("=" * 62)
print()
input("  창을 닫으려면 Enter >>> ")
