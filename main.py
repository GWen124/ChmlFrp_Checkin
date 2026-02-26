import os
import json
import asyncio
import random
from playwright.async_api import async_playwright

ACCOUNTS_JSON = os.environ.get('ACCOUNTS_JSON')

def mask_username(username):
    """账号脱敏"""
    if not username: return "未知账号"
    if len(username) <= 3: return username[0] + "***"
    return username[:3] + "***"

async def log_api_response(response):
    """API 监听"""
    if "qiandao" in response.url and response.status == 200:
        try:
            data = await response.json()
            print(f"\n🎁 [API 监听] 服务器返回数据: {json.dumps(data, ensure_ascii=False)}")
        except:
            pass

async def get_stat_info(page):
    """获取统计信息"""
    print(">>> [信息获取] 尝试读取账户统计...")
    try:
        info_btn = page.get_by_text("签到信息").first
        if await info_btn.count() > 0 and await info_btn.is_visible():
            await info_btn.click()
            await asyncio.sleep(1)
            popover = page.locator(".ant-popover-inner-content, .ant-tooltip-inner, div[role='tooltip']")
            if await popover.count() > 0:
                text = await popover.first.inner_text()
                print("="*30)
                print(f"📊 【账户状态】")
                print(text.strip())
                print("="*30)
    except:
        pass

async def handle_slider(page):
    """处理滑块"""
    try:
        # 增加等待，防止滑块还没加载出来
        await asyncio.sleep(1)
        slider = await page.wait_for_selector('.ant-slider-handle, .nc_iconfont, .drag-btn', timeout=4000)
        if slider:
            print(">>> [滑块] 发现验证码，尝试拖动...")
            box = await slider.bounding_box()
            if box:
                await page.mouse.move(box['x'] + box['width']/2, box['y'] + box['height']/2)
                await page.mouse.down()
                # 模拟人类变速拖动
                await page.mouse.move(box['x'] + 260, box['y'] + random.randint(-5,5), steps=25)
                await page.mouse.up()
                print(">>> [滑块] 拖动完成")
                await asyncio.sleep(2)
    except:
        pass

async def run_one_account(account, context):
    username = account['u']
    password = account['p']
    masked_name = mask_username(username)
    
    if "你的用户名" in username: return

    print(f"\n========== 🟢 正在执行: {masked_name} ==========")
    page = await context.new_page()
    
    # 【重要】反检测：注入 JS 移除 webdriver 属性
    await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    
    page.on("response", log_api_response)

    try:
        # 1. 登录
        print("1. 访问登录页...")
        await page.goto("https://panel.chmlfrp.net/", timeout=45000) # 增加超时时间
        
        # 【关键修改】使用更宽容的等待策略
        print("   等待登录框加载...")
        try:
            # 尝试等待任意输入框出现，或者 Cloudflare 的挑战结束
            await page.wait_for_selector('input', timeout=20000)
        except:
            print("⚠️ 警告: 输入框加载超时，可能遇到了 Cloudflare 盾，尝试截图...")
            await page.screenshot(path=f"debug_loading_{username}.png")
        
        # 使用更通用的选择器，不局限于 name="username"
        await page.fill('input[type="text"]', username)
        await page.fill('input[type="password"]', password)
        
        print("   提交登录...")
        # 尝试点击登录按钮，如果找不到就回车
        login_btn = page.locator('button[type="submit"], button:has-text("登录")')
        if await login_btn.count() > 0:
            await login_btn.first.click()
        else:
            await page.keyboard.press('Enter')
            
        await page.wait_for_load_state('networkidle')
        await asyncio.sleep(3)

        # 2. 跳转首页
        print("2. 进入面板首页...")
        await page.goto("https://panel.chmlfrp.net/home")
        await asyncio.sleep(3)

        # 3. 签到
        print("3. 寻找签到按钮...")
        # 增加对 "已签到" 按钮的检测，避免干等
        signed_btn = page.get_by_text("已签到")
        checkin_btn = page.get_by_text("签到", exact=True)
        
        if await signed_btn.count() > 0:
            print(">>> 检测到【已签到】状态，跳过点击。")
        elif await checkin_btn.count() > 0:
            print(">>> 点击【签到】按钮...")
            await checkin_btn.first.click(force=True)
            await asyncio.sleep(1)
            # 处理可能的弹窗
            try:
                toast = await page.wait_for_selector('.swal2-title, .ant-message', timeout=2000)
                if toast: print(f"🔔 [弹窗] {await toast.inner_text()}")
            except: pass
            
            await handle_slider(page)
        else:
            print(">>> 未找到明显签到按钮。")

        # 4. 统计
        await get_stat_info(page)
        await page.screenshot(path=f"result_{username}.png")

    except Exception as e:
        print(f"❌ 异常: {e}")
        # 保存错误截图，这是排查问题的关键
        await page.screenshot(path=f"error_{username}.png")
    finally:
        await page.close()

async def main():
    if not ACCOUNTS_JSON:
        print("错误: 未设置 ACCOUNTS_JSON")
        return

    accounts = json.loads(ACCOUNTS_JSON)
    async with async_playwright() as p:
        # 【核心修改】启动参数加入反检测
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--disable-blink-features=AutomationControlled', # 移除自动化特征
                '--no-sandbox',
                '--disable-setuid-sandbox'
            ]
        )
        
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            # 使用真实的 User-Agent
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        
        for account in accounts:
            await run_one_account(account, context)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
