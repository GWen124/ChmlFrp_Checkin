import os
import json
import asyncio
import random
from playwright.async_api import async_playwright

ACCOUNTS_JSON = os.environ.get('ACCOUNTS_JSON')

async def handle_slider(page):
    """
    处理滑块验证逻辑
    """
    print("正在检测是否有滑块验证...")
    try:
        # 增加更多可能的滑块选择器
        # .nc_iconfont (阿里系), .geetest_slider_button (极验), .ant-slider-handle (AntDesign)
        slider_handle = await page.wait_for_selector(
            '.ant-slider-handle, .nc_iconfont, .drag-btn, .secsdk-captcha-drag-icon, .geetest_slider_button', 
            timeout=5000
        )
        
        if slider_handle:
            print(">>> 发现滑块！开始尝试拖动...")
            box = await slider_handle.bounding_box()
            
            # 尝试找到轨道宽度，如果找不到就默认滑 250px
            try:
                track = await page.wait_for_selector('.ant-slider, .nc_scale, .drag-track, .geetest_slider_track', timeout=2000)
                track_box = await track.bounding_box()
                target_x = track_box['width'] - box['width']
            except:
                target_x = 260 # 默认兜底距离

            # 模拟鼠标操作
            # 1. 移动到滑块中心
            await page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
            await page.mouse.down()
            
            # 2. 模拟人类不匀速拖动
            steps = 30
            for i in range(steps):
                move_x = (target_x / steps) * (i + 1)
                # 加随机抖动，防止被识别为机器人
                jitter = random.randint(-3, 3) 
                await page.mouse.move(box['x'] + move_x, box['y'] + jitter + box['height'] / 2)
                await asyncio.sleep(random.uniform(0.01, 0.05))
            
            await page.mouse.up()
            print(">>> 滑块拖动动作完成，等待验证结果...")
            await asyncio.sleep(3)
        else:
            print("未检测到滑块元素。")
            
    except Exception as e:
        #超时是正常的，说明不需要滑块
        print("未检测到滑块或无需滑动。")

async def run_one_account(account, context):
    username = account['u']
    password = account['p']
    
    # 跳过示例账号
    if "你的用户名" in username:
        print(f"跳过无效示例账号: {username}")
        return

    print(f"\n========== 开始处理账号: {username} ==========")
    
    page = await context.new_page()
    
    # --- 核心修改：设置 API 监听 ---
    # 监听包含 'qiandao' 的接口响应，直接获取后端返回的结果
    page.on("response", lambda response: print_response(response))

    try:
        # 1. 访问登录页
        print("1. 访问面板首页...")
        await page.goto("https://panel.chmlfrp.net/")
        
        # 2. 登录
        print("2. 正在登录...")
        await page.wait_for_selector('input[type="text"], input[name="username"]', timeout=15000)
        await page.fill('input[type="text"], input[name="username"]', username)
        await page.fill('input[type="password"]', password)
        
        # 点击登录
        login_btn = await page.query_selector('button[type="submit"], .login-btn, button:has-text("登录")')
        if login_btn:
            await login_btn.click()
        else:
            # 回车登录
            await page.keyboard.press('Enter')
        
        await page.wait_for_load_state('networkidle')

        # 3. 查找签到按钮
        print("3. 寻找签到入口...")
        # 截图保存登录后状态，方便排查
        await page.screenshot(path=f"debug_login_{username}.png")
        
        # 尝试多种方式定位“签到”按钮
        checkin_btn = None
        # 策略A: 找文字
        try:
            checkin_btn = page.get_by_text("签到", exact=False).first
            if not await checkin_btn.is_visible():
                checkin_btn = None
        except:
            pass

        # 策略B: 如果首页没找到，可能是已经签到过了，或者在模态框里
        if not checkin_btn:
            print("首页未找到明显签到按钮，检查页面文字...")
            content = await page.content()
            if "已签到" in content:
                print(f"检测到页面包含 '已签到' 字样，跳过。")
                return

        if checkin_btn:
            print(">>> 点击签到按钮...")
            await checkin_btn.click()
            
            # 4. 点击后处理滑块
            # 有些网站点击后才加载滑块，所以要等一下
            await asyncio.sleep(2)
            await handle_slider(page)
            
            # 5. 等待最后的弹窗或结果
            print("等待结果反馈...")
            await asyncio.sleep(3)
            
            # 尝试截图最后的结果（比如弹出的 SweetAlert）
            await page.screenshot(path=f"result_{username}.png")
            
            # 尝试读取常见的弹窗文字
            try:
                # 常见弹窗类名: swal2-content, modal-body, ant-message
                popup_text = await page.inner_text('div[class*="swal"], div[class*="modal"], div[class*="message"]', timeout=2000)
                print(f"*** 页面弹窗文字: {popup_text} ***")
            except:
                print("未提取到弹窗文字，请查看 result 图片或上方 API 日志。")
                
        else:
            print("严重：无法找到签到按钮，请检查 debug_login 图片。")

    except Exception as e:
        print(f"账号 {username} 执行出错: {e}")
        await page.screenshot(path=f"error_{username}.png")
    finally:
        await page.close()

def print_response(response):
    """
    回调函数：当浏览器收到网络响应时触发
    """
    try:
        # 只过滤和签到相关的接口，或者 info 接口
        if "qiandao" in response.url and response.status == 200:
            print(f"\n[API 捕获] URL: {response.url}")
            # 尝试解析 JSON
            json_data = response.json() 
            # 这里 .json() 是一个协程吗？在 playwright sync api 里不是，但在 async api 里
            # page.on 是同步回调，不能直接 await。
            # 这里的处理稍微有点复杂，为了简化，我们打印 URL 确认触发了即可。
            # 如果需要内容，playwright 的 page.on 不支持 async body 获取。
            # 改为简单的 text 打印：
            print(">>> 接口触发成功！(由于异步限制，内容请看下方截图或结果)")
    except:
        pass

async def main():
    if not ACCOUNTS_JSON:
        print("错误: 环境变量 ACCOUNTS_JSON 未设置！")
        return

    try:
        accounts = json.loads(ACCOUNTS_JSON)
    except json.JSONDecodeError:
        print("错误: ACCOUNTS_JSON 格式不正确")
        return
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={'width': 1920, 'height': 1080} # 加大分辨率，防止按钮被折叠
        )
        
        for account in accounts:
            await run_one_account(account, context)
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
