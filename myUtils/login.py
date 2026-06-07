import asyncio
import base64
import sqlite3

from playwright.async_api import async_playwright

from myUtils.auth import check_cookie
from utils.base_social_media import set_init_script
import uuid
from pathlib import Path
from conf import BASE_DIR, LOCAL_CHROME_HEADLESS, LOCAL_CHROME_PATH

# 统一获取浏览器启动配置（防风控+引入本地浏览器）
def get_browser_options():
    options = {
        'headless': LOCAL_CHROME_HEADLESS,
        'args': [
            '--disable-blink-features=AutomationControlled',  # 核心防爬屏蔽：去掉 window.navigator.webdriver 标签
            '--lang=zh-CN',
            '--disable-infobars',
            '--start-maximized'
        ]
    }
    # 如果用户在 conf.py 里配置了本地 Chrome，就用本地的，这样成功率极高
    if LOCAL_CHROME_PATH:
        options['executable_path'] = LOCAL_CHROME_PATH

    return options


def get_visible_browser_options():
    """获取可见浏览器配置，用于弹窗登录模式。"""
    options = get_browser_options()
    options['headless'] = False
    # 替换 --start-maximized，避免窗口在 Windows 下自动最小化到任务栏
    options['args'] = [
        '--disable-blink-features=AutomationControlled',
        '--lang=zh-CN',
        '--disable-infobars',
        '--window-size=1280,900',
        '--window-position=100,50',
    ]
    return options


async def _browser_login_save_and_verify(platform_type, id, status_queue, account_id,
                                          page, context, browser):
    """弹窗登录通用流程：保存 cookie → 验证有效性 → 写入数据库 → 关闭浏览器。"""
    uuid_v1 = uuid.uuid1()
    cookies_dir = Path(BASE_DIR / "cookiesFile")
    cookies_dir.mkdir(exist_ok=True)
    cookie_file = f"{uuid_v1}.json"
    await context.storage_state(path=cookies_dir / cookie_file)

    result = await check_cookie(platform_type, cookie_file)
    if not result:
        status_queue.put("500")
        await page.close()
        await context.close()
        await browser.close()
        return

    await page.close()
    await context.close()
    await browser.close()

    if save_login_account(platform_type, cookie_file, id, status_queue, account_id):
        status_queue.put("200")


async def safe_goto(page, url):
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        # Some creator sites abort the initial navigation while redirecting into
        # their login shell. If a document still loaded, continue and let the
        # selector waits below decide whether the page is usable.
        if page.url == "about:blank":
            raise e


async def send_qr_from_locator(locator, status_queue):
    await locator.wait_for(state="visible", timeout=30000)
    try:
        src = await locator.get_attribute("src")
        if src and src.startswith("data:image"):
            status_queue.put(src)
            return src
    except Exception:
        pass

    image_bytes = await locator.screenshot(type="png")
    data_url = "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")
    status_queue.put(data_url)
    return data_url

def save_login_account(platform_type, cookie_file, user_name, status_queue, account_id=None):
    with sqlite3.connect(Path(BASE_DIR / "db" / "database.db")) as conn:
        cursor = conn.cursor()
        old_cookie_file = None

        if account_id is not None:
            cursor.execute("SELECT type, filePath FROM user_info WHERE id = ?", (account_id,))
            row = cursor.fetchone()
            if row is None:
                status_queue.put("500")
                print(f"❌ 未找到需要重新连接的账号: {account_id}")
                return False
            if int(row[0]) != int(platform_type):
                status_queue.put("500")
                print(f"❌ 重新连接账号平台不匹配: account_id={account_id}, expect={row[0]}, actual={platform_type}")
                return False
            old_cookie_file = row[1]

            cursor.execute(
                '''
                UPDATE user_info
                SET type = ?, filePath = ?, userName = ?, status = ?
                WHERE id = ?
                ''',
                (platform_type, cookie_file, user_name, 1, account_id)
            )
        else:
            cursor.execute(
                '''
                INSERT INTO user_info (type, filePath, userName, status)
                VALUES (?, ?, ?, ?)
                ''',
                (platform_type, cookie_file, user_name, 1)
            )

        conn.commit()
        print("✅ 用户状态已记录")

        if old_cookie_file and old_cookie_file != cookie_file:
            old_path = Path(BASE_DIR / "cookiesFile" / old_cookie_file)
            try:
                if old_path.exists():
                    old_path.unlink()
                    print(f"✅ 旧 Cookie 文件已删除: {old_path}")
            except Exception as e:
                print(f"⚠️ 删除旧 Cookie 文件失败: {e}")

        return True


