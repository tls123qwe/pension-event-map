#!/usr/bin/env python3
"""행사 데이터 주간 업데이트 (파이썬 표준 라이브러리만 사용)

실행:  python3 update.py            진행 중·예정 행사만 상세정보(공식 사이트 등) 확인
       python3 update.py --all      종료된 행사까지 상세정보 확인 (오래 걸림)
       python3 update.py --dry-run  결과만 보고 파일은 바꾸지 않음

하는 일
  1. 문화체육관광부 지역축제 목록(올해 1월 1일 ~ 내년 12월 31일)을 다시 읽음
  2. 새로 등록된 행사 추가, 일정이 바뀐 행사 갱신
  3. 진행 중·예정 행사 가운데 상세정보를 아직 안 받았거나 공식 사이트가 없던 행사를 다시 확인
     → 공식 사이트(관련 누리집), 실제 장소, 요금, 주최기관 저장
  4. 바뀐 내용을 화면에 보여주고 data/update-log.md 에 기록
  5. 원래 data/events.js 는 data/backup/ 에 보관

직접 추가한 행사(id가 x- 로 시작)는 건드리지 않고, 문체부에 같은 행사가 올라오면 '중복 후보'로 알려줌.
"""
import concurrent.futures
import datetime as dt
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
EVENTS_JS = os.path.join(DATA, "events.js")
SGG_JS = os.path.join(DATA, "sgg.js")
LOG_MD = os.path.join(DATA, "update-log.md")
BASE = "https://www.mcst.go.kr/kor/s_culture/festival/"
UA = "Mozilla/5.0 (pension-event-map weekly update)"


def now_kst():
    """GitHub Actions(UTC)에서 돌아도 한국 시간으로 기록"""
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).replace(tzinfo=None)

HEADER = (
    "/* 2026 전국 행사 데이터 (update.py 가 자동 생성·갱신)\n"
    " * src m: 문화체육관광부 지역축제 목록, src x: 직접 추가(st=conf 공식/ann 안내/est 전년 기준 예상)\n"
    " * 필드: id,n(이름),s/e(시작/종료),sd(시도),sg(시군구),lat/lng(시군구 중심, pin=0이면 시도 중심),c(분류),tel,tm(운영시간),ap(날짜 추정)\n"
    " *       w(공식 사이트),v(축제 장소),f(요금),h(주최·주관),dt(상세정보 확인일)\n"
    " */\n"
)

SIDO = {"서울시": "서울", "부산시": "부산", "대구시": "대구", "인천시": "인천", "대전시": "대전", "울산시": "울산", "세종시": "세종",
        "경기도": "경기", "강원도": "강원", "충청북도": "충북", "충청남도": "충남", "전라북도": "전북", "경상북도": "경북",
        "경상남도": "경남", "제주도": "제주"}
GWANGJU_GU = {"동구", "서구", "남구", "북구", "광산구"}
PROV_CENTER = {"서울": [37.56, 126.98], "인천": [37.47, 126.62], "경기": [37.42, 127.42], "강원": [37.75, 128.3], "충북": [36.82, 127.75],
               "충남": [36.52, 126.82], "대전": [36.33, 127.4], "세종": [36.6, 127.25], "전북": [35.73, 127.15], "전남": [34.85, 126.92],
               "광주": [35.16, 126.85], "경북": [36.4, 128.78], "대구": [35.84, 128.58], "경남": [35.3, 128.2], "울산": [35.55, 129.27],
               "부산": [35.17, 129.06], "제주": [33.38, 126.55]}
# 목록에 날짜가 시간만 적혀 있는 행사: 직접 확인한 날짜 (seq: (시작, 끝, 추정여부))
DATE_FIX = {"13424": ("2026-05-02", "2026-05-03", 0), "13326": ("2026-09-11", "2026-09-13", 0),
            "13205": ("2026-06-06", "2026-06-08", 0), "13161": ("2026-05-15", "2026-05-17", 0),
            "11906": ("2026-05-15", "2026-05-17", 0), "13141": ("2026-05-08", "2026-05-09", 0),
            "13469": ("2026-08-01", "2026-08-31", 1), "13483": ("2026-08-01", "2026-08-31", 1),
            "13457": ("2026-06-01", "2026-06-30", 1)}
