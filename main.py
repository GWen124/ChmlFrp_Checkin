import os
import json
import asyncio
import random
import cv2
import numpy as np
import re
from playwright.async_api import async_playwright

ACCOUNTS_JSON = os.getenv("ACCOUNTS_JSON")
LOGIN_URL = "https://panel.chmlfrp.net/sign"
DASHBOARD_URL = "https://panel.chmlfrp.net/"

async def solve_slider(page):
    try:
        print("      >> [滑块] 正在检测...")
        try:
            bg_handle = await page.wait_for_selector(".geetest_bg, canvas.geetest_canvas_bg", timeout=5000)
        except:
            print("      >> [滑块] 未出现，跳过")
            return

        print("      >> [滑块] 发现！开始破解...")
        box = await bg_handle.bounding_box()
        if not box: return

        await page.screenshot(path="captcha_bg.png", clip=box)
        
        target_x = 150 
        try:
            image = cv2.imread("captcha_bg.png")
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            blurred = cv2.GaussianBlur(gray, (5, 5), 0)
            canny = cv2.Canny(blurred, 200, 400)
            contours, _ = cv2.findContours(canny, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                (x, y, w, h) = cv2.boundingRect(contour)
                if 30 < w < 80 and 30 < h < 80 and x > 40:
                    target_x = x
                    break
            print(f"      >> [滑块] 识别缺口位置: {target_x}")
        except: pass

        knob = await page.query_selector(".geetest_btn, .geetest_slider_button")
        if knob:
            box_knob = await knob.bounding_box()
            if box_knob:
                start_x = box_knob["x"] + box_knob["width"] / 2
                start_y = box_knob["y"] + box_knob["height"] / 2
                
                await page.mouse.move(start_x, start_y)
                await page.mouse.down()
                await page.mouse.move(start_x + target_x, start_y + random.randint(-5, 5), steps=30)
                await asyncio.sleep(0.5)
                await page.mouse.up()
                print("      >> [滑块] 动作完成")
        await asyncio.sleep(4)
    except Exception as e:
        print(f"      >> [滑块] 异常: {e}")

async def run_account(context, account, account_index):
    username = account.get("username")
    password = account.get("password")
    
    # 彻底隐藏账号，使用序号
    account_label = f"账号 {account_index}"
    print(f"\n========== 开始处理 {account_label} ==========")

    page = await context.new_page()
    checkin_result = {"status": "未知", "msg": "未执行", "points": "0"}
    
    # --- API 监听 (最强辅助) ---
    async def handle_response(response):
        # 1. 监听签到动作结果
        if "qiandao" in response.url and response.request.method == "POST" and response.status == 200:
            try:
                data = await response.json()
                print(f"   [API] 捕获签到结果: {data.get('msg')}")
                checkin_result["msg"] = data.get("msg", "API无消息")
                code = data.get("code")
                if code == 200:
                    checkin_result["status"] = "成功"
                    match = re.search(r'获得(\d+)', str(data.get("msg")))
                    if match: checkin_result["points"] = match.group(1)
                elif code == 409:
                    checkin_result["status"] = "已签到"
            except: pass
        
        # 2. 监听页面加载时的状态查询
        if "qiandao_info" in response.url and response.status == 200:
            try:
                data = await response.json()
                d = data.get("data", {})
                # 如果 API 直接告诉我们今天签过了，那就稳了
                if d and d.get("is_signed_in_today") is True:
                     checkin_result["status"] = "已签到"
                     checkin_result["msg"] = "API检测: 今日已签"
                     checkin_result["points"] = str(d.get("total_points", 0))
                     print(f"   [API] 查询发现今日已签到，积分: {checkin_result['points']}")
            except: pass

    page.on("response", handle_response)

    try:
        print(f"1. 打开登录页...")
        await page.goto(LOGIN_URL, timeout=60000)
        
        # 切 Tab
        try:
            login_tab = page.locator("text='登录'").first
            if await login_tab.is_visible(): await login_tab.click()
        except: pass

        print("2. 正在登录...")
        await page.fill("input[placeholder*='用户'], input[placeholder*='账号'], input[name='username']", username)
        await page.fill("input[type='password']", password)
        
        # 增加登录超时时间到 30s
        try:
            async with page.expect_response(lambda response: "login" in response.url, timeout=30000) as response_info:
                await page.click("button:has-text('登录'), .login-btn, button[type='submit']")
            print("   >> 登录请求发送成功")
        except:
            print("   >> 警告: 登录接口响应超时，可能已登录或网络卡顿，继续尝试...")
        
        print(f"3. 前往面板: {DASHBOARD_URL}")
        await page.goto(DASHBOARD_URL)
        
        # --- 关键修复：页面假死救星 ---
        print("4. 等待数据加载...")
        try:
            # 等待 qiandao_info 接口，或者页面变得空闲
            # 如果 10秒没等到，说明页面可能卡住了
            await page.wait_for_response(lambda res: "qiandao_info" in res.url, timeout=10000)
            print("   >> 页面数据加载正常")
        except:
            print("   >> ⚠️ 页面似乎卡住了(未检测到数据包)，尝试刷新页面...")
            await page.reload()
            await asyncio.sleep(5)
            # 刷新后再次等待网络空闲
            try: await page.wait_for_load_state('networkidle', timeout=10000)
            except: pass
        
        await asyncio.sleep(3)

        # 如果 API 已经告诉我们签到了，就不用费劲找按钮了
        if checkin_result["status"] == "已签到":
            print("   >> 根据 API 信息，跳过按钮查找")
        else:
            print("5. 寻找按钮...")
            # 你的截图显示按钮文字可能是“签到”或者“签到信息”旁边
            # 扩大搜索范围，NaivUI 的按钮结构比较深
            qiandao_btn = None
            
            # 尝试 1: 直接找文本
            candidates = [
                page.locator("button:has-text('签到')"),
                page.locator(".n-button:has-text('签到')"),
                page.locator("div:has-text('签到')[role='button']")
            ]
            
            for loc in candidates:
                if await loc.count() > 0 and await loc.first.is_visible():
                    qiandao_btn = loc.first
                    print("   >> 找到按钮 (策略1)")
                    break
            
            # 尝试 2: 如果没找到，尝试在“签到信息”附近找
            if not qiandao_btn:
                info_text = page.locator("text='签到信息'")
                if await info_text.count() > 0:
                    # 找它的兄弟节点（通常是前一个按钮）
                    # 假设结构是 [签到] [签到信息]
                    # 我们找 "签到信息" 父级的子元素里的按钮
                    parent = info_text.first.locator("xpath=..")
                    siblings = parent.locator("button")
                    count = await siblings.count()
                    for i in range(count):
                        btn_text = await siblings.nth(i).text_content()
                        if "签到" in btn_text and "信息" not in btn_text:
                            qiandao_btn = siblings.nth(i)
                            print("   >> 找到按钮 (策略2: 兄弟节点)")
                            break

            if qiandao_btn:
                # 悬停检测
                await qiandao_btn.hover()
                await asyncio.sleep(1)
                
                if await page.locator("text='您今天已经签到过啦'").is_visible():
                    checkin_result["status"] = "已签到"
                    checkin_result["msg"] = "UI提示: 已签到"
                else:
                    print("   >> 点击签到...")
                    await qiandao_btn.click()
                    await solve_slider(page)
                    await asyncio.sleep(5)
            else:
                print("❌ 依然找不到按钮，可能是 API 延迟或页面布局变更")
                # 最后的补救：如果积分已经有了，那也算成功
                if checkin_result["points"] != "0":
                     checkin_result["status"] = "成功"
                     checkin_result["msg"] = "未点按钮但积分已更新"
                else:
                     checkin_result["msg"] = "找不到按钮"

    except Exception as e:
        print(f"❌ 运行异常: {str(e)[:100]}")
        checkin_result["msg"] = "脚本执行出错"

    finally:
        await page.close()

    # 最终状态判定
    status_icon = "✅" if checkin_result["status"] in ["成功", "已签到"] else "❌"
    log_msg = f"{account_label} {status_icon} | 状态: {checkin_result['status']} | 消息: {checkin_result['msg']} | 积分: {checkin_result['points']}"
    print(log_msg)
    
    if "GITHUB_STEP_SUMMARY" in os.environ:
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as f:
            f.write(f"{log_msg}\n")

async def main():
    if not ACCOUNTS_JSON: return
    accounts = json.loads(ACCOUNTS_JSON)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--disable-blink-features=AutomationControlled', '--no-sandbox']
        )
        
        # 使用 enumerate 获取序号 (index 从 0 开始，所以显示时 +1)
        for index, account in enumerate(accounts):
            context = await browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
            
            # 传入 index + 1
            await run_account(context, account, index + 1)
            await context.close()
            
            delay = random.randint(15, 25)
            print(f"等待 {delay} 秒...")
            await asyncio.sleep(delay)
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
