from __future__ import annotations

import argparse
import json

from app.services.admin_price_simulator_service import (
    get_status,
    request_stop,
    run_one_cycle_sync,
    run_simulator_forever,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.simulator",
        description="가격/재고 시뮬레이터 CLI",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="시뮬레이터를 실행합니다.")
    run_parser.add_argument(
        "--min-seconds",
        type=int,
        default=180,
        help="최소 대기 시간(초), 기본값 180",
    )
    run_parser.add_argument(
        "--max-seconds",
        type=int,
        default=300,
        help="최대 대기 시간(초), 기본값 300",
    )

    subparsers.add_parser("once", help="사이클 1회만 실행합니다.")
    subparsers.add_parser("stop", help="실행 중인 시뮬레이터에 중지 요청을 보냅니다.")
    subparsers.add_parser("status", help="시뮬레이터 상태를 확인합니다.")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "run":
        run_simulator_forever(
            min_seconds=args.min_seconds,
            max_seconds=args.max_seconds,
        )
        return

    if args.command == "once":
        result = run_one_cycle_sync()
        print(
            json.dumps(
                {
                    "message": "사이클 1회 실행 완료",
                    **result,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    if args.command == "stop":
        result = request_stop()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.command == "status":
        result = get_status()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return


if __name__ == "__main__":
    main()