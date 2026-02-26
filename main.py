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

async def log_api_response(response):
    """API 监听"""
    # 监听签到接口和用户信息接口
    if ("qiandao" in response.url or "user/info" in response.url) and response.status == 200:
        try:
            data = await response.json()
            print(f"\n🎁 [API 监听] 接口返回: {json.dumps(data, ensure_ascii=False)}")
        except:
            pass

async def handle_slider(page):
    """处理滑块"""
    try:
        await asyncio.sleep(1)
        # 增加更多滑块选择器
        slider = await page.wait_for_selector(
            '.ant-slider-handle, .nc_iconfont, .drag-btn, .geetest_slider_button', 
            timeout=4000
        )
        if slider:
            print(">>> [滑块] 发现验证码，尝试拖动...")
            box = await slider.bounding_box()
            if box:
                await page.mouse.move(box['x'] + box['width']/2, box['y'] + box['height']/2)
                await page.mouse.down()
                # 拖动距离稍微随机一点
                await page.mouse.move(box['x'] + 260 + random.randint(0, 10), box['y'] + random.randint(-5,5), steps=25)
                await page.mouse.up()
                print(">>> [滑块] 拖动完成")
                await asyncio.sleep(3)
    except:
        pass # 没有滑块是好消息，直接跳过

async def run_one_account(account, browser):
    username = account['u']
    password = account['p']
    masked_name = mask_username(username)
    
    if "你的用户名" in username: return

    print(f"\n========== 🟢 正在执行: {masked_name} ==========")
    
    # 【核心修复】每人都用一个全新的 context，互不干扰
    context = await browser.new_context(
        viewport={'width': 1920, 'height': 1080},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        # 禁用自动化特征
        locale='zh-CN',
        timezone_id='Asia/Shanghai'
    )
    
    # 反检测注入
    page = await context.new_page()
    await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    
    page.on("response", log_api_response)

    try:
        # 1. 登录
        print("1. 访问登录页...")
        await page.goto("https://panel.chmlfrp.net/", timeout=60000)
        
        # 判断是否已经登录（防止 cookie 残留或自动登录）
        if "/home" in page.url:
            print(">>> 检测到已在首页，跳过登录步骤...")
        else:
            print("   等待登录框...")
            try:
                # 优先等待输入框
                await page.wait_for_selector('input[type="text"]', timeout=20000)
                await page.fill('input[type="text"]', username)
                await page.fill('input[type="password"]', password)
                
                print("   点击登录...")
                # 尝试点击登录按钮
                login_btn = page.locator('button:has-text("登录"), button[type="submit"]')
                if await login_btn.count() > 0:
                    await login_btn.first.click()
                else:
                    await page.keyboard.press('Enter')
                
                await page.wait_for_load_state('networkidle')
                await asyncio.sleep(3)
            except Exception as e:
                print(f"⚠️ 登录环节异常 (可能是已登录或被盾): {str(e)[:100]}")

        # 2. 强制确认在首页
        if "/home" not in page.url:
            print("2. 跳转到面板首页...")
            await page.goto("https://panel.chmlfrp.net/home")
            await asyncio.sleep(3)

        # 3. 签到
        print("3. 寻找签到按钮...")
        # 优先找“签到”按钮，排除“已签到”
        checkin_btn = page.locator('button:has-text("签到")').filter(has_not_text="已签到")
        already_signed = page.get_by_text("已签到")
        
        if await already_signed.count() > 0:
             print(">>> 状态：今日已签到 (页面包含'已签到'字样)")
        elif await checkin_btn.count() > 0:
            print(">>> 点击【签到】按钮...")
            # 监听是否有弹窗文本
            async def check_alert(dialog):
                print(f"🔔 [系统弹窗] {dialog.message}")
                await dialog.accept()
            page.on("dialog", check_alert)
            
            await checkin_btn.first.click(force=True)
            await asyncio.sleep(2)
            
            # 检查是否有 Toast 提示
            toast = page.locator('.ant-message-notice, .swal2-container')
            if await toast.count() > 0 and await toast.first.is_visible():
                print(f"🔔 [页面提示] {await toast.first.inner_text()}")
            
            await handle_slider(page)
        else:
            print(">>> 未找到可点击的签到按钮。")

        # 4. 获取积分信息
        print(">>> 读取最新积分...")
        # 尝试刷新一下页面确保数据最新
        # await page.reload() 
        # await asyncio.sleep(2)
        
        info_btn = page.get_by_text("签到信息").first
        if await info_btn.count() > 0:
            await info_btn.click()
            await asyncio.sleep(1)
            popover = page.locator(".ant-popover-inner-content, .ant-tooltip-inner, div[role='tooltip']")
            if await popover.count() > 0:
                print("-" * 30)
                print(f"📊 {masked_name} 数据统计:")
                print((await popover.first.inner_text()).strip())
                print("-" * 30)

        await page.screenshot(path=f"result_{username}.png")

    except Exception as e:
        print(f"❌ 严重错误: {e}")
        await page.screenshot(path=f"error_{username}.png")
    finally:
        # 【关键】关闭当前账号的 context，清除 Cookies
        await context.close()

async def main():
    if not ACCOUNTS_JSON:
        print("错误: 未设置 ACCOUNTS_JSON")
        return

    accounts = json.loads(ACCOUNTS_JSON)
    async with async_playwright() as p:
        # 启动浏览器
        browser = await p.chromium.launch(
            headless=True,
            args=['--disable-blink-features=AutomationControlled', '--no-sandbox']
        )
        
        for account in accounts:
            await run_one_account(account, browser)
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
