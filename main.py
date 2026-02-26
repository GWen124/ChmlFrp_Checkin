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

# 缓动函数
def ease_out_quad(x):
    return 1 - (1 - x) * (1 - x)

async def mouse_slide(page, box):
    """仿真鼠标拖动"""
    start_x = box['x'] + box['width'] / 2
    start_y = box['y'] + box['height'] / 2
    
    await page.mouse.move(start_x, start_y)
    await page.mouse.down()
    
    # 调整距离：极验通常是 slide-to-end，距离通常在 250-270 之间
    distance = 260 + random.randint(-5, 15)
    steps = 50
    
    for i in range(steps):
        t = (i + 1) / steps
        progress = ease_out_quad(t)
        current_x = start_x + (distance * progress)
        jitter_y = random.uniform(-3, 3) # 加大一点抖动
        current_y = start_y + jitter_y
        
        # 模拟中间卡顿
        if i == 30: await asyncio.sleep(0.1)
        
        if i > steps - 10:
             await asyncio.sleep(random.uniform(0.04, 0.06))
        else:
             await asyncio.sleep(random.uniform(0.008, 0.015))
             
        await page.mouse.move(current_x, current_y)

    # 模拟修正回退
    await page.mouse.move(current_x - 5, start_y, steps=10)
    await asyncio.sleep(0.2)
    await page.mouse.up()
    print(f"   └── 🖱️ 模拟拖动完成")

async def handle_geetest(page):
    """处理极验"""
    print(">>> [验证] 扫描验证码...")
    try:
        # 点击验证按钮
        radar = page.locator('.geetest_radar_tip, .geetest_radar_btn')
        if await radar.count() > 0 and await radar.first.is_visible():
            print("   └── 点击验证按钮...")
            await radar.first.click()
            await asyncio.sleep(2)

        # 处理滑块
        slider = await page.wait_for_selector(
            '.geetest_slider_button, .geetest_btn, .ant-slider-handle, .nc_iconfont', 
            timeout=4000
        )
        if slider:
            print("   └── 发现滑块，开始拖动...")
            box = await slider.bounding_box()
            if box:
                await mouse_slide(page, box)
                await asyncio.sleep(4)
    except:
        pass

async def check_sign_status(page):
    """
    检查签到状态
    返回: (是否成功, 详细文本)
    """
    try:
        # 1. 检查 API 监听 (如果有)
        # 2. 检查页面文本
        info_btn = page.get_by_text("签到信息").first
        if await info_btn.is_visible():
            # 必须使用 force=True，因为可能被验证码遮挡
            await info_btn.click(force=True)
            await asyncio.sleep(1)
            
            popover = page.locator(".ant-popover-inner-content, .ant-tooltip-inner, div[role='tooltip']")
            if await popover.count() > 0:
                text = await popover.first.inner_text()
                
                # 获取今天的日期字符串 (e.g., "2026-02-26")
                # 注意：GitHub Actions 时区可能是 UTC，这里简单匹配日期
                today_str = datetime.datetime.now().strftime("%Y-%m-%d")
                
                # 简单判断：如果包含今天的日期，认为成功
                # 注意：你需要根据服务器时区调整，这里假设服务器也是 UTC 或者脚本能匹配上
                # 更稳妥的是看 "累计签到积分" 是否变化，但这里我们只看日期
                if today_str in text:
                    return True, text
                
                # 如果没匹配上今天，尝试匹配 API 返回的 Last sign in (如果有)
                # 或者检查是否只差几小时（时区问题）
                # 这里简单返回 False，触发重试
                return False, text
                
        return False, "未获取到弹窗信息"
    except Exception as e:
        return False, str(e)

async def run_one_account(account, browser):
    username = account['u']
    password = account['p']
    masked_name = mask_username(username)
    
    if "你的用户名" in username: return

    print(f"\n========== 🟢 正在执行: {masked_name} ==========")
    
    context = await browser.new_context(
        viewport={'width': 1920, 'height': 1080},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
    page = await context.new_page()
    await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

    # === 最大重试次数 ===
    MAX_RETRIES = 3
    
    for attempt in range(1, MAX_RETRIES + 1):
        print(f"\n🔄 第 {attempt} 次尝试...")
        try:
            # 1. 登录 (只在第一次或需要时执行，简化逻辑直接每次确保在首页)
            await page.goto("https://panel.chmlfrp.net/", timeout=45000)
            
            if "/home" not in page.url:
                try:
                    await page.wait_for_selector('input[type="text"]', timeout=10000)
                    await page.fill('input[type="text"]', username)
                    await page.fill('input[type="password"]', password)
                    await page.locator('button:has-text("登录"), button[type="submit"]').first.click()
                    await page.wait_for_load_state('networkidle')
                    await asyncio.sleep(3)
                except:
                    pass # 可能已经登录

            if "/home" not in page.url:
                await page.goto("https://panel.chmlfrp.net/home")
                await asyncio.sleep(3)

            # 2. 尝试签到
            # 检查是否已签到
            if await page.get_by_text("已签到").count() > 0:
                 print("   ✅ 页面已显示【已签到】")
                 success = True
            else:
                checkin_btn = page.locator('button').filter(has_text="签到").filter(has_not_text="已签到")
                if await checkin_btn.count() > 0:
                    print("   └── 点击签到...")
                    await checkin_btn.first.click(force=True)
                    await asyncio.sleep(2)
                    await handle_geetest(page)
                    await asyncio.sleep(2)
                else:
                    print("   ⚠️ 未找到签到按钮")

            # 3. 验证结果
            success, info_text = await check_sign_status(page)
            
            # 获取当前 UTC 日期和 +8 时区日期
            utc_now = datetime.datetime.utcnow()
            cn_now = utc_now + datetime.timedelta(hours=8)
            date_str = cn_now.strftime("%Y-%m-%d")
            
            print("-" * 30)
            print(f"📊 检查结果 (匹配日期: {date_str}):\n{info_text.strip()}")
            print("-" * 30)

            # 宽松判定：如果文本包含今天的日期(CN)，或者包含“已签到”
            if date_str in info_text or "已签到" in info_text or success:
                print(f"✅ 账号 {masked_name} 签到成功！")
                await page.screenshot(path=f"success_{username}.png")
                break # 成功，跳出重试循环
            else:
                print(f"❌ 似乎未成功 (日期不匹配)。准备重试...")
                if attempt == MAX_RETRIES:
                     print("🚫 达到最大重试次数，放弃。")
                     await page.screenshot(path=f"failed_{username}.png")

        except Exception as e:
            print(f"❌ 异常: {e}")
        
        # 重试前刷新页面
        if attempt < MAX_RETRIES:
            print("⏳ 等待 5 秒后刷新页面重试...")
            await asyncio.sleep(5)
    
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