CAT_RULES = [
    ("family", r"어린이|키즈|가족|반려|펫스타|펫|청소년|청년|과학|동물|공룡|메이커|게임|AI"),
    ("winter", r"동장군|꽁꽁|카운트다운|얼음|눈꽃|눈축제|빙어|산천어|송어|겨울|해맞이|해넘이|일출|썰매|스키|크리스마스|성탄"),
    ("light", r"낙화|나잇|빛|야행|불꽃|불빛|야간|달빛|별빛|별밤|연등|등축제|루미|라이트|나이트|밤"),
    ("flower", r"물축제|강축제|계곡|호수|바닷길|머드|워터|노을|반딧불|나비|보리밭|황새|생태|하천|발원지|꽃|벚|매화|유채|튤립|장미|국화|철쭉|진달래|연꽃|코스모스|단풍|억새|수국|라벤더|해바라기|산수유|동백|작약|목련|숲|정원|봄|가을"),
    ("food", r"순대|소라|고사리|고로쇠|만두|누들|유자|율무|오곡|고구마|대하|부추|명태|치즈|별미|삼계탕|대문어|광어|도미|밀축제|시식|수라간|생과방|은어|카페|포구|항구|나루|주막|장터|통맥|옥토버|쌀|사과|딸기|한우|고추|대게|전어|굴|김치|커피|막걸리|와인|맥주|빵|라면|수산|대추|인삼|홍삼|곶감|떡|젓갈|멸치|방어|꽃게|새우|장어|한과|토마토|수박|복숭아|포도|마늘|양파|버섯|녹차|음식|먹거리|미식|푸드|맛|한돈|돼지|닭|치킨|국수|냉면|김|미역|전복|오징어|고등어|한치|갈치|감자|옥수수|참외|블루베리|배축제|밤축제|산채|나물|장류|두부|술|주류|차문화|티|바다|해양|갯벌|조개|꼬막|낙지|주꾸미|도다리|멍게|송이|오미자|복분자|곰취|더덕|약초|한방|축산|농특산|특산"),
    ("heritage", r"대첩|이순신|장군|구석기|선사|가야|신라|백제|궁중|종묘|고분|군항제|모양성|춘향|논개|심청|한글|독서|무형|대제|성축제|국가유산|문화재|역사|전통|민속|단오|제례|제전|왕|성곽|읍성|향교|선비|유교|불교|사찰|한옥|도자|도예|공예|한지|탈춤|농악|아리랑|문화제|의병|독립|기념"),
    ("art", r"음악|뮤직|페스티벌|재즈|록|공연|영화|예술|아트|국악|춤|댄스|연극|합창|오페라|클래식|버스킹|힙합|K-|케이|만화|웹툰|책|문학|미디어"),
]


# ---------------------------------------------------------------- 네트워크
def fetch(path, params, tries=3):
    """macOS 기본 curl 사용 (python.org 파이썬은 인증서 설정이 없어 urllib 이 HTTPS 에서 실패할 수 있음)"""
    url = BASE + path + "?" + urllib.parse.urlencode(params)
    err = ""
    for i in range(tries):
        r = subprocess.run(["curl", "-sSL", "--max-time", "40", "-A", UA, url], capture_output=True)
        if r.returncode == 0 and r.stdout:
            return r.stdout.decode("utf-8", "ignore")
        err = r.stderr.decode("utf-8", "ignore").strip()
        time.sleep(2 + i * 3)
    raise RuntimeError(f"{url} 요청 실패: {err}")


def list_params(page, frm, to):
    return {"fromDt": frm, "toDt": to, "pOrder": "01up", "pCurrentPage": page}


# ---------------------------------------------------------------- 파싱
def parse_dates(per):
    p = per.split("|")[0]
    m = re.search(r"(20\d\d)\s*\.\s*(\d{1,2})\s*\.\s*(\d{1,2})", p)
    if not m:
        return None
    y, mo, d = map(int, m.groups())
    s = (y, mo, d)
    rest = p[m.end():]
    m2 = re.search(r"~\s*(?:(20\d\d)\s*\.\s*)?(\d{1,2})\s*\.\s*(\d{1,2})", rest)
    if m2:
        e = (int(m2.group(1)) if m2.group(1) else y, int(m2.group(2)), int(m2.group(3)))
    else:
        m3 = re.search(r"~\s*(\d{1,2})\s*\.", rest)
        e = (y, mo, int(m3.group(1))) if m3 else s
    if e < s:
        e = (e[0] + 1, e[1], e[2])
    return "%04d-%02d-%02d" % s, "%04d-%02d-%02d" % e


def parse_list_page(text):
    items = []
    for m in re.finditer(r'festivalView\.jsp\?pSeq=(\d+).*?class="sub-tit">(.*?)</p>.*?<strong>기간</strong>:(.*?)</li>'
                         r'.*?<strong>장소</strong>:(.*?)</li>.*?<strong>문의</strong>:(.*?)</li>', text, re.S):
        seq, name, per, place, tel = [html.unescape(re.sub(r"<[^>]+>", "", x)).strip() for x in m.groups()]
        items.append(dict(seq=seq, n=name, per=per, place=place, tel=tel))
    return items


