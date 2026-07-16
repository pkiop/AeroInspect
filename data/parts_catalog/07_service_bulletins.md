> 본 문서는 데모용 가상 자료이며 실제 항공기 기술자료가 아닙니다.

# AeroInspect 가상 부품 카탈로그 (mini-IPC) — 07. 정비회보 요약집 (Service Bulletin Digest)

**문서 번호**: AI-IPC-DEMO-07
**적용 기체**: AI-DEMO-100 (가상 축소 모형 항공기 — 실존 기종과 무관)
**개정**: Rev. A (데모용)

본 문서는 부품 카탈로그 문서 01~06에서 "참조 SB"로 인용되는 가상 정비회보
(Service Bulletin, SB)의 요약집이다. 각 SB는 대상 부품의 누락·재장착 시
반드시 함께 인용해야 하는 근거 문서이며, 번호 체계는 다음과 같다.

- **SB-DEMO-2025-001 ~ 022**: 부품 누락/재장착 관련 (문서 01~05 대응)
- **SB-DEMO-2025-031 ~ 034**: 미부 손상 평가 관련 (문서 06 대응)

---

## 1. 미부 (Tail Section) — 문서 01 대응

### [SB-DEMO-2025-001] 우측 수직꼬리날개 장착 상태 확인

- **대상 P/N**: ACFT-VTS-R-001 (우측 수직꼬리날개 / Right Vertical Stabilizer)
- **발행 배경**: 데모 리허설 중 우측 수직꼬리날개 루트 체결 나사의 토크 저하
  사례(가상)가 보고되어, 누락·장착 상태 점검을 표준화한다.
- **요구 조치**: 비행 전 점검 시 루트 필렛 간극(0.5 mm 이하)과 토크 확인
  마킹(TM-01) 상태를 육안 확인한다. 누락 확인 시 즉시 지상
  계류(ground_aircraft)하고 AI-IPC-DEMO-01 장착 절차에 따라 재장착한다.

### [SB-DEMO-2025-002] 좌측 수직꼬리날개 장착 상태 확인

- **대상 P/N**: ACFT-VTS-L-001 (좌측 수직꼬리날개 / Left Vertical Stabilizer)
- **발행 배경**: SB-DEMO-2025-001과 동일 사유의 좌측 대응 회보.
- **요구 조치**: 루트 필렛 간극·토크 마킹 확인. 좌/우 전용품 혼용 장착 여부
  (P/N 말미 L/R 표기)를 함께 확인한다. 누락 시 지상 계류(ground_aircraft).

### [SB-DEMO-2025-003] 우측 수평꼬리날개 피벗 고정 상태 확인

- **대상 P/N**: ACFT-HTS-R-001 (우측 수평꼬리날개 / Right Horizontal Stabilizer)
- **발행 배경**: 피벗 고정 나사 풀림에 의한 붙임각 이탈 사례(가상).
- **요구 조치**: 붙임각(0°±0.3°)과 피벗 고정 나사 토크(0.35 N·m) 확인.
  누락 확인 시 지상 계류(ground_aircraft) 후 재장착·대칭 확인.

### [SB-DEMO-2025-004] 좌측 수평꼬리날개 피벗 고정 상태 확인

- **대상 P/N**: ACFT-HTS-L-001 (좌측 수평꼬리날개 / Left Horizontal Stabilizer)
- **발행 배경**: SB-DEMO-2025-003과 동일 사유의 좌측 대응 회보.
- **요구 조치**: 붙임각·토크 확인, 우측과의 스팬 끝단 높이 대칭 확인.
  누락 시 지상 계류(ground_aircraft).

## 2. 주익 / 파일런 / 장착물 (Wing / Pylon / Stores) — 문서 02 대응

### [SB-DEMO-2025-005] 우측 주익 장착 검사

- **대상 P/N**: ACFT-WNG-R-001 (우측 주익 / Right Main Wing)
- **요구 조치**: 주익 루트 체결부 전수 확인. 누락은 즉시 지상
  계류(ground_aircraft) 대상이다.

### [SB-DEMO-2025-006] 좌측 주익 장착 검사

