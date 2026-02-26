import os
import json
import asyncio
import random
import datetime
from playwright.async_api import async_playwright

ACCOUNTS_JSON = os.environ.get('ACCOUNTS_JSON')

def mask_username(username):
    if not username: return "未知账号"
    if len(username) <= 3: return username[0] + "***"
    return username[:3] + "***"

# 全局状态字典
ACCOUNT_STATUS = {}

def ease_out_quad(x):
    return 1 - (1 - x) * (1 - x)

async def mouse_slide(page, box):
    """仿真鼠标拖动"""
    start_x = box['x'] + box['width'] / 2
    start_y = box['y'] + box['height'] / 2
    await page.mouse.move(start_x, start_y)
    await page.mouse.down()
    
    distance = 260 + random.randint(-5, 15)
    steps = 40
    for i in range(steps):
        t = (i + 1) / steps
        progress = ease_out_quad(t)
        current_x = start_x + (distance * progress)
        await page.mouse.move(current_x, start_y + random.uniform(-2, 2))
        if i > steps - 10: await asyncio.sleep(0.04)
        else: await asyncio.sleep(0.01)
        
    await page.mouse.move(current_x - 3, start_y, steps=5)
    await page.mouse.up()
    print(f"   └── 🖱️ 模拟拖动完成")

async def force_clear_overlays(page):
    """【核心】暴力删除遮挡层"""
    try:
        await page.evaluate("""() => {
            document.querySelectorAll('.geetest_popup_ghost, .geetest_wrap, .geetest_mask').forEach(e => e.remove());
        }""")
    except:
        pass

async def handle_geetest(page):
    """处理极验"""
    print(">>> [验证] 扫描验证码...")
    try:
        radar = page.locator('.geetest_radar_tip')
        if await radar.count() > 0 and await radar.first.is_visible():
            print("   └── 点击验证按钮...")
            await radar.first.click()
            await asyncio.sleep(2)

        slider = await page.wait_for_selector('.geetest_slider_button, .geetest_btn, .ant-slider-handle', timeout=4000)
        if slider:
            print("   └── 发现滑块，开始拖动...")
            box = await slider.bounding_box()
            if box:
                await mouse_slide(page, box)
                await asyncio.sleep(3)
                # 拖动完立刻清除遮挡
                await force_clear_overlays(page)
    except:
        pass

async def log_api_response(response):
    """API 监听"""
    if "qiandao" in response.url or "user/info" in response.url:
        try:
            data = await response.json()
            # 记录关键状态
            if isinstance(data, dict):
                inner = data.get("data", {})
                if isinstance(inner, dict):
                    # 积分
                    if "total_points" in inner:
                        ACCOUNT_STATUS["points"] = inner["total_points"]
                    # 签到状态
                    if inner.get("is_signed_in_today") is True:
                        ACCOUNT_STATUS["signed"] = True
                        print("   ✅ [API] 确认今日已签到")
        except:
            pass

async def run_one_account(account, browser):
    username = account['u']
    password = account['p']
    masked_name = mask_username(username)
    
    if "你的用户名" in username: return

    print(f"\n========== 🟢 正在执行: {masked_name} ==========")
    
    # 重置当前账号状态
    ACCOUNT_STATUS.clear()
    ACCOUNT_STATUS["signed"] = False
    ACCOUNT_STATUS["points"] = "未知"

    context = await browser.new_context(
        viewport={'width': 1920, 'height': 1080},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
    page = await context.new_page()
    await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    page.on("response", log_api_response)

    MAX_RETRIES = 2
    for attempt in range(1, MAX_RETRIES + 1):
        print(f"\n🔄 第 {attempt} 次检查...")
        try:
            # 1. 登录与跳转
            await page.goto("https://panel.chmlfrp.net/", timeout=45000)
            if "/home" not in page.url:
                try:
                    await page.wait_for_selector('input[type="text"]', timeout=10000)
                    await page.fill('input[type="text"]', username)
                    await page.fill('input[type="password"]', password)
                    await page.locator('button[type="submit"]').first.click()
                    await page.wait_for_load_state('networkidle')
                except: pass
            
            if "/home" not in page.url:
                await page.goto("https://panel.chmlfrp.net/home")
                await asyncio.sleep(2)

            # 2. 核心：判断是否需要签到
            # 如果 API 已经返回已签到，直接成功
            if ACCOUNT_STATUS.get("signed"):
                print("   ✅ API 已确认签到状态，无需操作UI。")
                break

            # 3. UI 操作
            # 先清除可能存在的遮挡
            await force_clear_overlays(page)
            
            # 查找按钮：同时查找“签到”和“已签到”
            checkin_btn = page.locator('button').filter(has_text="签到").filter(has_not_text="已签到")
            signed_text = page.get_by_text("已签到")
            
            if await signed_text.count() > 0 and await signed_text.first.is_visible():
                print("   ✅ 页面显示【已签到】")
                ACCOUNT_STATUS["signed"] = True
                break
            
            elif await checkin_btn.count() > 0:
                print("   └── 点击签到按钮...")
                await checkin_btn.first.click(force=True)
                await asyncio.sleep(2)
                await handle_geetest(page)
                # 等待一会儿让 API 更新状态
                await asyncio.sleep(3)
                
                # 如果此时 API 变更为已签到，则成功
                if ACCOUNT_STATUS.get("signed"):
                    print("   ✅ 操作后 API 状态更新为已签到")
                    break
            else:
                print("   ⚠️ 未找到任何签到相关按钮")

        except Exception as e:
            print(f"   ❌ 异常: {str(e)[:100]}")
        
        if attempt < MAX_RETRIES:
            print("   ⏳ 刷新重试...")
            await asyncio.sleep(3)

    # 最终结果汇报
    print("-" * 30)
    if ACCOUNT_STATUS.get("signed"):
        print(f"🎉 账号 {masked_name} 签到成功！")
        print(f"💰 当前积分: {ACCOUNT_STATUS.get('points')}")
        await page.screenshot(path=f"success_{username}.png")
    else:
        print(f"❌ 账号 {masked_name} 签到失败 (或验证码未通过)")
        await page.screenshot(path=f"failed_{username}.png")
    print("-" * 30)
    
    await context.close()

async def main():
    if not ACCOUNTS_JSON:
        print("错误: 未设置 ACCOUNTS_JSON")
        return

    accounts = json.loads(ACCOUNTS_JSON)
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--disable-blink-features=AutomationControlled', '--no-sandbox']
        )
        for account in accounts:
            await run_one_account(account, browser)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
