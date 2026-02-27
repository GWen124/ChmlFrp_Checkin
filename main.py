import cloudscraper
import json
import os
import time
import random
import sys

# 从环境变量获取账号
ACCOUNTS_ENV = os.environ.get('ACCOUNTS_JSON')

def mask_account(index, username):
    # 强制显示为 账号1, 账号2... 不再显示用户名
    return f"账号{index + 1}"

def create_scraper():
    # 模拟 Windows Chrome
    # 每次创建都是一个新的 Session，有助于重置连接状态
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

    # === 配置区域 ===
    # 将重试次数保持在 15 次，应对 WARP 的不稳定性
    MAX_RETRIES = 15 
    # ================
    
    # --- 1. 登录 (超级死缠烂打模式) ---
    token = None
    scraper = create_scraper() # 初始化
    
    for attempt in range(MAX_RETRIES):
        try:
            login_url = "https://cf-v2.uapis.cn/login"
            login_payload = {"username": username, "password": password}
            
            # 发送请求
            res = scraper.post(login_url, json=login_payload, timeout=30)
            
            # 检查 Cloudflare 拦截
            if res.status_code in [520, 522, 525, 403, 503]:
                raise Exception(f"CF拦截/WAF拒绝 (Code {res.status_code})")

            try:
                data = res.json()
            except:
                # 如果是 HTML，说明可能还在验证中
                raise Exception(f"响应非 JSON (Code {res.status_code})")

            if data.get("code") == 200:
                token = data["data"]["usertoken"]
                scraper.headers.update({"Authorization": f"Bearer {token}"})
                print(f"[+] {label} 登录成功 (第 {attempt+1} 次尝试)")
                break 
            else:
                print(f"[x] {label} 登录失败: {data.get('msg')}")
                return # 账号密码错误，直接退出，不重试

        except Exception as e:
            # 打印简略错误信息
            print(f"    [!] 登录尝试 {attempt+1}/{MAX_RETRIES} 失败: {e}")
            
            # 失败后，如果是最后一次就不等了
            if attempt < MAX_RETRIES - 1:
                # 动态调整等待时间：重试次数越多，等待越久 (10秒 ~ 30秒)
                # 这种策略能有效缓解短时间的网络拥堵
                wait = random.uniform(10, 25)
                print(f"        -> 等待 {wait:.1f} 秒后重试...")
                time.sleep(wait)
                
                # 关键优化：如果是 522 网络错误，尝试重建 scraper 实例，刷新连接池
                if "522" in str(e) or "520" in str(e):
                    scraper = create_scraper()
            else:
                print(f"[x] {label} 登录最终失败 (已重试 {MAX_RETRIES} 次)")
                return

    # 登录成功后，稍作休息
    time.sleep(random.uniform(3, 6))

    # --- 2. 签到 (同样死缠烂打) ---
    sign_url = "https://cf-v2.uapis.cn/qiandao"
    sign_payload = {
        "lot_number": "", "captcha_output": "", "pass_token": "", 
        "gen_time": str(int(time.time()))
    }

    for attempt in range(MAX_RETRIES):
        try:
            res = scraper.post(sign_url, json=sign_payload, timeout=30)
            
            if res.status_code in [520, 522, 525, 403]:
                raise Exception(f"CF拦截 (Code {res.status_code})")

            try:
                data = res.json()
            except:
                raise Exception(f"响应非 JSON (Code {res.status_code})")

            code = data.get("code")
            msg = data.get("msg")

            if code == 200:
                print(f"[√] {label} 签到成功! 消息: {msg}")
                return
            elif code == 409:
                print(f"[-] {label} 今日已签到 (提示: {msg})")
                return
            else:
                print(f"[x] {label} 签到失败: {msg} (Code: {code})")
                return

        except Exception as e:
            print(f"    [!] 签到尝试 {attempt+1}/{MAX_RETRIES} 失败: {e}")
            if attempt < MAX_RETRIES - 1:
                wait = random.uniform(10, 25)
                print(f"        -> 等待 {wait:.1f} 秒后重试...")
                time.sleep(wait)
                if "522" in str(e):
                    scraper = create_scraper() # 刷新连接
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

    print("--- 开始 GitHub Actions 签到 (WARP增强版) ---")
    for i, acc in enumerate(accounts):
        run_signin(i, acc.get('username'), acc.get('password'))
        if i < len(accounts) - 1:
            # 账号间增加较长延迟，避免并发过高导致 VPN 降速
            wait_acc = random.uniform(5, 10)
            print(f"\n⏳ 等待 {wait_acc:.1f} 秒处理下一个账号...")
            time.sleep(wait_acc)
            
    print("--- 任务结束 ---")

if __name__ == "__main__":
    main()