# 抖音登录 — 弹窗模式
async def douyin_cookie_gen(id, status_queue, account_id=None):
    url_changed_event = asyncio.Event()

    async def on_url_change():
        current = page.url
        if current != original_url and 'login' not in current.lower():
            url_changed_event.set()

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(**get_visible_browser_options())
        context = await browser.new_context()
        context = await set_init_script(context)
        page = await context.new_page()
        await safe_goto(page, "https://creator.douyin.com/")

        # 抢焦点 + 等待页面初始加载完成
        await page.bring_to_front()
        await page.wait_for_timeout(3000)

        # 告诉前端浏览器已打开，用户可自由选择登录方式
        status_queue.put("BROWSER_OPENED")

        # 记录稳定后的 URL，只监听真正的登录成功跳转（离开登录页）
        original_url = page.url

        page.on('framenavigated',
                lambda frame: asyncio.create_task(on_url_change()) if frame == page.main_frame else None)
        try:
            await asyncio.wait_for(url_changed_event.wait(), timeout=300)
            print("✅ 抖音登录成功，页面已跳转")
        except asyncio.TimeoutError:
            print("❌ 抖音登录超时")
            status_queue.put("500")
            await page.close()
            await context.close()
            await browser.close()
            return

        await _browser_login_save_and_verify(3, id, status_queue, account_id,
                                              page, context, browser)


# 视频号登录
async def get_tencent_cookie(id,status_queue,account_id=None):
    url_changed_event = asyncio.Event()
    async def on_url_change():
        # 检查是否是主框架的变化
        if page.url != original_url:
            url_changed_event.set()

    async with async_playwright() as playwright:
        options = get_browser_options()
        # Make sure to run headed.
        browser = await playwright.chromium.launch(**options)
        # Setup context however you like.
        context = await browser.new_context()  # Pass any options
        # Pause the page, and start recording manually.
        context = await set_init_script(context)
        page = await context.new_page()
        await safe_goto(page, "https://channels.weixin.qq.com")
        original_url = page.url

        # 监听页面的 'framenavigated' 事件，只关注主框架的变化
        page.on('framenavigated',
                lambda frame: asyncio.create_task(on_url_change()) if frame == page.main_frame else None)

        # 等待 iframe 出现（最多等 60 秒）
        iframe_locator = page.frame_locator("iframe").first

        # 获取 iframe 中的第一个 img 元素
        img_locator = iframe_locator.get_by_role("img").first

        src = await send_qr_from_locator(img_locator, status_queue)
        print("✅ 图片地址:", src)

        try:
            # 等待 URL 变化或超时
            await asyncio.wait_for(url_changed_event.wait(), timeout=200)  # 最多等待 200 秒
            print("监听页面跳转成功")
        except asyncio.TimeoutError:
            status_queue.put("500")
            print("监听页面跳转超时")
            await page.close()
            await context.close()
            await browser.close()
            return None
        uuid_v1 = uuid.uuid1()
        print(f"UUID v1: {uuid_v1}")
        # 确保cookiesFile目录存在
        cookies_dir = Path(BASE_DIR / "cookiesFile")
        cookies_dir.mkdir(exist_ok=True)
        await context.storage_state(path=cookies_dir / f"{uuid_v1}.json")
        result = await check_cookie(2,f"{uuid_v1}.json")
        if not result:
            status_queue.put("500")
            await page.close()
            await context.close()
            await browser.close()
            return None
        await page.close()
        await context.close()
        await browser.close()

        if save_login_account(2, f"{uuid_v1}.json", id, status_queue, account_id):
            status_queue.put("200")

# 快手登录
async def get_ks_cookie(id,status_queue,account_id=None):
    url_changed_event = asyncio.Event()
    async def on_url_change():
        # 检查是否是主框架的变化
        if page.url != original_url:
            url_changed_event.set()
    async with async_playwright() as playwright:
        options = get_browser_options()
        # Make sure to run headed.
        browser = await playwright.chromium.launch(**options)
        # Setup context however you like.
        context = await browser.new_context()  # Pass any options
        context = await set_init_script(context)
        # Pause the page, and start recording manually.
        page = await context.new_page()
        await safe_goto(page, "https://cp.kuaishou.com")

        # 定位并点击“立即登录”按钮（类型为 link）
        await page.get_by_role("link", name="立即登录").click()
        await page.get_by_text("扫码登录").click()
        img_locator = page.get_by_role("img", name="qrcode")
        src = await send_qr_from_locator(img_locator, status_queue)
        original_url = page.url
        print("✅ 图片地址:", src)
        # 监听页面的 'framenavigated' 事件，只关注主框架的变化
        page.on('framenavigated',
                lambda frame: asyncio.create_task(on_url_change()) if frame == page.main_frame else None)

        try:
            # 等待 URL 变化或超时
            await asyncio.wait_for(url_changed_event.wait(), timeout=200)  # 最多等待 200 秒
            print("监听页面跳转成功")
        except asyncio.TimeoutError:
            status_queue.put("500")
            print("监听页面跳转超时")
            await page.close()
            await context.close()
            await browser.close()
            return None
        uuid_v1 = uuid.uuid1()
        print(f"UUID v1: {uuid_v1}")
        # 确保cookiesFile目录存在
        cookies_dir = Path(BASE_DIR / "cookiesFile")
        cookies_dir.mkdir(exist_ok=True)
        await context.storage_state(path=cookies_dir / f"{uuid_v1}.json")
        result = await check_cookie(4, f"{uuid_v1}.json")
        if not result:
            status_queue.put("500")
            await page.close()
            await context.close()
            await browser.close()
            return None
        await page.close()
        await context.close()
        await browser.close()

        if save_login_account(4, f"{uuid_v1}.json", id, status_queue, account_id):
            status_queue.put("200")

