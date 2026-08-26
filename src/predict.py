"""과거 분개 이력으로 2단 룰을 학습해 계정과목/공제구분을 예측한다.

L1  사업자등록번호 -> 계정과목      (그 거래처와 거래한 적이 있으면 이걸로 끝)
L2  품명 정규화 키워드 -> 계정과목  (신규 거래처인데 품명이 익숙한 경우)
L3  둘 다 못 맞추면 미해결 -> 사람 또는 LLM 이 판단

왜 L2 가 필요한가:
    제조업 고객사는 일회성 화물운송 사업자가 거래처의 절반을 차지한다.
    거래처는 매번 다르지만 품명은 늘 '운송료 (오더번호: ...)' 라서,
    품명만 정규화하면 거래처 이력 없이도 계정과목이 결정된다.

사용법:
    python predict.py --data dataset.csv              # leave-one-out 으로 커버리지 실측
    python predict.py --train 과거.csv --apply 신규.csv  # 과거로 배우고 신규에 적용
"""
from __future__ import annotations

import argparse
import collections
import csv
import re
from pathlib import Path

# 품명에서 건별로만 달라지는 부분(오더번호, 날짜, 수량, 규격)을 지운다.
# '운송료 (오더번호: 408969852)' 와 '운송료 (오더번호: 413938815)' 를 같은 키로 만들기 위함.
NOISE = [
    re.compile(r"\(오더번호[^)]*\)"),
    re.compile(r"\(\d[^)]*\)"),
    re.compile(r"\[[^\]]*\]"),
    re.compile(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}"),
    re.compile(r"외\s*\d+\s*건"),
    re.compile(r"\d+"),
]


def norm_item(name: str) -> str:
    """품명을 정규화해 룰 키로 쓸 수 있게 만든다."""
    s = str(name or "")
    for pat in NOISE:
        s = pat.sub(" ", s)
    return re.sub(r"[\s\-_/,]+", " ", s).strip().lower()


class Model:
    """사업자번호 룰(L1)과 품명 룰(L2)을 담는다."""

    def __init__(self, target: str) -> None:
        self.target = target
        self.by_biz: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
        self.by_item: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)

    def fit(self, rows: list[dict], skip: int | None = None) -> "Model":
        for i, r in enumerate(rows):
            if i == skip:
                continue
            self.by_biz[r["사업자번호"]][r[self.target]] += 1
            key = norm_item(r["품목명"])
            if key:
                self.by_item[key][r[self.target]] += 1
        return self

    def predict(self, row: dict) -> tuple[str | None, str, float]:
        """(예측값, 사용한 계층, 확신도) 를 돌려준다. 못 맞추면 (None, 'L3', 0.0)."""
        hist = self.by_biz.get(row["사업자번호"])
        if hist:
            value, n = hist.most_common(1)[0]
            return value, "L1", n / sum(hist.values())
        hist = self.by_item.get(norm_item(row["품목명"]))
        if hist:
            value, n = hist.most_common(1)[0]
            return value, "L2", n / sum(hist.values())
        return None, "L3", 0.0


def evaluate(rows: list[dict], target: str) -> None:
    """각 건을 하나씩 빼고 나머지로 학습해 예측한다 (leave-one-out)."""
    stats = collections.Counter()
    wrong = []
    for i, row in enumerate(rows):
        pred, layer, conf = Model(target).fit(rows, skip=i).predict(row)
        if pred is None:
            stats["L3_미해결"] += 1
        elif pred == row[target]:
            stats[f"{layer}_적중"] += 1
        else:
            stats[f"{layer}_오답"] += 1
            wrong.append((row, pred, layer))

    total = sum(stats.values())
    print(f"\n[{target}]  n={total}")
    resolved = 0
    for layer in ("L1", "L2"):
        hit, miss = stats[f"{layer}_적중"], stats[f"{layer}_오답"]
        if hit + miss == 0:
            continue
        resolved += hit + miss
        name = "사업자번호 룰" if layer == "L1" else "품명 룰"
        print(f"    {layer} {name:<10} {hit + miss:5d}건 ({(hit + miss) / total * 100:5.1f}%)  "
              f"적중 {hit:5d}  오답 {miss:3d}  정확도 {hit / (hit + miss) * 100:5.1f}%")
    unresolved = stats["L3_미해결"]
    print(f"    L3 사람/LLM 판단  {unresolved:5d}건 ({unresolved / total * 100:5.1f}%)")
    total_hit = stats["L1_적중"] + stats["L2_적중"]
    total_miss = stats["L1_오답"] + stats["L2_오답"]
    print(f"    ── 자동 처리 {resolved}건 중 정확도 {total_hit / resolved * 100:.2f}% (오답 {total_miss}건)")
    for row, pred, layer in wrong[:12]:
        print(f"      [{layer}] {row['공급자상호'][:16]:<18} {row['품목명'][:28]:<30} "
              f"예측={pred} 실제={row[target]}")


def apply(train: list[dict], target_rows: list[dict], target: str, out: Path) -> None:
    """과거 데이터로 학습해 새 데이터에 예측을 붙이고, 검토 대상을 표시한다."""
    model = Model(target).fit(train)
    written = 0
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["작성일자", "공급자상호", "품목명", "공급가액",
                         f"예측_{target}", "계층", "확신도", f"위하고_{target}", "검토필요"])
        for row in target_rows:
            pred, layer, conf = model.predict(row)
            actual = row.get(target, "")
            # 룰이 못 맞춘 건, 또는 룰과 위하고 값이 어긋난 건만 사람이 본다.
            review = "확인" if pred is None or (actual and pred != actual) else ""
            writer.writerow([row["작성일자"], row["공급자상호"], row["품목명"], row["공급가액"],
                             pred or "", layer, f"{conf:.2f}", actual, review])
            written += 1
    print(f"\n예측 결과 저장: {out} ({written}건)")


def read(path: Path) -> list[dict]:
    return list(csv.DictReader(path.open(encoding="utf-8-sig")))


def main() -> None:
    ap = argparse.ArgumentParser(description="2단 룰 기반 계정과목/공제구분 예측")
    ap.add_argument("--data", type=Path, help="leave-one-out 으로 커버리지만 실측")
    ap.add_argument("--train", type=Path, help="학습용 과거 데이터")
    ap.add_argument("--apply", type=Path, help="예측을 붙일 신규 데이터")
    ap.add_argument("--out", type=Path, default=Path("예측결과.csv"))
    ap.add_argument("--targets", nargs="+", default=["계정과목", "공제구분"])
    args = ap.parse_args()

    if args.data:
        rows = [r for r in read(args.data) if r["계정과목"] not in ("미추천", "")]
        print("=" * 74)
        print(f"{args.data.name}  분개완료 {len(rows)}건")
        print("=" * 74)
        for t in args.targets:
            evaluate(rows, t)
    elif args.train and args.apply:
        train = [r for r in read(args.train) if r["계정과목"] not in ("미추천", "")]
        apply(train, read(args.apply), args.targets[0], args.out)
    else:
        ap.error("--data 또는 (--train 과 --apply) 중 하나가 필요합니다")


if __name__ == "__main__":
    main()
