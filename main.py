import requests
import json
import os
import time
import random

# 从环境变量获取账号信息
ACCOUNTS_ENV = os.environ.get('ACCOUNTS_JSON')

# 修改为 macOS (Intel) + Chrome 的 User-Agent
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Origin": "https://panel.chmlfrp.net",
    "Referer": "https://panel.chmlfrp.net/"
}

def mask_account(index):
    return f"账号 {index + 1}"

def safe_json_parse(response, label, action_name):
    """
    安全解析 JSON，如果失败则打印原始文本
    """
    try:
        return response.json()
    except json.JSONDecodeError:
        print(f"[!] {label} {action_name}异常: 响应不是合法的 JSON")
        print(f"    状态码: {response.status_code}")
        # 截取前 200 个字符，防止 HTML 太长刷屏
        print(f"    响应内容(前200字符): {response.text[:200]}")
        return None

def run_signin(index, username, password):
    session = requests.Session()
    session.headers.update(HEADERS)
    
    account_label = mask_account(index)
    print(f"[-] 开始处理: {account_label}")

    # --- 1. 登录 (Login) ---
    login_url = "https://cf-v2.uapis.cn/login"
    login_payload = {
        "username": username,
        "password": password
    }
    
    try:
        # 适当增加了超时时间到 30 秒，防止网络波动
        login_res = session.post(login_url, json=login_payload, timeout=30)
        login_data = safe_json_parse(login_res, account_label, "登录")
        
        if not login_data:
            return # 解析失败，终止该账号
            
        if login_data.get("code") != 200:
            print(f"[x] {account_label} 登录失败: {login_data.get('msg')} (Code: {login_data.get('code')})")
            return
            
        token = login_data["data"]["usertoken"]
        # 设置 Authorization 头
        session.headers.update({"Authorization": f"Bearer {token}"})
        print(f"[+] {account_label} 登录成功")

    except Exception as e:
        print(f"[!] {account_label} 登录请求出错: {e}")
        return

    # 随机延迟 2-5 秒
    time.sleep(random.uniform(2, 5))

    # --- 2. 检查签到状态 (Check Status) ---
    info_url = "https://cf-v2.uapis.cn/qiandao_info"
    try:
        info_res = session.get(info_url, timeout=30)
        info_data = safe_json_parse(info_res, account_label, "获取信息")
        
        if info_data and info_data.get("code") == 200:
            points = info_data.get("data", {}).get("total_points", "未知")
            print(f"[*] {account_label} 当前积分: {points}")
        
    except Exception as e:
        print(f"[!] {account_label} 获取信息网络错误: {e}")

    # --- 3. 执行签到 (Sign In) ---
    sign_url = "https://cf-v2.uapis.cn/qiandao"
    
    sign_payload = {
        "lot_number": "", 
        "captcha_output": "",
        "pass_token": "",
        "gen_time": str(int(time.time()))
    }

    try:
        sign_res = session.post(sign_url, json=sign_payload, timeout=30)
        sign_data = safe_json_parse(sign_res, account_label, "签到")

        if not sign_data:
            print(f"    [提示] 如果状态码是 522/520，说明 GitHub IP 可能被服务商拉黑了。")
            return

        code = sign_data.get("code")
        msg = sign_data.get("msg")

        if code == 200:
            print(f"[√] {account_label} 签到成功! 消息: {msg}")
        elif code == 409:
            print(f"[-] {account_label} 今日已签到 (服务端提示: {msg})")
        else:
            print(f"[x] {account_label} 签到失败: {msg} (代码: {code})")

    except Exception as e:
        print(f"[!] {account_label} 签到请求出错: {e}")

def main():
    if not ACCOUNTS_ENV:
        print("Error: 未找到 ACCOUNTS_JSON 环境变量")
        return

    try:
        accounts = json.loads(ACCOUNTS_ENV)
    except json.JSONDecodeError:
        print("Error: ACCOUNTS_JSON 格式错误")
        return

    print("--- 开始批量签到任务 (MacOS UA 测试) ---")
    for i, acc in enumerate(accounts):
        run_signin(i, acc['username'], acc['password'])
        print("-" * 30)
        time.sleep(5) 
    print("--- 任务结束 ---")

if __name__ == "__main__":
    main()
