# main.py
import cloudscraper
import json
import os
import time
import random
import sys

# 从环境变量获取账号
ACCOUNTS_ENV = os.environ.get('ACCOUNTS_JSON')

def mask_account(index, username):
    if not username: return f"账号{index+1}"
    if len(username) > 4:
        return f"{username[:2]}***{username[-2:]}"
    return f"账号{index+1}"

def create_scraper():
    # 模拟 Windows Chrome
    return cloudscraper.create_scraper(
        browser={
            'browser': 'chrome',
            'platform': 'windows',
            'desktop': True
        }
    )

def run_signin(index, username, password):
    label = mask_account(index, username)
    print(f"\n[-] 开始处理: {label}")

    scraper = create_scraper()
    max_retries = 5 
    
    # --- 1. 登录 (带重试) ---
    token = None
    for attempt in range(max_retries):
        try:
            login_url = "https://cf-v2.uapis.cn/login"
            login_payload = {"username": username, "password": password}
            
            # 发送请求
            res = scraper.post(login_url, json=login_payload, timeout=20)
            
            # 检查 Cloudflare 拦截
            if res.status_code in [520, 522, 525, 403, 503]:
                raise Exception(f"CF拦截/WAF拒绝 (状态码 {res.status_code})")

            try:
                data = res.json()
            except:
                # 打印一点点内容看看是不是HTML
                print(f"    [调试] 返回内容: {res.text[:50]}...")
                raise Exception(f"响应非 JSON (状态码 {res.status_code})")

            if data.get("code") == 200:
                token = data["data"]["usertoken"]
                scraper.headers.update({"Authorization": f"Bearer {token}"})
                print(f"[+] 登录成功 (第 {attempt+1} 次尝试)")
                break 
            else:
                print(f"[x] 登录失败: {data.get('msg')}")
                return 

        except Exception as e:
            print(f"    [!] 登录尝试 {attempt+1} 失败: {e}")
            if attempt < max_retries - 1:
                time.sleep(random.uniform(3, 8))
            else:
                print(f"[x] {label} 登录最终失败")
                return

    time.sleep(random.uniform(2, 5))

    # --- 2. 签到 (带重试) ---
    sign_url = "https://cf-v2.uapis.cn/qiandao"
    sign_payload = {
        "lot_number": "", "captcha_output": "", "pass_token": "", 
        "gen_time": str(int(time.time()))
    }

    for attempt in range(max_retries):
        try:
            res = scraper.post(sign_url, json=sign_payload, timeout=20)
            
            if res.status_code in [520, 522, 525, 403]:
                raise Exception(f"CF拦截 (状态码 {res.status_code})")

            try:
                data = res.json()
            except:
                raise Exception(f"响应非 JSON (状态码 {res.status_code})")

            code = data.get("code")
            msg = data.get("msg")

            if code == 200:
                print(f"[√] 签到成功! 消息: {msg}")
                return
            elif code == 409:
                print(f"[-] 今日已签到 (提示: {msg})")
                return
            else:
                print(f"[x] 签到失败: {msg} (Code: {code})")
                return

        except Exception as e:
            print(f"    [!] 签到尝试 {attempt+1} 失败: {e}")
            if attempt < max_retries - 1:
                time.sleep(random.uniform(3, 8))
            else:
                print(f"[x] {label} 签到最终失败")

def main():
    if not ACCOUNTS_ENV:
        print("Error: 未找到 ACCOUNTS_JSON 环境变量")
        return

    try:
        accounts = json.loads(ACCOUNTS_ENV)
    except json.JSONDecodeError:
        print("Error: ACCOUNTS_JSON 格式错误")
        return

    print("--- 开始 GitHub Actions 签到 (WARP + Cloudscraper) ---")
    for i, acc in enumerate(accounts):
        run_signin(i, acc.get('username'), acc.get('password'))
        if i < len(accounts) - 1:
            time.sleep(random.uniform(3, 6))
    print("--- 任务结束 ---")

if __name__ == "__main__":
    main()
