# main.py
import requests
import json
import os
import time
import random

# 从环境变量获取账号信息
ACCOUNTS_ENV = os.environ.get('ACCOUNTS_JSON')

# 模拟手机端 UA (与抓包保持一致)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 26_3_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/143.0.7499.151 Mobile/15E148 Safari/604.1",
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh-Hans;q=0.9",
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
        # 截取前 200 个字符，防止 HTML 太长刷屏，让你看清是不是被 WAF 拦截了
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
        login_res = session.post(login_url, json=login_payload, timeout=15)
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

    # 随机延迟，避免请求太快被识别
    time.sleep(random.uniform(1, 3))

    # --- 2. 检查签到状态 (Check Status) ---
    info_url = "https://cf-v2.uapis.cn/qiandao_info"
    try:
        info_res = session.get(info_url, timeout=15)
        info_data = safe_json_parse(info_res, account_label, "获取信息")
        
        if info_data and info_data.get("code") == 200:
            points = info_data.get("data", {}).get("total_points", "未知")
            print(f"[*] {account_label} 当前积分: {points}")
        
    except Exception as e:
        print(f"[!] {account_label} 获取信息网络错误: {e}")

    # --- 3. 执行签到 (Sign In) ---
    sign_url = "https://cf-v2.uapis.cn/qiandao"
    
    # 这里依然是空参数。
    # 如果服务端强制校验，这次运行后你会看到"响应内容"里包含具体的错误页面 HTML
    sign_payload = {
        "lot_number": "", 
        "captcha_output": "",
        "pass_token": "",
        "gen_time": str(int(time.time()))
    }

    try:
        sign_res = session.post(sign_url, json=sign_payload, timeout=15)
        sign_data = safe_json_parse(sign_res, account_label, "签到")

        if not sign_data:
            print(f"    [提示] 如果状态码是 403 或 500，说明服务端识别到了缺少极验参数，拦截了请求。")
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

    print("--- 开始批量签到任务 (调试模式) ---")
    for i, acc in enumerate(accounts):
        run_signin(i, acc['username'], acc['password'])
        print("-" * 30)
        time.sleep(3) 
    print("--- 任务结束 ---")

if __name__ == "__main__":
    main()
