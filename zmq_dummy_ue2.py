#!/usr/bin/env python3
"""
Dummy ZMQ UE for gNB Cell 2.
Unblocks srsRAN gNB's second ZMQ cell so Cell 1 can transmit to the real UE.

Protocol (srsRAN Project ZMQ):
  DL: gNB binds REP on tx_port (2002). We connect REQ, send 1-byte trigger, receive DL samples.
  UL: gNB connects REQ to rx_port (2003). We bind REP, receive 1-byte trigger, send zero UL samples.
"""
import zmq
import numpy as np
import threading
import signal
import sys
import time

GNB_TX_PORT = 2002   # gNB REP+BIND  -> we REQ+CONNECT
GNB_RX_PORT = 2003   # gNB REQ+CONNECT -> we REP+BIND
SAMPLES_PER_SLOT = 11520
UL_PAYLOAD = np.zeros(SAMPLES_PER_SLOT, dtype=np.complex64).tobytes()

running = True


def dl_loop(ctx):
    sock = ctx.socket(zmq.REQ)
    sock.setsockopt(zmq.RCVTIMEO, 1000)
    sock.setsockopt(zmq.SNDTIMEO, 1000)
    sock.connect(f"tcp://127.0.0.1:{GNB_TX_PORT}")
    print(f"[DL] REQ connected to tcp://127.0.0.1:{GNB_TX_PORT}")
    while running:
        try:
            sock.send(b'\x00')
            sock.recv()
        except zmq.Again:
            pass
        except zmq.ZMQError:
            if running:
                time.sleep(0.01)
    sock.close()


def ul_loop(ctx):
    sock = ctx.socket(zmq.REP)
    sock.setsockopt(zmq.RCVTIMEO, 1000)
    sock.setsockopt(zmq.SNDTIMEO, 1000)
    sock.bind(f"tcp://127.0.0.1:{GNB_RX_PORT}")
    print(f"[UL] REP bound on tcp://127.0.0.1:{GNB_RX_PORT}")
    while running:
        try:
            sock.recv()
            sock.send(UL_PAYLOAD)
        except zmq.Again:
            pass
        except zmq.ZMQError:
            if running:
                time.sleep(0.01)
    sock.close()


def signal_handler(sig, frame):
    global running
    running = False
    sys.exit(0)


if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    ctx = zmq.Context()
    t_ul = threading.Thread(target=ul_loop, args=(ctx,), daemon=True)
    t_dl = threading.Thread(target=dl_loop, args=(ctx,), daemon=True)

    t_ul.start()
    t_dl.start()

    print("Dummy Cell-2 UE running (Ctrl+C to stop)...")
    try:
        while running:
            time.sleep(1)
    except KeyboardInterrupt:
        running = False
