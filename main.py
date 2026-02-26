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

async def get_stat_info(page):
    """
    专门用于获取并打印截图中的【统计信息】
    """
    print(">>> [信息获取] 尝试获取详细签到统计...")
    try:
        # 1. 寻找并点击“签到信息”按钮
        # 按钮通常在“签到”按钮旁边
        info_btn = page.get_by_text("签到信息").first
        
        if await info_btn.is_visible():
            await info_btn.click()
            await asyncio.sleep(1) # 等待弹窗动画
            
            # 2. 寻找弹出的“统计信息”框
            # 这里的逻辑是：找到包含“上次签到时间”文字的容器
            stat_panel = page.locator("div, span, p").filter(has_text="上次签到时间").last
            
            # 获取整个卡片的文本
            # 既然 filter 到了具体行，我们向上找父级容器以获取完整信息，或者直接读取整个页面的相关文本
            # 更稳妥的方法：等待包含“统计信息”的元素出现
            popover = page.locator("div[role='tooltip'], .ant-popover, .ant-tooltip").filter(has_text="统计信息")
            
            content = ""
            if await popover.count() > 0 and await popover.first.is_visible():
                content = await popover.first.inner_text()
            elif await stat_panel.is_visible():
                # 如果找不到 tooltip 类名，就直接读取包含数据的父级
                content = await stat_panel.locator("xpath=..").inner_text()
            
            if content:
                print("\n" + "="*30)
                print(f"📊 【签到统计数据】")
                print("-" * 30)
                # 格式化输出，去除多余空行
                lines = [line.strip() for line in content.split('\n') if line.strip()]
                for line in lines:
                    print(f"   {line}")
                print("="*30 + "\n")
                return True
            else:
                print(">>> [信息获取] 未能提取到文本内容")
    except Exception as e:
        print(f">>> [信息获取] 获取统计信息失败: {e}")
    return False

async def handle_slider(page):
    """处理滑块验证"""
    print(">>> [滑块检测] 正在扫描页面是否有滑块...")
    try:
        slider_handle = await page.wait_for_selector(
            '.ant-slider-handle, .nc_iconfont, .drag-btn, .secsdk-captcha-drag-icon, .geetest_slider_button', 
            timeout=3000
        )
    except:
        print(">>> [滑块检测] 未检测到滑块。")
        return

    if slider_handle:
        print(">>> [滑块操作] 发现滑块！开始拖动...")
        try:
            box = await slider_handle.bounding_box()
            track_width = 260
            try:
                track = await page.query_selector('.ant-slider, .nc_scale, .drag-track')
                if track:
                    track_box = await track.bounding_box()
                    track_width = track_box['width'] - box['width']
            except:
                pass

            start_x = box['x'] + box['width'] / 2
            start_y = box['y'] + box['height'] / 2
            await page.mouse.move(start_x, start_y)
            await page.mouse.down()
            
            steps = 25
            for i in range(steps):
                progress = (i + 1) / steps
                progress = 1 - (1 - progress) * (1 - progress)
                move_x = track_width * progress
                await page.mouse.move(start_x + move_x, start_y + random.randint(-2, 2))
                await asyncio.sleep(random.uniform(0.02, 0.05))
            
            await page.mouse.up()
            print(">>> [滑块操作] 拖动完成。")
            await asyncio.sleep(2)
        except Exception as e:
            print(f">>> [滑块错误] {e}")

async def run_one_account(account, context):
    username = account['u']
    password = account['p']
    masked_name = mask_username(username)
    
    if "你的用户名" in username: return

    print(f"\n========== 🟢 开始处理账号: {masked_name} ==========")
    page = await context.new_page()
    
    # 监听 API 确认实际签到请求
    page.on("response", lambda r: print(f"✅ [API] 触发: {r.url}") if "qiandao" in r.url and r.status==200 else None)

    try:
        # 1. 登录
        print("1. 登录中...")
        await page.goto("https://panel.chmlfrp.net/")
        await page.wait_for_selector('input[name="username"]', timeout=15000)
        await page.fill('input[name="username"]', username)
        await page.fill('input[type="password"]', password)
        await page.keyboard.press('Enter')
        await page.wait_for_load_state('networkidle')
        await asyncio.sleep(2)

        # 2. 强制跳转首页
        print("2. 进入面板首页...")
        await page.goto("https://panel.chmlfrp.net/home")
        await page.wait_for_load_state('networkidle')
        await asyncio.sleep(2)

        # 3. 执行签到 (先尝试点签到)
        print("3. 尝试签到...")
        checkin_btn = page.get_by_text("签到", exact=True)
        if await checkin_btn.count() > 0 and await checkin_btn.first.is_visible():
            await checkin_btn.first.click(force=True)
            await asyncio.sleep(1)
            await handle_slider(page) # 处理可能的滑块
            await asyncio.sleep(2) # 等待结果生效
        else:
            print(">>> 未找到直接的“签到”按钮，可能已签到或布局不同。")

        # 4. 【核心新增】获取并打印截图里的统计信息
        # 无论刚才签到是否成功，都去点一下“签到信息”看看数据
        await get_stat_info(page)

        # 截图留证
        await page.screenshot(path=f"result_{username}.png")

    except Exception as e:
        print(f"❌ 错误: {e}")
        await page.screenshot(path=f"error_{username}.png")
    finally:
        await page.close()

async def main():
    if not ACCOUNTS_JSON:
        print("错误: 环境变量 ACCOUNTS_JSON 未设置")
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
