import os
import json
import asyncio
import random
from playwright.async_api import async_playwright

ACCOUNTS_JSON = os.environ.get('ACCOUNTS_JSON')

def mask_username(username):
    if not username: return "未知账号"
    if len(username) <= 3: return username[0] + "***"
    return username[:3] + "***"

# 全局变量，用于在 API 响应中截获签到状态
CURRENT_ACCOUNT_STATUS = {"signed": False}

async def log_api_response(response):
    """API 监听，同时获取签到状态"""
    if ("qiandao" in response.url or "user/info" in response.url) and response.status == 200:
        try:
            data = await response.json()
            print(f"\n🎁 [API 监听] 接口返回: {json.dumps(data, ensure_ascii=False)}")
            
            # 自动解析是否已签到
            if "data" in data and isinstance(data["data"], dict):
                if data["data"].get("is_signed_in_today") is True:
                    CURRENT_ACCOUNT_STATUS["signed"] = True
                    print("   └── ✅ 检测到 API 状态: 今日已签到")
        except:
            pass

async def handle_geetest(page):
    """
    专门处理极验 (Geetest) 验证码
    """
    print(">>> [验证检测] 正在扫描极验/滑块...")
    try:
        # 1. 检测是否有“点击按钮进行验证” (Radar)
        # 极验有时候先显示一个按钮，点了才出滑块
        radar_btn = page.locator('.geetest_radar_tip, .geetest_radar_btn')
        if await radar_btn.count() > 0 and await radar_btn.first.is_visible():
            print(">>> [极验] 发现点击验证按钮，尝试点击...")
            await radar_btn.first.click()
            await asyncio.sleep(2)

        # 2. 检测滑块按钮
        # 包含常见的极验类名和通用滑块类名
        slider_selector = '.geetest_slider_button, .geetest_btn, .ant-slider-handle, .nc_iconfont'
        slider = await page.wait_for_selector(slider_selector, timeout=4000)
        
        if slider:
            print(">>> [极验] 发现滑块，开始拖动...")
            box = await slider.bounding_box()
            if box:
                # 模拟鼠标移动到滑块中心
                await page.mouse.move(box['x'] + box['width']/2, box['y'] + box['height']/2)
                await page.mouse.down()
                
                # 极验通常需要滑到最右边或者缺口处，这里尝试模拟一个通用距离 (约220-260px)
                # 分段拖动模拟真人
                target_x = box['x'] + 240 + random.randint(-10, 20)
                await page.mouse.move(target_x, box['y'] + random.randint(-5, 5), steps=30)
                
                # 稍微停顿
                await asyncio.sleep(0.5)
                await page.mouse.up()
                print(">>> [极验] 拖动动作完成")
                
                # 等待验证框消失
                await asyncio.sleep(3)
        else:
            print(">>> [验证检测] 未发现明显滑块。")
            
    except Exception as e:
        # 超时说明没验证码，这是好事
        pass

async def safe_click_info(page):
    """
    安全点击“签到信息”，防止被遮挡导致报错
    """
    print(">>> 读取最新积分...")
    try:
        # 尝试等待遮挡层消失 (比如 geetest_popup_ghost)
        # 如果遮挡层还在，说明验证没过，或者卡住了
        for _ in range(3):
            is_blocked = await page.locator('.geetest_popup_ghost, .geetest_wrap').is_visible()
            if is_blocked:
                print("   ⚠️ 检测到验证码遮挡层依然存在，等待 2秒...")
                await asyncio.sleep(2)
            else:
                break

        info_btn = page.get_by_text("签到信息").first
        # 缩短超时时间，如果点不到就放弃，别卡死脚本
        await info_btn.click(timeout=5000) 
        
        await asyncio.sleep(1)
        popover = page.locator(".ant-popover-inner-content, .ant-tooltip-inner, div[role='tooltip']")
        if await popover.count() > 0:
            text = await popover.first.inner_text()
            print("-" * 30)
            print(f"📊 积分统计:\n{text.strip()}")
            print("-" * 30)
            
    except Exception as e:
        print(f"⚠️ 无法读取积分信息 (可能验证码未通过或页面遮挡): {str(e)[:100]}")

async def run_one_account(account, browser):
    username = account['u']
    password = account['p']
    masked_name = mask_username(username)
    
    if "你的用户名" in username: return

    # 重置状态
    CURRENT_ACCOUNT_STATUS["signed"] = False

    print(f"\n========== 🟢 正在执行: {masked_name} ==========")
    
    context = await browser.new_context(
        viewport={'width': 1920, 'height': 1080},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        locale='zh-CN',
        timezone_id='Asia/Shanghai'
    )
    
    page = await context.new_page()
    await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    page.on("response", log_api_response)

    try:
        # 1. 登录
        print("1. 访问登录页...")
        try:
            await page.goto("https://panel.chmlfrp.net/", timeout=45000)
            if "/home" not in page.url:
                await page.wait_for_selector('input[type="text"]', timeout=15000)
                await page.fill('input[type="text"]', username)
                await page.fill('input[type="password"]', password)
                
                # 点击登录
                await page.locator('button:has-text("登录"), button[type="submit"]').first.click()
                await page.wait_for_load_state('networkidle')
                await asyncio.sleep(3)
        except Exception as e:
            print(f"⚠️ 登录过程遇到波动: {str(e)[:50]}")

        # 2. 确认在首页
        if "/home" not in page.url:
            await page.goto("https://panel.chmlfrp.net/home")
            await asyncio.sleep(3)

        # 3. 智能签到
        # 如果 API 已经告诉我们已签到，就没必要去点按钮了，直接跳过，防止触发验证码
        if CURRENT_ACCOUNT_STATUS["signed"]:
            print(">>> ⏩ API 指示今日已签到，跳过点击步骤。")
        else:
            print("3. 寻找签到按钮...")
            # 排除 "已签到" 的按钮
            checkin_btn = page.locator('button').filter(has_text="签到").filter(has_not_text="已签到")
            
            if await checkin_btn.count() > 0:
                print(">>> 点击【签到】按钮...")
                # 使用 force=True 强制点击，防止被透明层拦截
                await checkin_btn.first.click(force=True)
                await asyncio.sleep(2)
                
                # 核心：处理极验验证码
                await handle_geetest(page)
            else:
                # 再次检查页面文本
                if await page.get_by_text("已签到").count() > 0:
                    print(">>> 页面显示【已签到】。")
                else:
                    print(">>> 未找到签到按钮。")

        # 4. 获取积分 (使用防崩溃版)
        await safe_click_info(page)
        
        # 截图留存
        await page.screenshot(path=f"result_{username}.png")

    except Exception as e:
        print(f"❌ 运行异常: {e}")
        await page.screenshot(path=f"error_{username}.png")
    finally:
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