- **대상 P/N**: ACFT-WNG-L-001 (좌측 주익 / Left Main Wing)
- **요구 조치**: SB-DEMO-2025-005와 동일. 누락 시 지상 계류(ground_aircraft).

### [SB-DEMO-2025-007] 우측 익하 파일런 장착 확인

- **대상 P/N**: ACFT-PYL-R-001 (우측 익하 파일런 / Right Underwing Pylon)
- **요구 조치**: 파일런-주익 하드포인트 체결 확인. 누락 시 다음 비행 전
  장착(install_before_flight)을 완료한다.

### [SB-DEMO-2025-008] 좌측 익하 파일런 장착 확인

- **대상 P/N**: ACFT-PYL-L-001 (좌측 익하 파일런 / Left Underwing Pylon)
- **요구 조치**: SB-DEMO-2025-007과 동일. 누락 시 비행 전
  장착(install_before_flight).

### [SB-DEMO-2025-009] 우측 훈련용 미사일 장착/분리 기록 관리

- **대상 P/N**: ACFT-MSL-R-001 (우측 훈련용 미사일 / Right Training Missile)
- **발행 배경**: 훈련용 장착물의 장착/분리 이력이 기록과 불일치한 사례(가상).
- **요구 조치**: 선택 장착품이므로 누락 상태 운용이 가능하나, 장착/분리 시마다
  기록을 갱신하고 추세를 모니터링(monitor)한다. 좌측과의 비대칭 장착 상태는
  보고서에 명시한다.

### [SB-DEMO-2025-010] 좌측 훈련용 미사일 장착/분리 기록 관리

- **대상 P/N**: ACFT-MSL-L-001 (좌측 훈련용 미사일 / Left Training Missile)
- **요구 조치**: SB-DEMO-2025-009와 동일. 누락 시 모니터링(monitor).

## 3. 랜딩기어 (Landing Gear) — 문서 03 대응

### [SB-DEMO-2025-011] 전방 랜딩기어 장착 상태 확인

- **대상 P/N**: ACFT-NLG-C-001 (전방 랜딩기어 / Nose Landing Gear)
- **요구 조치**: 스트럿 체결·다운록 확인. 누락 시 지상 계류(ground_aircraft).

### [SB-DEMO-2025-012] 우측 주 랜딩기어 장착 상태 확인

- **대상 P/N**: ACFT-MLG-R-001 (우측 주 랜딩기어 / Right Main Landing Gear)
- **요구 조치**: 스트럿 체결·다운록 확인. 누락 시 지상 계류(ground_aircraft).

### [SB-DEMO-2025-013] 좌측 주 랜딩기어 장착 상태 확인

- **대상 P/N**: ACFT-MLG-L-001 (좌측 주 랜딩기어 / Left Main Landing Gear)
- **요구 조치**: 스트럿 체결·다운록 확인. 누락 시 지상 계류(ground_aircraft).

### [SB-DEMO-2025-014] 전방 랜딩기어 도어 장착 확인

- **대상 P/N**: ACFT-NGD-C-001 (전방 랜딩기어 도어 / Nose Gear Door)
- **요구 조치**: 힌지·링크 체결 확인. 누락 시 비행 전
  장착(install_before_flight).

## 4. 동체 / 캐노피 (Fuselage / Canopy) — 문서 04 대응

### [SB-DEMO-2025-015] 캐노피 잠금 기구 확인

- **대상 P/N**: ACFT-CNP-C-001 (캐노피 / Canopy)
- **요구 조치**: 잠금 기구·실링 상태 확인. 누락 시 지상
  계류(ground_aircraft).

### [SB-DEMO-2025-016] 후방 동체 점검 패널 체결 확인

- **대상 P/N**: ACFT-APN-C-001 (후방 동체 점검 패널 / Aft Fuselage Access Panel)
- **요구 조치**: 패널 파스너 전수 체결 확인. 누락 시 비행 전
  장착(install_before_flight).

### [SB-DEMO-2025-017] 동체 중앙 외부 연료탱크 장착 확인

