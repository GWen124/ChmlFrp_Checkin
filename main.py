import cloudscraper
import json
import os
import time
import random
import sys
import subprocess  # 新增：用于执行系统命令重启 WARP

# 从环境变量获取账号
ACCOUNTS_ENV = os.environ.get('ACCOUNTS_JSON')

def mask_account(index, username):
    return f"账号{index + 1}"

def create_scraper():
    # 模拟 Windows Chrome
    return cloudscraper.create_scraper(
        browser={
            'browser': 'chrome',
            'platform': 'windows',
            'desktop': True
        }
    )

def rotate_warp():
    """
    执行系统命令重启 WARP，以获取新 IP
    """
    print("\n🔄 [IP切换] 正在重启 WARP 以更换 IP...")
    try:
        # 1. 断开连接
        subprocess.run(["sudo", "warp-cli", "--accept-tos", "disconnect"], check=True, stdout=subprocess.DEVNULL)
        time.sleep(3) # 等待完全断开
        
        # 2. 重新连接
        subprocess.run(["sudo", "warp-cli", "--accept-tos", "connect"], check=True, stdout=subprocess.DEVNULL)
        
        # 3. 等待网络恢复 (关键)
        # WARP 连接需要几秒钟握手，多等一会儿确保网络通畅
        print("    -> 等待网络连接建立 (10秒)...")
        time.sleep(10)
        
        # 4. (可选) 打印新 IP 用于验证
        # 这一步不是必须的，但能让你在日志里看到 IP 确实变了
        try:
            ip_check = subprocess.check_output(["curl", "-s", "--max-time", "5", "https://api.ip.sb/ip"], text=True).strip()
            print(f"    -> 新 IP 地址: {ip_check}")
        except:
            print("    -> (IP 查询超时，但连接应该已建立)")
            
    except Exception as e:
        print(f"⚠️ WARP 重启失败: {e}")
        print("    -> 将使用旧 IP 继续尝试...")

def run_signin(index, username, password):
    label = mask_account(index, username)
    print(f"\n[-] 开始处理: {label}")

    MAX_RETRIES = 10 
    
    # --- 1. 登录 ---
    token = None
    scraper = create_scraper() 
    
    for attempt in range(MAX_RETRIES):
        try:
            login_url = "https://cf-v2.uapis.cn/login"
            login_payload = {"username": username, "password": password}
            
            res = scraper.post(login_url, json=login_payload, timeout=30)
            
            if res.status_code in [520, 522, 525, 403, 503]:
                raise Exception(f"CF拦截 (Code {res.status_code})")

            try:
                data = res.json()
            except:
                raise Exception(f"响应非 JSON (Code {res.status_code})")

            if data.get("code") == 200:
                token = data["data"]["usertoken"]
                scraper.headers.update({"Authorization": f"Bearer {token}"})
                print(f"[+] {label} 登录成功 (第 {attempt+1} 次尝试)")
                break 
            else:
                print(f"[x] {label} 登录失败: {data.get('msg')}")
                return 

        except Exception as e:
            print(f"    [!] 登录尝试 {attempt+1} 失败: {e}")
            if attempt < MAX_RETRIES - 1:
                wait = random.uniform(5, 15)
                time.sleep(wait)
                # 如果是网络错误，尝试重建 scraper
                if "522" in str(e): scraper = create_scraper()
            else:
                print(f"[x] {label} 登录最终失败")
                return

    time.sleep(random.uniform(2, 5))

    # --- 2. 签到 ---
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
            print(f"    [!] 签到尝试 {attempt+1} 失败: {e}")
            if attempt < MAX_RETRIES - 1:
                wait = random.uniform(5, 15)
                time.sleep(wait)
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

    print("--- 开始 GitHub Actions 签到 (WARP 动态 IP 版) ---")
    
    # 打印初始 IP
    try:
        init_ip = subprocess.check_output(["curl", "-s", "https://api.ip.sb/ip"], text=True).strip()
        print(f"初始 IP 地址: {init_ip}")
    except:
        pass

    for i, acc in enumerate(accounts):
        # 如果不是第一个账号，则在签到前重启 WARP 换 IP
        if i > 0:
            rotate_warp()
            
        run_signin(i, acc.get('username'), acc.get('password'))
        
        # 账号间稍微暂停一下，虽然 rotate_warp 里已经有等待了
        if i < len(accounts) - 1:
            time.sleep(3)
            
    print("--- 任务结束 ---")

if __name__ == "__main__":
    main()
