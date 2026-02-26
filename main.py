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
    """
    【核心升级】监听并打印接口返回的具体内容
    """
    if "qiandao" in response.url and response.status == 200:
        try:
            # 获取接口返回的 JSON 数据
            data = await response.json()
            print(f"\n🎁 [API 监听] 服务器返回数据: {json.dumps(data, ensure_ascii=False)}")
        except:
            pass

async def get_stat_info(page):
    """获取静态统计面板信息"""
    print(">>> [信息获取] 正在读取账户统计数据...")
    try:
        # 尝试点击“签到信息”按钮
        info_btn = page.get_by_text("签到信息").first
        if await info_btn.is_visible():
            await info_btn.click()
            await asyncio.sleep(1)
            
            # 读取弹出的统计信息
            popover = page.locator(".ant-popover-inner-content, .ant-tooltip-inner, div[role='tooltip']")
            if await popover.count() > 0 and await popover.first.is_visible():
                text = await popover.first.inner_text()
                print("="*30)
                print(f"📊 【账户当前状态】")
                print(text.strip())
                print("="*30)
    except Exception as e:
        print(f">>> [信息获取] 暂时无法读取详情: {e}")

async def handle_slider(page):
    """处理滑块验证"""
    try:
        # 检测常见滑块
        slider = await page.wait_for_selector('.ant-slider-handle, .nc_iconfont, .drag-btn', timeout=3000)
        if slider:
            print(">>> [滑块] 检测到验证码，正在自动处理...")
            box = await slider.bounding_box()
            if box:
                await page.mouse.move(box['x'] + box['width']/2, box['y'] + box['height']/2)
                await page.mouse.down()
                # 拖动大约 260px
                await page.mouse.move(box['x'] + 260, box['y'], steps=20)
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
    
    # 注册 API 监听器
    page.on("response", log_api_response)

    try:
        # 1. 登录
        print("1. 登录中...")
        await page.goto("https://panel.chmlfrp.net/")
        await page.fill('input[name="username"]', username)
        await page.fill('input[type="password"]', password)
        await page.keyboard.press('Enter')
        await page.wait_for_load_state('networkidle')
        await asyncio.sleep(2)

        # 2. 跳转首页
        print("2. 进入面板首页...")
        await page.goto("https://panel.chmlfrp.net/home")
        await page.wait_for_load_state('networkidle')
        await asyncio.sleep(2)

        # 3. 执行签到
        print("3. 寻找签到按钮...")
        checkin_btn = page.get_by_text("签到", exact=True).first
        
        if await checkin_btn.is_visible():
            print(">>> 点击【签到】按钮...")
            await checkin_btn.click(force=True)
            
            # 立即检测屏幕上有没有弹出的提示文字 (Toast)
            try:
                # 常见的提示框类名
                toast = await page.wait_for_selector('.swal2-title, .ant-message, .toast-message', timeout=3000)
                if toast:
                    msg = await toast.inner_text()
                    print(f"\n🔔 [页面弹窗] {msg}\n")
            except:
                pass
            
            await handle_slider(page)
            await asyncio.sleep(2)
        else:
            print(">>> 未找到签到按钮，可能今日已签。")

        # 4. 获取最终统计
        await get_stat_info(page)

        # 截图留存
        await page.screenshot(path=f"result_{username}.png")

    except Exception as e:
        print(f"❌ 异常: {e}")
        await page.screenshot(path=f"error_{username}.png")
    finally:
        await page.close()

async def main():
    if not ACCOUNTS_JSON:
        print("错误: 未设置 ACCOUNTS_JSON")
        return

    accounts = json.loads(ACCOUNTS_JSON)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1920, 'height': 1080})
        for account in accounts:
            await run_one_account(account, context)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
