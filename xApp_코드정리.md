# xApp 코드 정리 — 면접 대비

---

## 공통 구조 (모든 xApp에 적용)

```
MyXapp(xAppBase)          ← xAppBase 상속
    ├── __init__()        ← 변수 초기화
    ├── callback()        ← gNB 데이터 도착 시 자동 호출
    └── @start_function   ← 구독 신청 + 수신 루프 시작
        start()
```

**핵심 용어**
| 용어 | 설명 |
|------|------|
| xAppBase | xApp 개발용 베이스 클래스. RMR 통신, REST API, E2 메시지 처리를 추상화 |
| RMR | RIC Message Router. 컨테이너 간 메시지 라우팅 채널 (소켓 위에 올라간 레이어) |
| http_server_port | xApp이 구독 응답을 받는 HTTP 서버 포트 |
| rmr_port | RIC 내부 컴포넌트들과 통신하는 포트 |
| @start_function | 데코레이터. start()를 별도 스레드로 실행하고 수신 루프도 동시에 가동 |
| E2-Node | E2 인터페이스로 RIC과 연결되는 기지국(gNB) 자체 |
| E2 Agent | gNB 내부에서 E2 프로토콜 통신을 담당하는 소프트웨어 모듈 |
| granulPeriod | 측정 주기(ms). 이 단위로 측정한 값을 집계해서 보내줌 |
| ASN.1 | 통신 표준 인코딩 방식. extract_meas_data()가 이를 파이썬 dict로 변환 |

---

## 1. simple_mon_xapp.py — KPM 모니터링 (기본)

**목적:** gNB에 구독 신청 1회 → gNB가 주기적으로 KPI 데이터 전송 → 출력

**KPM Report Style:** 1 (기지국 전체 집계)

### 코드 흐름

```
실행
 ↓
argparse: --metrics=DRB.UEThpDl,DRB.UEThpUl 파싱
 ↓
MyXapp 객체 생성 → xAppBase.__init__() 호출
  → RMR 초기화, HTTP 서버 시작, Subscriber 연결
 ↓
@start_function → start() 별도 스레드 + 수신 루프 동시 시작
 ↓
start():
  subscribe_report_service_style_1(
      e2_node_id,          # 어느 gNB
      report_period=1000,  # 1초마다
      metric_names,        # 요청할 지표들
      granul_period=100,   # 100ms 단위 측정
      callback             # 데이터 오면 이 함수 호출
  )
 ↓
[1초마다 반복]
gNB → submgr → e2term → xApp: RIC_INDICATION 도착
 ↓
my_subscription_callback(e2_agent_id, subscription_id, hdr, msg):
  extract_hdr_info(hdr)     → 측정 시작 시간 파싱
  extract_meas_data(msg)    → ASN.1 → dict 변환
  
  meas_data["measData"] = {
      "DRB.UEThpDl": 4,       # 전체 DL 속도 (Kbps)
      "DRB.UEThpUl": 11367    # 전체 UL 속도 (Kbps)
  }
  
  → 터미널 출력
```

### 주요 용어
| 용어 | 설명 |
|------|------|
| DRB.UEThpDl | Data Radio Bearer UE Throughput Downlink. UE 다운로드 속도 (Kbps) |
| DRB.UEThpUl | UE 업로드 속도 (Kbps) |
| measData | 기지국 전체 집계값 딕셔너리 |
| Style 1 | E2-Node 전체 집계 지표. 가장 단순한 구독 방식 |

### simple_mon vs simple_rc 차이

```
simple_mon: xApp →(구독 1번)→ gNB
            xApp ←(데이터)←  gNB  [gNB가 알아서 주기적으로 전송]

simple_rc:  xApp →(명령)→ gNB  [xApp이 while 루프로 능동적으로 전송]
            xApp →(명령)→ gNB
```

---

## 2. kpm_mon_xapp.py — KPM 모니터링 (고급)

**목적:** simple_mon과 동일하나 KPM Report Style 1~5 전부 지원

**KPM Report Style:** 실행 시 --kpm_report_style 인자로 선택

### simple_mon과 차이점

```python
# simple_mon: Style 1 고정
subscribe_report_service_style_1(...)

# kpm_mon: if/elif로 스타일 선택
if kpm_report_style == 1:
    subscribe_style_1(...)
elif kpm_report_style == 2:
    subscribe_style_2(...)   # 특정 UE 1명 지정
elif kpm_report_style == 3:
    subscribe_style_3(...)   # 조건에 맞는 UE들
elif kpm_report_style == 4:
    subscribe_style_4(...)   # 조건 UE 각각 개별
elif kpm_report_style == 5:
    subscribe_style_5(...)   # 여러 UE ID 직접 지정
```