def parse_detail(text):
    m = re.search(r'<dl class="board">(.*?)</dl>', text, re.S)
    if not m:
        return None
    out = {}
    for dt_, dd in re.findall(r"<dt>(.*?)</dt>\s*<dd[^>]*>(.*?)</dd>", m.group(1), re.S):
        key = re.sub(r"<[^>]+>", "", dt_).strip()
        if key == "관련 누리집":
            out[key] = [html.unescape(u).strip() for u in re.findall(r'href="([^"]+)"', dd)]
        else:
            out[key] = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", dd))).strip()
    return out


def category(name):
    for k, r in CAT_RULES:
        if re.search(r, name):
            return k
    return "etc"


def load_js_json(path, var):
    text = open(path, encoding="utf-8").read()
    m = re.search(r"window\." + var + r"=(.*?);\s*(?:\n|$)", text, re.S)
    return json.loads(m.group(1))


# ---------------------------------------------------------------- 변환
def to_event(item, centers):
    seq = item["seq"]
    fix = DATE_FIX.get(seq)
    d = (fix[0], fix[1]) if fix else parse_dates(item["per"])
    if not d:
        return None
    parts = item["place"].split()
    sd_raw, sg = parts[0], (parts[1] if len(parts) > 1 else "")
    if sd_raw == "전남광주":
        sd = "광주" if (sg in GWANGJU_GU or (not sg and "광주" in item["n"])) else "전남"
    else:
        sd = SIDO.get(sd_raw, "")
    if not sd:
        return None
    if sg == "세종특별자치시":
        sg = ""
    ll = centers.get(f"{sd}|{sg}") if sg else None
    pin = 1 if ll else 0
    if not ll:
        ll = PROV_CENTER[sd]
    tm = item["per"].split("|", 1)[1].strip() if "|" in item["per"] else ""
    return dict(id="m" + seq, n=item["n"], s=d[0], e=d[1], sd=sd, sg=sg, lat=ll[0], lng=ll[1], pin=pin,
                tel=item["tel"], tm=tm[:60], c=category(item["n"]), src="m", ap=1 if fix and fix[2] else 0)


def detail_fields(det):
    sites = [u for u in det.get("관련 누리집", []) if u.startswith("http")]
    return {"w": sites[0] if sites else "", "v": det.get("축제장소", ""), "f": det.get("요금", ""),
            "h": det.get("주최/주관기관", "")}


def norm(name):
    return re.sub(r"\s+|\(.*?\)|20\d\d|제\d+회", "", name)


