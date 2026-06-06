import asyncio
import configparser
import os

from playwright.async_api import async_playwright
from xhs import XhsClient

from conf import BASE_DIR, LOCAL_CHROME_HEADLESS, LOCAL_CHROME_PATH
from utils.base_social_media import set_init_script
from utils.log import tencent_logger, kuaishou_logger, douyin_logger
from pathlib import Path
from uploader.xhs_uploader.main import sign_local


def get_browser_options():
    options = {
        "headless": LOCAL_CHROME_HEADLESS,
    }
    if LOCAL_CHROME_PATH:
        options["executable_path"] = LOCAL_CHROME_PATH
    return options


async def safe_goto(page, url):
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        if page.url == "about:blank":
            raise e


async def cookie_auth_douyin(account_file):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(**get_browser_options())
        try:
            context = await browser.new_context(storage_state=account_file)
            context = await set_init_script(context)
            page = await context.new_page()
            await safe_goto(page, "https://creator.douyin.com/creator-micro/content/upload")
            await page.wait_for_load_state("domcontentloaded", timeout=15000)
            await page.wait_for_timeout(3000)

            login_markers = [
                page.get_by_text("扫码登录", exact=True).first,
                page.get_by_text("手机号登录", exact=True).first,
                page.get_by_text("登录后即可", exact=False).first,
                page.get_by_role("img", name="二维码").first,
            ]
            for marker in login_markers:
                if not await marker.count():
                    continue
                try:
                    if await marker.is_visible():
                        douyin_logger.error("[+] cookie 失效，需要重新登录")
                        return False
                except Exception:
                    continue

            if page.url.startswith("https://creator.douyin.com/"):
                douyin_logger.success(f"[+] cookie 有效，当前页面: {page.url}")
                return True

            douyin_logger.error(f"[+] cookie 校验未进入创作者中心，当前页面: {page.url}")
            return False
        except Exception as exc:
            douyin_logger.error(f"[+] cookie 校验异常: {exc}")
            return False
        finally:
            try:
                await context.close()
            except Exception:
                pass
            await browser.close()


async def cookie_auth_tencent(account_file):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(**get_browser_options())
        context = await browser.new_context(storage_state=account_file)
        context = await set_init_script(context)
        # 创建一个新的页面
        page = await context.new_page()
        # 访问指定的 URL
        await safe_goto(page, "https://channels.weixin.qq.com/platform/post/create")
        try:
            await page.wait_for_selector('div.title-name:has-text("微信小店")', timeout=5000)  # 等待5秒
            tencent_logger.error("[+] 等待5秒 cookie 失效")
            await context.close()
            await browser.close()
            return False
        except:
            tencent_logger.success("[+] cookie 有效")
            await context.close()
            await browser.close()
            return True


async def cookie_auth_ks(account_file):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(**get_browser_options())
        context = await browser.new_context(storage_state=account_file)
        context = await set_init_script(context)
        # 创建一个新的页面
        page = await context.new_page()
        # 访问指定的 URL
        await safe_goto(page, "https://cp.kuaishou.com/article/publish/video")
        try:
            await page.wait_for_selector("div.names div.container div.name:text('机构服务')", timeout=5000)  # 等待5秒

            kuaishou_logger.info("[+] 等待5秒 cookie 失效")
            await context.close()
            await browser.close()
            return False
        except:
            kuaishou_logger.success("[+] cookie 有效")
            await context.close()
            await browser.close()
            return True


async def cookie_auth_xhs(account_file):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(**get_browser_options())
        context = await browser.new_context(storage_state=account_file)
        context = await set_init_script(context)
        # 创建一个新的页面
        page = await context.new_page()
        # 访问指定的 URL
        await safe_goto(page, "https://creator.xiaohongshu.com/creator-micro/content/upload")
        try:
            await page.wait_for_url("https://creator.xiaohongshu.com/creator-micro/content/upload", timeout=5000)
        except:
            print("[+] 等待5秒 cookie 失效")
            await context.close()
            await browser.close()
            return False
        # 2024.06.17 抖音创作者中心改版
        if await page.get_by_text('手机号登录').count() or await page.get_by_text('扫码登录').count():
            print("[+] 等待5秒 cookie 失效")
            await context.close()
            await browser.close()
            return False
        else:
            print("[+] cookie 有效")
            await context.close()
            await browser.close()
            return True


async def check_cookie(type, file_path):
    match type:
        # 小红书
        case 1:
            return await cookie_auth_xhs(Path(BASE_DIR / "cookiesFile" / file_path))
        # 视频号
        case 2:
            return await cookie_auth_tencent(Path(BASE_DIR / "cookiesFile" / file_path))
        # 抖音
        case 3:
            return await cookie_auth_douyin(Path(BASE_DIR / "cookiesFile" / file_path))
        # 快手
        case 4:
            return await cookie_auth_ks(Path(BASE_DIR / "cookiesFile" / file_path))
        case _:
            return False

# a = asyncio.run(check_cookie(1,"3a6cfdc0-3d51-11f0-8507-44e51723d63c.json"))
# print(a)
