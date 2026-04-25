#!/usr/bin/env python3
"""
QoS Control xApp - 트래픽 등급별 자동 PRB 제어
=================================================
UE의 실시간 DL throughput을 모니터링하고,
트래픽 등급에 따라 PRB 할당을 자동으로 조절한다.

등급 기준:
  HIGH  : throughput > 2000 Kbps  → PRB 30%  (헤비 유저 제한)
  MID   : throughput > 500  Kbps  → PRB 60%  (일반 유저)
  LOW   : throughput <= 500 Kbps  → PRB 100% (약한 신호 유저 우대)

사용법:
  docker compose exec python_xapp_runner ./qos_control_xapp.py
  docker compose exec python_xapp_runner ./qos_control_xapp.py --e2_node_id gnbd_001_001_00019b_0
"""

import argparse
import signal
from lib.xAppBase import xAppBase


class QoSControlXapp(xAppBase):
    def __init__(self, http_server_port, rmr_port):
        super(QoSControlXapp, self).__init__('', http_server_port, rmr_port)

        # ── 등급 기준 (Kbps) ──────────────────────────────────────────
        self.HIGH_THRESHOLD = 2000   # 이 값 초과 → HIGH 등급
        self.LOW_THRESHOLD  = 500    # 이 값 이하 → LOW 등급

        # ── 등급별 PRB 최댓값 (%) ────────────────────────────────────
        self.PRB_HIGH = 30    # 헤비 유저: 자원 제한
        self.PRB_MID  = 60    # 일반 유저: 중간
        self.PRB_LOW  = 100   # 약한 신호 유저: 최대 허용

        self.min_prb_ratio = 1

        # UE별 현재 PRB 상태 추적 (변경 시에만 RC 명령 전송하기 위해)
        self.cur_prb_state = {}

    def my_subscription_callback(self, e2_agent_id, subscription_id, indication_hdr, indication_msg):
        """
        gNB에서 KPI 데이터가 올 때마다 자동으로 호출되는 콜백.
        UE별 throughput을 분석하고 PRB 등급을 결정한다.
        """
        indication_hdr = self.e2sm_kpm.extract_hdr_info(indication_hdr)
        meas_data = self.e2sm_kpm.extract_meas_data(indication_msg)

        print("\n[QoS Control xApp] @ {}  |  gNB: {}".format(
            indication_hdr['colletStartTime'], e2_agent_id))
        print("=" * 65)

        # ── UE별 데이터 처리 ─────────────────────────────────────────
        for ue_id, ue_meas_data in meas_data["ueMeasData"].items():
            for metric_name, values in ue_meas_data["measData"].items():

                if metric_name != "DRB.UEThpDl":
                    continue

                # 평균 DL throughput 계산 (Kbps)
                avg_thp = sum(values) / len(values) if values else 0

                # ── 등급 분류 ─────────────────────────────────────────
                if avg_thp > self.HIGH_THRESHOLD:
                    tier    = "HIGH"
                    new_prb = self.PRB_HIGH
                elif avg_thp > self.LOW_THRESHOLD:
                    tier    = "MID "
                    new_prb = self.PRB_MID
                else:
                    tier    = "LOW "
                    new_prb = self.PRB_LOW

                prev_prb = self.cur_prb_state.get(ue_id, None)

                # 현재 상태 출력
                print("  UE {:>3} | {:>8.1f} Kbps | Tier: {} | PRB: {:>3}%".format(
                    ue_id, avg_thp, tier, new_prb))

                # ── PRB 변경이 필요할 때만 RC 제어 명령 전송 ─────────
                if prev_prb != new_prb:
                    prev_str = "{}%".format(prev_prb) if prev_prb is not None else "N/A"
                    print("    --> PRB 변경 감지: {} → {}%  (RC Control 전송)".format(
                        prev_str, new_prb))

                    self.e2sm_rc.control_slice_level_prb_quota(
                        e2_agent_id,
                        ue_id,
                        min_prb_ratio=self.min_prb_ratio,
                        max_prb_ratio=new_prb,
                        dedicated_prb_ratio=100,
                        ack_request=1
                    )
                    self.cur_prb_state[ue_id] = new_prb

        print("=" * 65)

    @xAppBase.start_function
    def start(self, e2_node_id):
        """
        xApp 시작 함수.
        KPM Style 4 로 구독 신청 → UE별 DL throughput 수신 시작.
        """
        report_period  = 1000   # 1000ms 마다 데이터 수신
        granul_period  = 1000   # 1000ms 단위로 측정한 값
        metric_names   = ["DRB.UEThpDl"]

        # 모든 UE를 포함하는 더미 조건 (항상 참)
        matchingUeConds = [{'testCondInfo': {
            'testType' : ('ul-rSRP', 'true'),
            'testExpr' : 'lessthan',
            'testValue': ('valueInt', 1000)
        }}]

        # subscribe 함수가 요구하는 4개 파라미터 → my_subscription_callback 으로 전달
        subscription_callback = lambda agent, sub, hdr, msg: \
            self.my_subscription_callback(agent, sub, hdr, msg)

        print("\n[QoS Control xApp] 시작!")
        print("  대상 gNB  : {}".format(e2_node_id))
        print("  지표      : {}".format(metric_names))
        print("  등급 기준 : HIGH > {}Kbps (PRB {}%) | MID > {}Kbps (PRB {}%) | LOW (PRB {}%)".format(
            self.HIGH_THRESHOLD, self.PRB_HIGH,
            self.LOW_THRESHOLD,  self.PRB_MID,
            self.PRB_LOW))
        print("  구독 신청 중 (KPM Report Style 4)...")

        self.e2sm_kpm.subscribe_report_service_style_4(
            e2_node_id,
            report_period,
            matchingUeConds,
            metric_names,
            granul_period,
            subscription_callback
        )


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='QoS Control xApp - 트래픽 등급별 자동 PRB 제어'
    )
    parser.add_argument("--http_server_port", type=int, default=8090,
                        help="HTTP 서버 포트 (기본값: 8090)")
    parser.add_argument("--rmr_port",         type=int, default=4560,
                        help="RMR 포트 (기본값: 4560)")
    parser.add_argument("--e2_node_id",       type=str, default='gnbd_001_001_00019b_0',
                        help="gNB E2 Node ID")
    parser.add_argument("--ran_func_id",      type=int, default=2,
                        help="E2SM-KPM RAN Function ID (기본값: 2)")

    args = parser.parse_args()

    myXapp = QoSControlXapp(args.http_server_port, args.rmr_port)
    myXapp.e2sm_kpm.set_ran_func_id(args.ran_func_id)

    signal.signal(signal.SIGQUIT, myXapp.signal_handler)
    signal.signal(signal.SIGTERM, myXapp.signal_handler)
    signal.signal(signal.SIGINT, myXapp.signal_handler)

    myXapp.start(args.e2_node_id)
    # xApp 종료 시 모든 구독 자동 해제