# ---------------------------------------------------------------- 메인
def main():
    args = set(sys.argv[1:])
    dry, all_details = "--dry-run" in args, "--all" in args
    today = dt.date.today()
    frm, to = f"{today.year}.01.01.", f"{today.year + 1}.12.31."
    centers = load_js_json(SGG_JS, "SGG_CENTER")
    old = load_js_json(EVENTS_JS, "EVENTS")
    old_by_id = {e["id"]: e for e in old}

    print(f"1) 문체부 지역축제 목록 읽는 중 ({frm} ~ {to})")
    first = fetch("festivalList.jsp", list_params(1, frm, to))
    total = int(re.search(r'movePageInputTotalVal" value="(\d+)', first).group(1))
    items = parse_list_page(first)
    for p in range(2, total + 1):
        items += parse_list_page(fetch("festivalList.jsp", list_params(p, frm, to)))
        print(f"\r   {p}/{total} 페이지", end="", flush=True)
        time.sleep(0.2)
    print(f"\r   {total}페이지에서 {len(items)}건 읽음          ")

    # 이름+시작일+시도가 같은 중복 등록은 하나만
    scraped, seen, skipped = {}, set(), []
    for it in items:
        ev = to_event(it, centers)
        if not ev:
            skipped.append(f"{it['n']} ({it['per'][:30]})")
            continue
        key = (norm(ev["n"]), ev["s"], ev["sd"])
        if ev["id"] in scraped or key in seen:
            continue
        seen.add(key)
        scraped[ev["id"]] = ev

    report = {"신규": [], "일정 변경": [], "공식 사이트 추가": [], "공식 사이트 변경": [], "목록에서 빠짐": [],
              "중복 후보": [], "날짜를 못 읽음": skipped, "상세정보 실패": []}
    merged = {}
    for eid, ev in scraped.items():
        prev = old_by_id.get(eid)
        if prev:
            for k in ("w", "v", "f", "h", "dt"):
                if k in prev:
                    ev[k] = prev[k]
            if (prev["s"], prev["e"]) != (ev["s"], ev["e"]):
                report["일정 변경"].append(f"{ev['n']}: {prev['s']}~{prev['e']} → {ev['s']}~{ev['e']}")
        else:
            report["신규"].append(f"{ev['n']} ({ev['sd']} {ev['sg']}, {ev['s']}~{ev['e']})")
        merged[eid] = ev
    for eid, prev in old_by_id.items():
        if prev.get("src") == "m" and eid not in scraped:
            merged[eid] = prev  # 사라진 행사도 기록은 남김
            if prev["e"] >= today.isoformat():
                report["목록에서 빠짐"].append(f"{prev['n']} ({prev['s']}~{prev['e']}) - 취소됐는지 확인 필요")

    # 상세정보: 진행 중·예정 행사 중 아직 안 받았거나 공식 사이트가 없던 것
    targets = [ev for ev in merged.values() if ev.get("src") == "m" and ev["id"] in scraped
               and (all_details or ev["e"] >= today.isoformat()) and (not ev.get("dt") or not ev.get("w"))]
    print(f"2) 상세정보 확인 {len(targets)}건 (한 건에 몇 초씩 걸립니다)")

    def work(ev):
        seq = ev["id"][1:]
        text = fetch("festivalView.jsp", {"pSeq": seq, "pRo": 1, "pCurrentPage": 1, "pOrder": "01up", "fromDt": frm, "toDt": to})
        return ev, parse_detail(text)

    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        for fut in concurrent.futures.as_completed([pool.submit(work, ev) for ev in targets]):
            done += 1
            print(f"\r   {done}/{len(targets)}", end="", flush=True)
            try:
                ev, det = fut.result()
            except RuntimeError as e:
                report["상세정보 실패"].append(str(e)[:120])
                continue
            if det is None:
                report["상세정보 실패"].append(f"{ev['n']}: 상세 페이지 형식이 다름")
                continue
            had = ev.get("w", "")
            ev.update(detail_fields(det))
            ev["dt"] = today.isoformat()
            if ev["w"] and not had:
                report["공식 사이트 추가"].append(f"{ev['n']}: {ev['w']}")
            elif ev["w"] and had and ev["w"] != had:
                report["공식 사이트 변경"].append(f"{ev['n']}: {had} → {ev['w']}")
    if targets:
        print()

    # 직접 추가한 행사(x-)는 그대로 두고, 문체부에 같은 행사가 있으면 알려줌
    curated = [e for e in old if e.get("src") == "x"]
    for x in curated:
        base = norm(x["n"])
        for ev in scraped.values():
            nb = norm(ev["n"])
            if (base in nb or nb in base) and ev["s"] <= x["e"] and ev["e"] >= x["s"]:
                report["중복 후보"].append(f"직접 추가 '{x['n']}' ↔ 문체부 '{ev['n']}' ({ev['s']}~{ev['e']}, id {ev['id']})")

    final = sorted(merged.values(), key=lambda e: (e["s"], e["n"])) + curated

    # 보고
    stamp = now_kst().strftime("%Y-%m-%d %H:%M")
    lines = [f"## {stamp} 업데이트", f"- 전체 {len(final)}건 (문체부 {len(final) - len(curated)}건, 직접 추가 {len(curated)}건)"]
    for k, v in report.items():
        if v:
            lines.append(f"- **{k} {len(v)}건**")
            lines += [f"  - {x}" for x in v]
    if not any(report[k] for k in ("신규", "일정 변경", "공식 사이트 추가", "공식 사이트 변경", "목록에서 빠짐")):
        lines.append("- 바뀐 내용 없음")
    text = "\n".join(lines)
    print("\n" + text)

    if dry:
        print("\n(--dry-run: 파일은 바꾸지 않았습니다)")
        return
    os.makedirs(os.path.join(DATA, "backup"), exist_ok=True)
    shutil.copy2(EVENTS_JS, os.path.join(DATA, "backup", f"events-{now_kst():%Y%m%d-%H%M}.js"))
    body = json.dumps(final, ensure_ascii=False, separators=(",", ":")).replace("},{", "},\n{")
    tmp = EVENTS_JS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(HEADER + f'window.EVENTS_UPDATED="{now_kst():%Y-%m-%d %H:%M}";\n' + "window.EVENTS=" + body + ";\n")
    os.replace(tmp, EVENTS_JS)
    with open(LOG_MD, "a", encoding="utf-8") as f:
        f.write(text + "\n\n")
    print(f"\n저장: {EVENTS_JS}\n기록: {LOG_MD}\n브라우저를 새로고침하면 반영됩니다.")


if __name__ == "__main__":
    main()
