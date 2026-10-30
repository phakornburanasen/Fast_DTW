# test_runner.py — Manual test script
# รัน: python test_runner.py
# ต้องการให้ server ทำงานอยู่ก่อน: uvicorn main:app --reload
from __future__ import annotations

import argparse
import json
import requests

# Default: server runs on port 60001.
# Override with: python test_runner.py --url http://10.115.2.74:60001/api/DTW_Service
DEFAULT_URL = "http://10.115.2.74:60000/api/DTW_Service"

PAYLOAD = {
    "request_id": "b7a8f1b0-7df2-4c8e-9e4c-26070001",
    "integration_profile": "RAGTAG",
    "side": "TFOUT",
    "requested_by": "T9334",
    "requested_at": "2026-07-01 00:00:00",
    "source_system": "STM",
    "documents": [
        {
            "record_key": 1,
            "transfer_no": "Test_TF01",
            "doc_date": "2026-07-01",
            "series_name": "TF2607",
            "series": "1636",
            "from_shop_code": "STORE2",
            "from_shop_name": "STORE2",
            "to_shop_code": "",
            "to_shop_name": "",
            "from_whscode": "STORE2",
            "status": "PRINT",
            "print_out_date": "2026-07-01 00:00:00",
            "create_by": "T9334",
            "total_qty": 4,
            "total_amount": 0.0,
            "head_csv": {
                "DocEntry": "",
                "Address": "",
                "CardCode": "",
                "CardName": "",
                "Comments": "Test_TF09",
                "ContactPerson": "",
                "DocDate": "20260701",
                "FromWarehouse": "STORE2",
                "JournalMemo": "Transfer for ใบเกลี่ยโอน",
                "PriceList": "2",
                "Reference1": "",
                "Reference2": "",
                "SalesPersonCode": "",
                "Series": "1636",
                "TaxDate": "",
                "DocObjectCode": "67"
            },
            "detail_csv": [
                {
                    "RecordKey": 1,
                    "LineNum": 0,
                    "Currency": "",
                    "DiscountPercent": "",
                    "Factor2": "",
                    "Factor3": "",
                    "Factor4": "",
                    "Factor": "",
                    "ItemCode": "TH0230226055401",
                    "ItemDescription": "",
                    "Price": "",
                    "ProjectCode": "",
                    "Quantity": "1",
                    "Rate": "",
                    "SerialNumber": "",
                    "VendorNum": "",
                    "WarehouseCode": "INTRAN"
                },
                {
                    "RecordKey": 1,
                    "LineNum": 1,
                    "Currency": "",
                    "DiscountPercent": "",
                    "Factor2": "",
                    "Factor3": "",
                    "Factor4": "",
                    "Factor": "",
                    "ItemCode": "TH0230226066978",
                    "ItemDescription": "",
                    "Price": "",
                    "ProjectCode": "",
                    "Quantity": "1",
                    "Rate": "",
                    "SerialNumber": "",
                    "VendorNum": "",
                    "WarehouseCode": "INTRAN"
                },
                {
                    "RecordKey": 1,
                    "LineNum": 2,
                    "Currency": "",
                    "DiscountPercent": "",
                    "Factor2": "",
                    "Factor3": "",
                    "Factor4": "",
                    "Factor": "",
                    "ItemCode": "TH0232125122229",
                    "ItemDescription": "",
                    "Price": "",
                    "ProjectCode": "",
                    "Quantity": "1",
                    "Rate": "",
                    "SerialNumber": "",
                    "VendorNum": "",
                    "WarehouseCode": "INTRAN"
                },
                {
                    "RecordKey": 1,
                    "LineNum": 3,
                    "Currency": "",
                    "DiscountPercent": "",
                    "Factor2": "",
                    "Factor3": "",
                    "Factor4": "",
                    "Factor": "",
                    "ItemCode": "TH0232125122291",
                    "ItemDescription": "",
                    "Price": "",
                    "ProjectCode": "",
                    "Quantity": "1",
                    "Rate": "",
                    "SerialNumber": "",
                    "VendorNum": "",
                    "WarehouseCode": "INTRAN"
                }
            ]
        }
    ]
}


def main() -> None:
    parser = argparse.ArgumentParser(description="TF File Generator — Manual Test Runner")
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help=f"Base URL of the server (default: {DEFAULT_URL})",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=1800,
        help="Request timeout in seconds. Must be longer than DTW timeout (default: 1800)",
    )
    args = parser.parse_args()
    base_url = args.url.rstrip("/")

    print("=" * 60)
    print("TF File Generator — Manual Test Runner")
    print("=" * 60)
    print(f"\nPOST {base_url}/generate-tf")

    try:
        response = requests.post(
            f"{base_url}/generate-tf",
            json=PAYLOAD,
            timeout=args.timeout,
        )
    except requests.exceptions.ConnectionError:
        print(
            f"\n[ERROR] Cannot connect to server at {base_url}."
            " Please start the server first:\n"
            "  uvicorn main:app --host 0.0.0.0 --port 60000 --reload\n"
        )
        return
    except requests.exceptions.ReadTimeout:
        print(
            f"\n[ERROR] Request timed out after {args.timeout}s."
            " DTW may still be running; check server console, job status, and runner logs.\n"
        )
        return

    print(f"\nStatus: {response.status_code}")
    print("\nResponse:")
    try:
        print(json.dumps(response.json(), ensure_ascii=False, indent=2))
    except Exception:
        print(response.text)


if __name__ == "__main__":
    main()