### KPM Report Style 비교

| Style | 대상 | 데이터 키 | 비고 |
|-------|------|----------|------|
| 1 | 기지국 전체 집계 | measData | 가장 단순 |
| 2 | UE 1명 지정 | measData | UE ID 직접 지정 |
| 3 | 조건 맞는 UE들 | ueMeasData | 필터링 가능 |
| 4 | 조건 UE 개별 | ueMeasData | 가장 세분화 |
| 5 | UE 여러 명 지정 | ueMeasData | 최소 2개 ID 필요 |

```python
# 콜백에서 Style별 분기
if kpm_report_style in [1, 2]:
    meas_data["measData"]      # 집계 데이터
else:
    meas_data["ueMeasData"]    # UE별 개별 데이터
```

---

## 3. simple_rc_xapp.py — RC 제어

**목적:** while 루프로 5초마다 gNB에 PRB 제어 명령 전송. 구독 없음.

**PRB (Physical Resource Block):** 기지국 주파수 자원을 쪼갠 단위. 비율(%)로 UE에게 얼마나 줄지 제어.

### 코드 흐름

```
실행
 ↓
MyXapp 객체 생성
 ↓
@start_function → start() 별도 스레드 시작
 ↓
start():
  while self.running:   ← Ctrl+C 시 signal_handler가 False로 바꿈
    
    PRB 30% 명령 전송 → 5초 대기
    PRB 50% 명령 전송 → 5초 대기
    PRB 70% 명령 전송 → 5초 대기
    PRB 100% 명령 전송 → 5초 대기
    (반복)
```

### control_slice_level_prb_quota 파라미터

```python
self.e2sm_rc.control_slice_level_prb_quota(
    e2_node_id,              # 어느 gNB에 명령
    ue_id,                   # 어느 UE에 적용 (gnb_cu_ue_f1ap_id)
    min_prb_ratio=10,        # PRB 최솟값 (%)
    max_prb_ratio=30,        # PRB 최댓값 (%)
    dedicated_prb_ratio=100, # 이 UE 전용 예약 비율
    ack_request=1            # 1=응답 요청, 0=fire-and-forget
)
```

### 주요 용어
| 용어 | 설명 |
|------|------|
| PRB | Physical Resource Block. 주파수 자원 조각. 비율로 UE 속도 제한 가능 |
| gnb_cu_ue_f1ap_id | gNB CU에서 이 UE를 식별하는 번호. 기본값 0 = 첫 번째 UE |
| ran_func_id=3 | E2SM-RC RAN Function ID. KPM은 2, RC는 3 |
| slice_level | 네트워크 슬라이스 단위로 자원 배분. 슬라이스별 PRB 제어 |
| self.running | xApp 실행 상태 플래그. signal_handler가 False로 바꾸면 루프 종료 |

---

## 4. simple_rc_ho_xapp.py — 핸드오버 제어

**목적:** 특정 UE를 지정한 셀로 핸드오버 명령 1회 전송 후 종료.

**핸드오버:** UE가 이동하면서 연결 셀을 바꾸는 것. 보통 gNB가 자동 판단하지만, 이 xApp은 RIC이 강제로 명령.

### 코드 흐름

```
실행 (인자 필수: --e2_node_id, --amf_ue_ngap_id, --target_nr_cell_id)
 ↓
@start_function → start()
 ↓
control_handover(e2_node_id, amf_ue_ngap_id, gnb_cu_ue_f1ap_id, plmn, target_nr_cell_id)
 ↓
self.running = False  ← 명령 1회 전송 후 바로 종료 (while 루프 없음)
```

### 핸드오버 명령에 필요한 파라미터

```python
self.e2sm_rc.control_handover(
    e2_node_id,          # 현재 gNB
    amf_ue_ngap_id,      # AMF가 이 UE에 부여한 ID (재접속 시 변경됨)
    gnb_cu_ue_f1ap_id,   # gNB CU 내부 UE ID
    plmn,                # 통신망 식별번호 (국가코드+통신사코드). 테스트: "00101"
    target_nr_cell_id    # 이동할 목적지 셀 ID. 16진수 가능 (0x19B1)
)
```

