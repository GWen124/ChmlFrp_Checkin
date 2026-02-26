import os
import json
import asyncio
import random
import cv2
import numpy as np
from playwright.async_api import async_playwright

ACCOUNTS_JSON = os.environ.get('ACCOUNTS_JSON')

def mask_username(username):
    if not username: return "未知"
    return username[:3] + "***" if len(username) > 3 else username[0] + "***"

def identify_gap(bg_path):
    """OpenCV 识别拼图缺口"""
    print("   🔍 [视觉] 正在分析缺口距离...")
    try:
        img = cv2.imread(bg_path)
        if img is None: return 210
        # 预处理
        blurred = cv2.GaussianBlur(img, (5, 5), 0)
        canny = cv2.Canny(blurred, 200, 450)
        contours, _ = cv2.findContours(canny, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            # 过滤缺口形状 (40-70px 宽度)
            if 38 < w < 75 and 38 < h < 75 and x > 55:
                print(f"   🎯 [视觉] 目标锁定: X={x}")
                return x
        return 210 # 兜底
    except:
        return 210

async def mouse_slide(page, slider_btn, distance):
    """仿真真人轨迹拖动"""
    box = await slider_btn.bounding_box()
    start_x = box['x'] + box['width'] / 2
    start_y = box['y'] + box['height'] / 2
    
    await page.mouse.move(start_x, start_y)
    await page.mouse.down()
    
    # 模拟加速度
    current = 0
    steps = 40
    for i in range(steps):
        t = (i + 1) / steps
        # 缓动函数
        move = distance * (1 - (1 - t)**2)
        await page.mouse.move(start_x + move, start_y + random.uniform(-2, 2))
        await asyncio.sleep(random.uniform(0.01, 0.02))
        
    await page.mouse.move(start_x + distance + 4, start_y, steps=5) # 过冲
    await asyncio.sleep(0.1)
    await page.mouse.move(start_x + distance, start_y, steps=5) # 回退
    await page.mouse.up()
    print(f"   └── 🖱️ 滑动完成")

async def handle_geetest(page, name=""):
    """处理极验 V4"""
    try:
        # 1. 尝试点击验证按钮
        radar = page.locator('.geetest_radar_tip, .geetest_radar_btn')
        if await radar.count() > 0 and await radar.first.is_visible():
            await radar.first.click()
            await asyncio.sleep(3)

        # 2. 尝试识别并滑动
        slider = await page.wait_for_selector('.geetest_slider_button, .geetest_btn', timeout=3000)
        if slider:
            captcha_box = page.locator('.geetest_window, .geetest_box_wrap').first
            if await captcha_box.is_visible():
                await captcha_box.screenshot(path="captcha.png")
                gap_x = identify_gap("captcha.png")
                await mouse_slide(page, slider, gap_x - 5)
                await asyncio.sleep(4)
            # 暴力清理残留层
            await page.evaluate("document.querySelectorAll('.geetest_popup_ghost, .geetest_wrap').forEach(e => e.remove())")
    except:
        pass

async def run_account(account, browser):
    username, password = account['u'], account['p']
    masked = mask_username(username)
    print(f"\n========== 🟢 执行: {masked} ==========")

    # 独立环境隔离
    context = await browser.new_context(
        viewport={'width': 1920, 'height': 1080},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
    page = await context.new_page()
    # 绕过自动化检测
    await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

    try:
        # 1. 登录流程
        print("   1. 正在登录...")
        await page.goto("https://panel.chmlfrp.net/", timeout=60000)
        
        try:
            await page.wait_for_selector('input[type="text"]', timeout=20000)
            await page.fill('input[type="text"]', username)
            await page.fill('input[type="password"]', password)
            await page.click('button[type="submit"]')
            await asyncio.sleep(2)
            await handle_geetest(page, "登录")
            await page.wait_for_url("**/home", timeout=15000)
            print("   ✅ 登录成功")
        except:
            if "/home" not in page.url:
                print("   🚫 登录超时或失败，跳过此账号。")
                await context.close(); return

        # 2. 签到流程
        print("   2. 执行签到...")
        if "/home" not in page.url: await page.goto("https://panel.chmlfrp.net/home")
        await asyncio.sleep(3)

        if await page.get_by_text("已签到").count() > 0:
            print("   ✅ 今日已签到")
        else:
            checkin_btn = page.locator('button').filter(has_text="签到").filter(has_not_text="已签到").first
            if await checkin_btn.is_visible():
                await checkin_btn.click(force=True)
                await asyncio.sleep(2)
                await handle_geetest(page, "签到")
                await asyncio.sleep(3)
                
                # 再次确认
                if await page.get_by_text("已签到").count() > 0:
                    print("   🎉 签到成功！")
                else:
                    print("   ⚠️ 签到状态未改变")
            else:
                print("   ⚠️ 未找到签到按钮")
        
        await page.screenshot(path=f"result_{username}.png")

    except Exception as e:
        print(f"   ❌ 异常: {str(e)[:100]}")
        await page.screenshot(path=f"error_{username}.png")
    finally:
        await context.close()

async def main():
    if not ACCOUNTS_JSON: return print("错误: 未设置 ACCOUNTS_JSON")
    accounts = json.loads(ACCOUNTS_JSON)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-blink-features=AutomationControlled'])
        for acc in accounts: await run_account(acc, browser)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
