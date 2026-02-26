# main.py
import requests
import json
import os
import time

# 从环境变量获取账号信息，格式建议为 JSON 字符串: [{"username": "xxx", "password": "xxx"}, ...]
ACCOUNTS_ENV = os.environ.get('ACCOUNTS_JSON')

# 模拟 HAR 中的手机端 UA
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

def run_signin(index, username, password):
    session = requests.Session()
    session.headers.update(HEADERS)
    
    account_label = mask_account(index)
    print(f"[-] 开始处理: {account_label}")

    # 1. 登录 (Login)
    login_url = "https://cf-v2.uapis.cn/login"
    login_payload = {
        "username": username,
        "password": password
    }
    
    try:
        login_res = session.post(login_url, json=login_payload, timeout=10)
        login_data = login_res.json()
        
        if login_data.get("code") != 200:
            print(f"[x] {account_label} 登录失败: {login_data.get('msg')}")
            return
            
        # 获取 Token 并设置到后续请求头中
        token = login_data["data"]["usertoken"]
        session.headers.update({"Authorization": f"Bearer {token}"})
        print(f"[+] {account_label} 登录成功")

    except Exception as e:
        print(f"[!] {account_label} 登录异常: {e}")
        return

    # 2. 检查签到状态 (Check Status)
    # 虽然你提到 info 接口可能延迟，但可以作为参考
    info_url = "https://cf-v2.uapis.cn/qiandao_info"
    try:
        info_res = session.get(info_url, timeout=10)
        info_data = info_res.json()
        
        # 注意：根据你的 HAR，这里即使签到过也可能返回 is_signed_in_today: false，所以主要依靠签到动作的反馈
        # 我们仅打印一下积分信息
        current_points = info_data.get("data", {}).get("total_points", "未知")
        print(f"[*] {account_label} 当前积分: {current_points}")
        
    except Exception as e:
        print(f"[!] {account_label} 获取信息异常: {e}")

    # 3. 执行签到 (Sign In)
    sign_url = "https://cf-v2.uapis.cn/qiandao"
    
    # 关键点：这里是极验验证码参数。
    # 纯脚本无法生成有效的 lot_number/captcha_output/pass_token。
    # 如果服务端强制校验，这里会失败。我们尝试发送空值或模拟结构，看是否能通过移动端接口绕过。
    sign_payload = {
        # 如果你有对接打码平台，可以在这里填入获取到的参数
        "lot_number": "", 
        "captcha_output": "",
        "pass_token": "",
        "gen_time": str(int(time.time()))
    }

    try:
        sign_res = session.post(sign_url, json=sign_payload, timeout=10)
        sign_data = sign_res.json()
        
        code = sign_data.get("code")
        msg = sign_data.get("msg")

        if code == 200:
            # 成功: {"msg":"签到成功！您本次签到获得238点积分",...}
            # 提取积分数字
            import re
            points_match = re.search(r"获得(\d+)点积分", msg)
            points_gained = points_match.group(1) if points_match else "未知"
            print(f"[√] {account_label} 签到成功! 获得积分: {points_gained}, 消息: {msg}")
        elif code == 409:
            # 重复签到: {"msg":"请勿重复签到",...}
            print(f"[-] {account_label} 今日已签到 (服务端提示: {msg})")
        else:
            # 失败 (可能是验证码校验失败)
            print(f"[x] {account_label} 签到失败: {msg} (代码: {code})")
            print(f"    提示: 如果失败原因是参数错误，说明服务端强制开启了极验滑块验证，纯脚本无法绕过。")

    except Exception as e:
        print(f"[!] {account_label} 签到请求异常: {e}")

def main():
    if not ACCOUNTS_ENV:
        print("未找到 ACCOUNTS_JSON 环境变量，请检查 Secrets 设置。")
        return

    try:
        accounts = json.loads(ACCOUNTS_ENV)
    except json.JSONDecodeError:
        print("ACCOUNTS_JSON 格式错误，请确保是有效的 JSON 数组字符串。")
        return

    print("--- 开始批量签到任务 ---")
    for i, acc in enumerate(accounts):
        run_signin(i, acc['username'], acc['password'])
        time.sleep(2) # 账号间稍微延时
    print("--- 任务结束 ---")

if __name__ == "__main__":
    main()