- **대상 P/N**: ACFT-EFT-C-001 (동체 중앙 외부 연료탱크 / Centerline External Fuel Tank)
- **요구 조치**: 선택 장착품. 누락 상태 운용 가능하나 장착/분리 이력을
  기록하고 모니터링(monitor)한다.

### [SB-DEMO-2025-018] 노즈콘(레이돔) 장착 상태 확인

- **대상 P/N**: ACFT-RDM-C-001 (노즈콘(레이돔) / Nose Cone (Radome))
- **요구 조치**: 체결부·정렬 확인. 누락 시 지상 계류(ground_aircraft).

## 5. 센서 / 프로브류 (Sensors / Probes) — 문서 05 대응

### [SB-DEMO-2025-019] 피토 프로브 장착·오염 점검

- **대상 P/N**: ACFT-PIT-C-001 (피토 프로브 / Pitot Probe)
- **발행 배경**: 프로브 개구부 이물질 유입 사례(가상).
- **요구 조치**: 장착 상태와 개구부 오염 여부 확인. 누락 시 지상
  계류(ground_aircraft) — 필수 비행 데이터(속도) 확보 불가.

### [SB-DEMO-2025-020] 우측 받음각 센서 장착 확인

- **대상 P/N**: ACFT-AOA-R-001 (우측 받음각 센서 / Right AOA Vane)
- **요구 조치**: 베인 회전 자유도·장착 상태 확인. 누락 시 지상
  계류(ground_aircraft).

### [SB-DEMO-2025-021] 좌측 받음각 센서 장착 확인

- **대상 P/N**: ACFT-AOA-L-001 (좌측 받음각 센서 / Left AOA Vane)
- **요구 조치**: SB-DEMO-2025-020과 동일. 누락 시 지상
  계류(ground_aircraft).

### [SB-DEMO-2025-022] VHF 블레이드 안테나 장착 확인

- **대상 P/N**: ACFT-ANT-C-001 (VHF 블레이드 안테나 / VHF Blade Antenna)
- **요구 조치**: 베이스 체결 확인. 누락 시 비행 전
  장착(install_before_flight).

## 6. 미부 손상 평가 (Tail Damage Assessment) — 문서 06 대응

### [SB-DEMO-2025-031] 우측 수직꼬리날개 손상 평가 기준

- **대상 P/N**: ACFT-VTS-R-001 (우측 수직꼬리날개 / Right Vertical Stabilizer)
- **요구 조치**: 손상 발견 시 AI-IPC-DEMO-06의 손상 허용 한계를 적용해
  평가하고, 한계 초과 시 지상 계류(ground_aircraft) 후 교체한다.

### [SB-DEMO-2025-032] 좌측 수직꼬리날개 손상 평가 기준

- **대상 P/N**: ACFT-VTS-L-001 (좌측 수직꼬리날개 / Left Vertical Stabilizer)
- **요구 조치**: SB-DEMO-2025-031과 동일 기준을 적용한다.

### [SB-DEMO-2025-033] 우측 수평꼬리날개 손상 평가 기준

- **대상 P/N**: ACFT-HTS-R-001 (우측 수평꼬리날개 / Right Horizontal Stabilizer)
- **요구 조치**: AI-IPC-DEMO-06 손상 허용 한계 적용, 한계 초과 시 지상
  계류(ground_aircraft).

### [SB-DEMO-2025-034] 좌측 수평꼬리날개 손상 평가 기준

- **대상 P/N**: ACFT-HTS-L-001 (좌측 수평꼬리날개 / Left Horizontal Stabilizer)
- **요구 조치**: SB-DEMO-2025-033과 동일 기준을 적용한다.

---

## 7. 인용 규칙

1. 부품 누락 보고 시 해당 부품의 "참조 SB"(문서 01~05)와 본 요약집의 대응
   항목을 함께 인용한다.
2. 손상 보고 시에는 SB-DEMO-2025-031~034(문서 06 대응)를 인용하며, 누락
   보고용 SB(001~004)와 혼용하지 않는다.
3. 본 요약집의 모든 SB 번호·발행 배경·조치는 데모 시나리오용 가상 정보이다.
