"""위하고가 칸 편집을 처리하는 함수의 원본 코드를 읽어온다.

한 건 쓰기 시험 결과, 차변계정 값은 들어갔지만 전표상태가 미추천 그대로였다.
손으로 입력하면 위하고 코드가 편집 완료 신호를 받아 전표상태를 바꾸고
하단 분개까지 만들어 주는데, 데이터만 바꾸면 그 신호가 안 간다.

자바스크립트는 함수의 원본 코드를 꺼내 볼 수 있다.
편집 처리 함수들이 어떤 인자를 받고 전표상태를 어떻게 바꾸는지 읽으면
어떻게 불러야 하는지 알 수 있다.

여기서 얻는 것은 위하고의 코드일 뿐 거래 자료가 아니다.
"""
import json
import traceback
from pathlib import Path

from playwright.sync_api import sync_playwright

CDP = "http://localhost:9222"
HERE = Path(__file__).resolve().parent
OUT = HERE / "함수코드.txt"
TOP_MARK = "nm_acctit_cha"

# 편집 신호를 처리할 것으로 보이는 함수들
TARGETS = ["setValue", "setValues", "commit",
           "_onCellEdited", "_onEditCommit", "handleCellEdited", "handleEditCommit",
           "onCellEdited", "onEditCommit", "autoCompleteCommit",
           "handleRowDataChanged", "onRowDataChanged", "_onCurrentRowChanged",
           "validationCheck", "customValidationCheck"]

SCRIPT = r"""() => {
  const MARK = '%MARK%';
  const TARGETS = %TARGETS%;
  const L = [];
  const log = s => L.push(String(s));

  const gridish = o => {
    if (!o || (typeof o !== 'object' && typeof o !== 'function')) return false;
    try { return typeof o.getColumns === 'function' && typeof o.getValues === 'function'; }
    catch (e) { return false; }
  };

  // 전표 목록 그리드와 그 그리드를 감싼 위하고 쪽 객체를 찾는다
  const seen = new WeakSet();
  const queue = [{ o: window, path: 'window', d: 0 }];
  const SKIP = /^(document|location|navigator|parent|top|self|frames|history|localStorage|sessionStorage|indexedDB|caches|crypto)$/;
  let handler = null, hpath = '';
  let visited = 0;
  while (queue.length && visited < 60000 && !handler) {
    const { o, path, d } = queue.shift();
    if (d > 9) continue;
    let keys = [];
    try { keys = Object.keys(o); } catch (e) { continue; }
    for (const k of keys) {
      if (d === 0 && SKIP.test(k)) continue;
      let v;
      try { v = o[k]; } catch (e) { continue; }
      if (!v || (typeof v !== 'object' && typeof v !== 'function')) continue;
      try { if (v.nodeType || v === window) continue; } catch (e) { continue; }
      try { if (seen.has(v)) continue; seen.add(v); } catch (e) { continue; }
      visited++;
      if (gridish(v)) {
        let cn = [];
        try { cn = v.getColumns().map(c => String(c.name || c.fieldName || '')); } catch (e) {}
        if (cn.includes(MARK)) { handler = v; hpath = path + '.' + k; break; }
      }
      if (d < 9) queue.push({ o: v, path: path + '.' + k, d: d + 1 });
    }
  }
  if (!handler) return '전표 목록을 잡지 못했습니다.';
  log(`대상: ${hpath}`);

  // 함수 원본 코드를 꺼낸다
  const dump = (label, obj) => {
    if (!obj) return;
    log('');
    log('#'.repeat(58));
    log(`#  ${label}`);
    log('#'.repeat(58));
    for (const name of TARGETS) {
      let fn;
      try { fn = obj[name]; } catch (e) { continue; }
      if (typeof fn !== 'function') continue;
      let src = '';
      try { src = Function.prototype.toString.call(fn); } catch (e) { src = '(코드를 읽지 못함)'; }
      log('');
      log(`--- ${name} (${src.length}자) ---`);
      log(src.length > 6000 ? src.slice(0, 6000) + '\n...(잘림)' : src);
    }
  };

  dump('위하고 래퍼', handler);

  // 전표상태를 건드리는 함수가 또 있는지 이름으로 훑는다
  log('');
  log('#'.repeat(58));
  log('#  이름에 상태/추천/분개가 들어간 함수');
  log('#'.repeat(58));
  const names = [];
  let cur = handler;
  for (let i = 0; i < 4 && cur; i++) {
    for (const k of Object.getOwnPropertyNames(cur)) {
      try { if (typeof handler[k] === 'function' && !names.includes(k)) names.push(k); } catch (e) {}
    }
    cur = Object.getPrototypeOf(cur);
  }
  const hit = names.filter(n => /jungstat|status|recommend|추천|bungae|acctit|edit|commit/i.test(n));
  log(`  후보: ${hit.join(', ')}`);
  for (const n of hit) {
    if (TARGETS.includes(n)) continue;
    let src = '';
    try { src = Function.prototype.toString.call(handler[n]); } catch (e) { continue; }
    if (src.length > 2500) src = src.slice(0, 2500) + '\n...(잘림)';
    log('');
    log(`--- ${n} ---`);
    log(src);
  }

  return L.join('\n');
}""".replace("%MARK%", TOP_MARK).replace("%TARGETS%", json.dumps(TARGETS))

lines: list[str] = []

print()
print("=" * 62)
print("  위하고 편집 처리 함수 읽기")
print("=" * 62)
print()
print("  전표 목록에서 아무 줄이나 한 번 클릭한 뒤 실행하세요.")
print("  읽기만 합니다. 값을 바꾸지 않습니다.")
print()
input("  준비되었으면 Enter >>> ")

try:
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        pages = [pg for ctx in browser.contexts for pg in ctx.pages]
        target = next((pg for pg in pages if "smarta.wehago.com" in pg.url), None)
        if target is None:
            lines.append("smarta.wehago.com 탭을 찾지 못했습니다.")
        else:
            lines.append(target.evaluate(SCRIPT))
        browser.close()
except Exception:
    lines.append("\n실패했습니다. 원인:")
    lines.append(traceback.format_exc())

text = "\n".join(lines)
OUT.write_text(text, encoding="utf-8")
print(text[:2000])
print()
print("=" * 62)
print(f"  저장됨: {OUT}  ({len(text):,}자)")
print("  위하고의 코드일 뿐 거래 자료는 없습니다. 보내주세요.")
print("=" * 62)
print()
input("  창을 닫으려면 Enter >>> ")
