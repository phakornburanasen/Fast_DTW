# Manual test: resend a failed/incomplete job by job_id.
from __future__ import annotations

import argparse
import json

import requests


DEFAULT_URL = "http://10.0.32.70:60000/api/DTW_Service"


def _print_response(response: requests.Response) -> None:
    """Print an HTTP response in a readable form."""
    print(f"\nStatus: {response.status_code}")
    print("\nResponse:")
    try:
        print(json.dumps(response.json(), ensure_ascii=False, indent=2))
    except ValueError:
        print(response.text)


def _root_url_without_api_prefix(base_url: str) -> str:
    """Return a root URL fallback when the server has no /api/DTW_Service prefix."""
    suffix = "/api/DTW_Service"
    if base_url.endswith(suffix):
        return base_url[: -len(suffix)]
    return base_url


def _post_with_optional_prefix_fallback(
    base_url: str,
    path: str,
    timeout: int,
) -> requests.Response:
    """POST to base_url/path and retry once without /api/DTW_Service on 404."""
    url = f"{base_url.rstrip('/')}{path}"
    print(f"\nPOST {url}")
    response = requests.post(url, timeout=timeout)

    fallback_base_url = _root_url_without_api_prefix(base_url.rstrip("/"))
    if response.status_code == 404 and fallback_base_url != base_url.rstrip("/"):
        fallback_url = f"{fallback_base_url}{path}"
        print(f"\n[INFO] 404 received. Retrying without API prefix: {fallback_url}")
        response = requests.post(fallback_url, timeout=timeout)

    return response


def main() -> None:
    """Run a manual resend-by-job-id API call."""
    parser = argparse.ArgumentParser(
        description="Manual test for POST /resend_job/job/{job_id}"
    )
    parser.add_argument(
        "job_id",
        type=int,
        help="Job ID to resend. The job must be incomplete and have backup paths.",
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help=f"Base API URL (default: {DEFAULT_URL})",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Request timeout in seconds (default: 300)",
    )
    args = parser.parse_args()

    path = f"/resend_job/job/{args.job_id}"

    print("=" * 72)
    print("TF File Generator - Resend By Job ID")
    print("=" * 72)
    print(f"Job ID: {args.job_id}")

    try:
        response = _post_with_optional_prefix_fallback(
            base_url=args.url,
            path=path,
            timeout=args.timeout,
        )
    except requests.exceptions.ConnectionError:
        print(
            f"\n[ERROR] Cannot connect to server at {args.url}.\n"
            "Start the server first:\n"
            "  uvicorn main:app --host 0.0.0.0 --port 60001 --reload\n"
        )
        return
    except requests.exceptions.ReadTimeout:
        print(
            f"\n[ERROR] Request timed out after {args.timeout}s.\n"
            "DTW may still be running; check server console, DB job status, and DTW logs.\n"
        )
        return

    _print_response(response)


if __name__ == "__main__":
    main()