# 小红书登录 — 弹窗模式
async def xiaohongshu_cookie_gen(id, status_queue, account_id=None):
    url_changed_event = asyncio.Event()

    async def on_url_change():
        current = page.url
        if current != original_url and 'login' not in current.lower():
            url_changed_event.set()

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(**get_visible_browser_options())
        context = await browser.new_context()
        context = await set_init_script(context)
        page = await context.new_page()
        await safe_goto(page, "https://creator.xiaohongshu.com/")

        # 抢焦点 + 等待页面初始加载完成
        await page.bring_to_front()
        await page.wait_for_timeout(3000)

        # 切换到登录方式选择界面（扫码 / 手机号等），让用户自行选择
        try:
            switch_btn = page.locator('img.css-wemwzq')
            if await switch_btn.count() > 0:
                await switch_btn.first.click()
                await page.wait_for_timeout(500)
        except Exception:
            pass

        # 记录稳定后的 URL，只监听真正的登录成功跳转（离开登录页）
        original_url = page.url

        # 告诉前端浏览器已打开
        status_queue.put("BROWSER_OPENED")

        page.on('framenavigated',
                lambda frame: asyncio.create_task(on_url_change()) if frame == page.main_frame else None)
        try:
            await asyncio.wait_for(url_changed_event.wait(), timeout=300)
            print("✅ 小红书登录成功，页面已跳转")
        except asyncio.TimeoutError:
            print("❌ 小红书登录超时")
            status_queue.put("500")
            await page.close()
            await context.close()
            await browser.close()
            return

        await _browser_login_save_and_verify(1, id, status_queue, account_id,
                                              page, context, browser)

# B站登录 — 弹窗模式
async def bilibili_cookie_gen(id, status_queue, account_id=None):
    url_changed_event = asyncio.Event()

    async def on_url_change():
        current = page.url
        if current != original_url and 'login' not in current.lower():
            url_changed_event.set()

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(**get_visible_browser_options())
        context = await browser.new_context()
        context = await set_init_script(context)
        page = await context.new_page()
        await safe_goto(page, "https://member.bilibili.com/")

        # 抢焦点 + 等待页面初始加载完成
        await page.bring_to_front()
        await page.wait_for_timeout(3000)

        # 如果页面停留在登录页，点击"登录"按钮展开登录弹窗
        try:
            login_btn = page.locator('span:has-text("登录")').first
            if await login_btn.count() > 0 and await login_btn.is_visible():
                await login_btn.click()
                await page.wait_for_timeout(2000)
        except Exception:
            pass

        # B站登录弹窗默认显示"微信登录"扫码页，切换到"短信登录"让用户看到输入框
        try:
            sms_tab = page.locator('text="短信登录"').first
            if await sms_tab.count() > 0 and await sms_tab.is_visible():
                await sms_tab.click()
                await page.wait_for_timeout(500)
        except Exception:
            pass

        # 记录稳定后的 URL
        original_url = page.url

        # 告诉前端浏览器已打开
        status_queue.put("BROWSER_OPENED")

        page.on('framenavigated',
                lambda frame: asyncio.create_task(on_url_change()) if frame == page.main_frame else None)
        try:
            await asyncio.wait_for(url_changed_event.wait(), timeout=300)
            print("✅ B站登录成功，页面已跳转")
        except asyncio.TimeoutError:
            # URL 未跳转，再检查是否已经登录
            try:
                if await page.locator('a[href*="space.bilibili.com"]').count() > 0:
                    print("✅ B站登录成功，检测到用户信息")
                else:
                    print("❌ B站登录超时")
                    status_queue.put("500")
                    await page.close()
                    await context.close()
                    await browser.close()
                    return
            except Exception:
                print("❌ B站登录超时")
                status_queue.put("500")
                await page.close()
                await context.close()
                await browser.close()
                return

        await _browser_login_save_and_verify(5, id, status_queue, account_id,
                                              page, context, browser)