### simple_rc vs simple_rc_ho

```
simple_rc:    while 루프 → 계속 PRB 제어 명령 반복 전송
simple_rc_ho: 핸드오버 명령 1번 → self.running=False → 바로 종료
```

---

## 5. simple_xapp.py — KPM + RC 결합 (가장 현실적)

**목적:** KPM으로 UE별 누적 DL 데이터를 모니터링하다가, 20MB 넘으면 PRB를 10% ↔ 100% 토글.
실제 AI xApp의 기본 구조 (수집 → 판단 → 제어).

**KPM Report Style:** 4 (UE별 개별 데이터)

### 초기화 변수

```python
self.ue_dl_tx_data = {}          # UE별 누적 DL 데이터 (MB)
self.min_prb_ratio = 1           # PRB 최솟값 (고정)
self.max_prb_ratio1 = 10         # 제한 모드
self.max_prb_ratio2 = 100        # 풀 모드
self.cur_ue_max_prb_ratio = {}   # UE별 현재 PRB 상태
self.dl_tx_data_threshold_mb = 20  # 제어 트리거 기준
```

### 코드 흐름

```
@start_function
 ↓
subscribe_report_service_style_4(
    e2_node_id,
    report_period=1000,      # 1초마다
    matchingUeConds,         # 항상 참인 더미 조건 (모든 UE 포함)
    metric_names=["DRB.RlcSduTransmittedVolumeDL"],
    granul_period=1000,
    callback
)
 ↓
[1초마다]
my_subscription_callback():
  
  meas_data["ueMeasData"] = {
      0: {"measData": {"DRB.RlcSduTransmittedVolumeDL": [100, 200]}},
      1: {"measData": {...}}
  }
  
  for ue_id, ue_data in ueMeasData:
    
    # 단위 변환: kbits → MB
    self.ue_dl_tx_data[ue_id] += sum(values)/8/1000
    
    if ue_dl_tx_data[ue_id] > 20MB:          # 누적 20MB 초과 시
      new_prb = 토글(10% ↔ 100%)             # 현재 상태 반대로
      ue_dl_tx_data[ue_id] = 0              # 누적 초기화
      control_slice_level_prb_quota(...)    # RC 제어 명령
```

### 주요 용어
| 용어 | 설명 |
|------|------|
| DRB.RlcSduTransmittedVolumeDL | RLC 레이어에서 전송된 누적 DL 데이터 양 (Kbits). 속도가 아닌 누적량. |
| RLC | Radio Link Control. UE↔gNB 간 데이터 전송 담당 레이어 |
| ueMeasData | UE별로 분리된 측정 데이터 딕셔너리 (Style 3,4,5에서 사용) |
| sum(values)/8/1000 | Kbits → KBytes(÷8) → MBytes(÷1000) 단위 변환 |
| matchingUeConds | Style 4 구독 시 UE 필터링 조건. 더미 조건으로 모든 UE 포함 |
| lambda | 한 줄짜리 익명 함수. 콜백 파라미터 수를 맞추기 위해 사용 |

---

## 전체 비교 요약

| xApp | 방식 | E2SM | Style | 데이터 방향 | 동작 |
|------|------|------|-------|------------|------|
| simple_mon | 수동 | KPM | 1 | gNB→xApp | 구독 후 데이터 수신·출력 |
| kpm_mon | 수동 | KPM | 1~5 | gNB→xApp | Style 선택 가능한 고급 모니터링 |
| simple_rc | 능동 | RC | - | xApp→gNB | while 루프로 PRB 명령 반복 |
| simple_rc_ho | 능동 | RC | - | xApp→gNB | 핸드오버 명령 1회 후 종료 |
| simple_xapp | 결합 | KPM+RC | 4 | 양방향 | 수집→판단→제어 루프 |

---

## AI xApp으로 확장하는 방법

simple_xapp.py에서 판단 로직 자리에 ML 모델을 넣으면 AI xApp이 된다.

```python
# 현재: 단순 threshold 비교
if value > 20MB:
    toggle PRB

# AI xApp으로 확장:
features = [throughput, prb_usage, ue_count, ...]
action = trained_model.predict(features)   # 모델 추론
control_slice_level_prb_quota(..., max_prb_ratio=action)
```

수집(KPM) → 추론(ML) → 제어(RC) 이 3단계가 AI xApp의 기본 구조.
