"""키움증권 모의투자 API 연결 테스트 스크립트

.env 파일의 API 키와 시크릿이 유효한지 확인합니다.
"""
import os
import sys
import requests
from decimal import Decimal
from dotenv import load_dotenv


def test_api_connection():
    """API 연결 및 인증 테스트"""
    # .env 파일 로드
    load_dotenv()

    api_key = os.getenv("KIWOOM_API_KEY")
    api_secret = os.getenv("KIWOOM_API_SECRET")
    base_url = os.getenv("KIWOOM_API_BASE_URL")
    account_number = os.getenv("KIWOOM_ACCOUNT_NUMBER")

    print("=" * 60)
    print("Kiwoom API Connection Test")
    print("=" * 60)
    print(f"API Base URL: {base_url}")
    print(f"API Key: {api_key[:20]}..." if api_key else "API Key: NOT SET")
    print(f"Account Number: {account_number}")
    print()

    if not all([api_key, api_secret, base_url, account_number]):
        print("[ERROR] Missing required environment variables!")
        print("Please check your .env file.")
        return False

    # 1. OAuth2 토큰 발급 테스트
    print("[Step 1] Testing OAuth2 token acquisition...")
    token_url = f"{base_url}/oauth2/token"

    token_payload = {
        "grant_type": "client_credentials",
        "appkey": api_key,
        "secretkey": api_secret
    }

    try:
        response = requests.post(
            token_url,
            json=token_payload,
            headers={"Content-Type": "application/json"},
            timeout=10
        )

        print(f"  Status Code: {response.status_code}")

        if response.status_code == 200:
            token_data = response.json()
            return_code = token_data.get("return_code")

            if return_code == 0:
                access_token = token_data.get("token")
                print(f"  [SUCCESS] Token acquired successfully!")
                print(f"  Token: {access_token[:30]}...")
                print(f"  Token Type: {token_data.get('token_type', 'N/A')}")
                print(f"  Expires At: {token_data.get('expires_dt', 'N/A')}")
            else:
                print("  [ERROR] Token acquisition failed")
                print(f"  Return Code: {return_code}")
                print(f"  Response: {token_data}")
                return False
        else:
            print(f"  [ERROR] Failed to get token")
            print(f"  Response: {response.text}")
            return False

    except requests.exceptions.ConnectionError as e:
        print(f"  [ERROR] Connection failed: {e}")
        print("  Check if the API base URL is correct.")
        return False
    except requests.exceptions.Timeout:
        print("  [ERROR] Request timeout")
        return False
    except Exception as e:
        print(f"  [ERROR] Unexpected error: {e}")
        return False

    print()

    # 2. 계좌 잔고 조회 테스트
    print("[Step 2] Testing account balance inquiry...")
    balance_url = f"{base_url}/uapi/domestic-stock/v1/trading/inquire-balance"

    headers = {
        "Content-Type": "application/json",
        "authorization": f"Bearer {access_token}",
        "appkey": api_key,
        "secretkey": api_secret,
        "tr_id": "TTTC8434R"  # 모의투자 잔고조회 TR
    }

    params = {
        "CANO": account_number,
        "ACNT_PRDT_CD": "01",  # 계좌상품코드
        "AFHR_FLPR_YN": "N",
        "OFL_YN": "N",
        "INQR_DVSN": "01",
        "UNPR_DVSN": "01",
        "FUND_STTL_ICLD_YN": "N",
        "FNCG_AMT_AUTO_RDPT_YN": "N",
        "PRCS_DVSN": "00",
        "CTX_AREA_FK100": "",
        "CTX_AREA_NK100": ""
    }

    try:
        response = requests.get(
            balance_url,
            headers=headers,
            params=params,
            timeout=10
        )

        print(f"  Status Code: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            print(f"  [SUCCESS] Account balance inquiry successful")
            print(f"  Response Code: {data.get('rt_cd', 'N/A')}")
            print(f"  Message: {data.get('msg1', 'N/A')}")

            # 잔고 정보 출력
            output = data.get("output2")
            if output:
                print(f"  Total Evaluation Amount: {output.get('tot_evlu_amt', 'N/A')}")
                print(f"  Cash Balance: {output.get('dnca_tot_amt', 'N/A')}")

        elif response.status_code == 401:
            print(f"  [ERROR] Authentication failed")
            print(f"  Response: {response.text}")
            return False
        else:
            print(f"  [ERROR] API call failed")
            print(f"  Response: {response.text}")
            return False

    except Exception as e:
        print(f"  [ERROR] Unexpected error: {e}")
        return False

    print()
    print("=" * 60)
    print("[RESULT] All API connection tests PASSED!")
    print("=" * 60)
    return True


if __name__ == "__main__":
    success = test_api_connection()
    sys.exit(0 if success else 1)
