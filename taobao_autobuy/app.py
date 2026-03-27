from __future__ import annotations

import datetime as dt
import logging
import time
from pathlib import Path

from selenium.common.exceptions import (
    ElementClickInterceptedException,
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from taobao_autobuy.browser import create_driver
from taobao_autobuy.config import AppConfig, ConfigError


class TaobaoAutoBuyer:
    def __init__(self, config: AppConfig, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger
        self.driver = None
        self.wait = None
        self.active_headless = False

    def now(self) -> dt.datetime:
        return dt.datetime.now(self.config.run.timezone)

    def now_str(self) -> str:
        return self.now().strftime("%Y-%m-%d %H:%M:%S")

    def seconds_until_buy_time(self) -> float:
        return (self.config.run.buy_time - self.now()).total_seconds()

    def start_driver(self, *, headless: bool | None = None) -> None:
        if self.driver is not None:
            return
        self.active_headless = self.config.browser.headless if headless is None else headless
        self.driver = create_driver(self.config.browser, headless=self.active_headless)
        self.wait = WebDriverWait(self.driver, 10)
        self.logger.info("Chrome 已启动，profile=%s", self.config.browser.user_data_dir)

    def stop_driver(self, *, force: bool = False) -> None:
        if self.driver is None:
            return
        if not force and self.config.output.leave_browser_open and not self.active_headless:
            self.logger.info("保留浏览器窗口，方便人工检查")
            return
        try:
            self.driver.quit()
        except Exception:
            pass
        finally:
            self.driver = None
            self.wait = None
            self.active_headless = False

    def open_url(self, url: str) -> None:
        assert self.driver is not None
        self.driver.get(url)

    def check_time(self) -> None:
        if self.seconds_until_buy_time() < 0:
            raise ConfigError(
                f"当前时间 {self.now_str()} 已经晚于 buy_time={self.config.run.buy_time_text}"
            )

    def switch_to_latest_window(self) -> bool:
        assert self.driver is not None
        handles = self.driver.window_handles
        if not handles:
            return False
        self.driver.switch_to.window(handles[-1])
        return True

    def close_possible_overlays(self) -> None:
        assert self.driver is not None
        xpath_candidates = [
            "//div[contains(@class,'close')]",
            "//span[contains(@class,'close')]",
            "//i[contains(@class,'close')]",
            "//*[text()='关闭']",
            "//*[text()='×']",
            "//*[text()='X']",
            "//*[contains(@aria-label,'关闭')]",
        ]

        for xp in xpath_candidates:
            try:
                elems = self.driver.find_elements(By.XPATH, xp)
            except Exception:
                continue

            for elem in elems:
                try:
                    if not elem.is_displayed():
                        continue
                except Exception:
                    continue

                if self.safe_click(elem, "关闭弹窗"):
                    time.sleep(0.5)
                    return

    def is_logged_in_current_page(self) -> bool:
        assert self.driver is not None
        try:
            self.close_possible_overlays()
            src = self.driver.page_source
        except Exception:
            return False

        if "亲，请登录" in src:
            return False
        return any(key in src for key in ("我的淘宝", "购物车", "已买到的宝贝"))

    def open_login_page(self) -> None:
        assert self.driver is not None and self.wait is not None
        self.open_url(self.config.taobao_home)
        time.sleep(2)
        self.close_possible_overlays()

        try:
            login_link = WebDriverWait(self.driver, 8).until(
                EC.presence_of_element_located((By.LINK_TEXT, "亲，请登录"))
            )
        except TimeoutException:
            self.logger.info("首页未找到“亲，请登录”，可能已经登录")
            return

        self.logger.info("未登录，准备点击登录按钮")
        old_handles = self.driver.window_handles[:]

        try:
            self.driver.execute_script(
                "arguments[0].scrollIntoView({block:'center'});", login_link
            )
            time.sleep(0.5)
            login_link.click()
        except ElementClickInterceptedException:
            self.close_possible_overlays()
            time.sleep(0.5)
            login_link = self.driver.find_element(By.LINK_TEXT, "亲，请登录")
            self.driver.execute_script("arguments[0].click();", login_link)
        except Exception:
            self.close_possible_overlays()
            time.sleep(0.5)
            login_link = self.driver.find_element(By.LINK_TEXT, "亲，请登录")
            self.driver.execute_script("arguments[0].click();", login_link)

        start = time.time()
        while time.time() - start < 10:
            handles = self.driver.window_handles
            if len(handles) > len(old_handles):
                self.switch_to_latest_window()
                break
            time.sleep(0.2)

        self.switch_to_latest_window()
        self.logger.info("请在当前浏览器窗口中扫码登录")

    def ensure_logged_in(self) -> None:
        assert self.driver is not None
        self.logger.info("开始检查登录状态")
        self.open_url(self.config.taobao_home)
        time.sleep(2)
        self.close_possible_overlays()

        if self.is_logged_in_current_page():
            self.logger.info("已处于登录状态")
            return

        if self.config.browser.headless:
            raise ConfigError(
                "当前是 headless 模式，但没有发现有效登录态。请先执行 `prepare-profile` 保存登录态。"
            )

        self.open_login_page()

        for retry in range(1, self.config.run.max_login_retry_times + 1):
            time.sleep(self.config.run.login_check_interval)
            self.switch_to_latest_window()
            self.close_possible_overlays()
            if self.is_logged_in_current_page():
                self.logger.info("登录成功: %s", self.now_str())
                return
            self.logger.info(
                "等待扫码登录中... 第 %s/%s 次检查",
                retry,
                self.config.run.max_login_retry_times,
            )

        raise RuntimeError("规定时间内没有扫码登录成功")

    def refresh_keep_alive(self) -> None:
        assert self.driver is not None
        self.switch_to_latest_window()
        self.open_url(self.config.taobao_cart)
        self.logger.info("[%s] 刷新购物车页面，防止登录超时", self.now_str())
        time.sleep(self.config.run.keep_alive_interval)

    def keep_login_and_wait(self) -> None:
        self.logger.info("开始保活，等待到达抢购时间")

        while True:
            remain_seconds = self.seconds_until_buy_time()
            if remain_seconds <= 0:
                self.logger.info("已到抢购时间，进入抢购阶段")
                return

            if self.config.cart.selection_mode == "manual":
                if remain_seconds > self.config.run.stop_refresh_before_seconds:
                    self.refresh_keep_alive()
                    continue

                self.switch_to_latest_window()
                self.open_url(self.config.taobao_cart)
                time.sleep(1)
                self.logger.info("已停止自动刷新，请手动勾选商品并确认结算按钮状态")
                return

            if remain_seconds > self.config.run.keep_alive_interval:
                self.refresh_keep_alive()
                continue

            self.switch_to_latest_window()
            self.open_url(self.config.taobao_cart)
            self.logger.info("已进入购物车页，等待抢购时间")
            while True:
                remain_seconds = self.seconds_until_buy_time()
                if remain_seconds <= 0:
                    self.logger.info("已到抢购时间，进入抢购阶段")
                    return
                time.sleep(min(1.0, max(remain_seconds / 2, 0.1)))

    def safe_click(self, elem: WebElement, name: str = "元素") -> bool:
        assert self.driver is not None
        try:
            self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", elem)
            time.sleep(0.2)
        except Exception:
            pass

        try:
            elem.click()
            self.logger.info("普通点击成功: %s", name)
            return True
        except Exception as exc:
            self.logger.info("普通点击失败: %s -> %s", name, exc)

        try:
            self.driver.execute_script("arguments[0].click();", elem)
            self.logger.info("JS 点击成功: %s", name)
            return True
        except Exception as exc:
            self.logger.info("JS 点击失败: %s -> %s", name, exc)

        try:
            self.driver.execute_script(
                """
                const ev = new MouseEvent('click', {
                    view: window,
                    bubbles: true,
                    cancelable: true
                });
                arguments[0].dispatchEvent(ev);
                """,
                elem,
            )
            self.logger.info("dispatchEvent 点击成功: %s", name)
            return True
        except Exception as exc:
            self.logger.info("dispatchEvent 点击失败: %s -> %s", name, exc)

        return False

    def get_visible_elements(self, xpaths: list[str]) -> list[WebElement]:
        assert self.driver is not None
        result: list[WebElement] = []
        for xp in xpaths:
            try:
                elems = self.driver.find_elements(By.XPATH, xp)
            except Exception:
                continue

            for elem in elems:
                try:
                    if elem.is_displayed():
                        result.append(elem)
                except StaleElementReferenceException:
                    continue
        return result

    def wait_cart_page_stable(self, timeout: int = 8) -> bool:
        assert self.driver is not None
        start = time.time()
        while time.time() - start < timeout:
            try:
                src = self.driver.page_source
                if ("结算" in src or "合计" in src) and "cart.taobao.com" in self.driver.current_url:
                    return True
            except Exception:
                pass
            time.sleep(0.3)
        return False

    def click_select_all(self) -> bool:
        xpaths = [
            "//*[@id='J_SelectAll1']",
            "//*[normalize-space(text())='全选']",
            "//label[normalize-space(.)='全选']",
            "//span[normalize-space(.)='全选']",
            "//div[normalize-space(.)='全选']",
        ]
        elems = self.get_visible_elements(xpaths)
        for elem in elems:
            text = ""
            try:
                text = elem.text.strip()
            except Exception:
                pass
            self.logger.info("找到全选候选元素: %r", text)
            if self.safe_click(elem, "全选"):
                return True
        self.logger.info("未能定位到购物车全选按钮")
        return False

    def ensure_cart_selected(self, *, first_attempt: bool, need_reselect_after_retry: bool) -> bool:
        if self.config.cart.selection_mode == "manual":
            if first_attempt:
                self.logger.info("人工模式：默认你已提前勾选商品，直接点结算")
            else:
                self.logger.info("人工模式：重试时不会自动勾选，请确认商品仍为勾选状态")
            return True

        if need_reselect_after_retry:
            self.logger.info("自动模式：失败后重新勾选购物车商品")
        else:
            self.logger.info("自动模式：准备自动勾选购物车商品")

        return self.click_select_all()

    def get_best_settlement_button(self) -> WebElement | None:
        assert self.driver is not None
        candidates = []
        xpaths = [
            "//button[contains(normalize-space(.), '结算')]",
            "//a[contains(normalize-space(.), '结算')]",
            "//span[contains(normalize-space(.), '结算')]",
            "//*[contains(normalize-space(text()), '结算(')]",
            "//*[contains(normalize-space(text()), '结算')]",
        ]

        for xp in xpaths:
            try:
                elems = self.driver.find_elements(By.XPATH, xp)
            except Exception:
                continue

            for elem in elems:
                try:
                    if not elem.is_displayed():
                        continue
                    text = elem.text.strip()
                    rect = elem.rect
                    tag = elem.tag_name
                except Exception:
                    continue

                if not text or "结算" not in text or len(text) > 30:
                    continue

                score = 0
                if rect.get("x", 0) > 900:
                    score += 10
                if rect.get("width", 0) > 80:
                    score += 3
                if rect.get("height", 0) > 30:
                    score += 2
                if tag in {"button", "a"}:
                    score += 5
                if "结算(" in text:
                    score += 5

                candidates.append((score, text, elem, rect, tag))

        candidates.sort(key=lambda item: item[0], reverse=True)
        for score, text, _, rect, tag in candidates[:10]:
            self.logger.info("结算候选 score=%s tag=%s text=%r rect=%s", score, tag, text, rect)
        return candidates[0][2] if candidates else None

    def click_settlement(self) -> bool:
        elem = self.get_best_settlement_button()
        if elem is None:
            self.logger.info("没有找到合适的结算按钮")
            return False
        return self.safe_click(elem, "结算主按钮")

    def wait_for_page_after_settlement(self, timeout: int = 10) -> str:
        assert self.driver is not None
        start = time.time()
        last_url = ""

        while time.time() - start < timeout:
            try:
                url = self.driver.current_url
                title = self.driver.title
                src = self.driver.page_source
            except Exception:
                time.sleep(0.3)
                continue

            if url != last_url:
                self.logger.info("等待结算跳转... url=%s title=%s", url, title)
                last_url = url

            if "confirm_order" in url or "确认订单" in title or "确认订单" in src:
                self.logger.info("已进入确认订单页")
                return "ok"
            if "TmallConfirmOrderError" in url or "系统繁忙" in src or "请稍候再试" in src:
                self.logger.info("检测到系统繁忙/错误页")
                return "error"
            time.sleep(0.3)

        try:
            if "cart.taobao.com" in self.driver.current_url:
                return "cart"
        except Exception:
            pass
        return "timeout"

    def get_best_submit_button(self) -> WebElement | None:
        assert self.driver is not None
        candidates = []
        xpaths = [
            "//button[contains(., '提交订单')]",
            "//a[contains(., '提交订单')]",
            "//span[contains(., '提交订单')]",
            "//div[contains(., '提交订单')]",
            "//*[contains(., '提交订单')]",
        ]

        for xp in xpaths:
            try:
                elems = self.driver.find_elements(By.XPATH, xp)
            except Exception:
                continue

            for elem in elems:
                try:
                    if not elem.is_displayed():
                        continue
                    text = elem.text.strip()
                    rect = elem.rect
                    tag = elem.tag_name
                    cls = elem.get_attribute("class") or ""
                except Exception:
                    continue

                if not text or "提交订单" not in text or len(text) > 40 or "返回" in text:
                    continue

                score = 0
                x = rect.get("x", 0)
                y = rect.get("y", 0)
                w = rect.get("width", 0)
                h = rect.get("height", 0)

                if x > 1200:
                    score += 20
                elif x > 1100:
                    score += 15
                elif x > 1000:
                    score += 10

                if y > 650:
                    score += 15
                elif y > 550:
                    score += 10

                if 180 <= w <= 420:
                    score += 10
                elif 120 <= w <= 500:
                    score += 5
                else:
                    score -= 5

                if 35 <= h <= 80:
                    score += 8
                if tag in {"button", "a"}:
                    score += 10
                if text.startswith("提交订单"):
                    score += 20
                if "¥" in text or "￥" in text:
                    score += 10
                if len(text) <= 20:
                    score += 10
                elif len(text) <= 30:
                    score += 5
                if "确认订单" in text:
                    score -= 40

                candidates.append((score, text, elem, rect, tag, cls))

        candidates.sort(key=lambda item: item[0], reverse=True)
        for score, text, _, rect, tag, cls in candidates[:10]:
            self.logger.info(
                "提交候选 score=%s tag=%s text=%r rect=%s class=%r",
                score,
                tag,
                text,
                rect,
                cls,
            )
        return candidates[0][2] if candidates else None

    def click_submit_order(self) -> bool:
        time.sleep(1)
        elem = self.get_best_submit_button()
        if elem is None:
            self.logger.info("没有找到合适的提交订单按钮")
            return False
        ok = self.safe_click(elem, "提交订单按钮")
        time.sleep(2)
        return ok

    def back_to_cart(self) -> bool:
        try:
            self.switch_to_latest_window()
            self.open_url(self.config.taobao_cart)
            time.sleep(1)
            return True
        except Exception:
            return False

    def capture_screenshot(self, tag: str) -> Path | None:
        if self.driver is None:
            return None
        self.config.output.screenshot_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{self.now().strftime('%Y%m%d-%H%M%S')}-{tag}.png"
        path = self.config.output.screenshot_dir / filename
        try:
            self.driver.save_screenshot(str(path))
            self.logger.info("已保存截图: %s", path)
            return path
        except Exception:
            return None

    def buy(self) -> None:
        assert self.driver is not None
        self.logger.info("进入抢购流程")
        self.switch_to_latest_window()
        self.open_url(self.config.taobao_cart)
        time.sleep(1)

        submit_success = False
        retry_submit_times = 0
        need_reselect_after_retry = False

        while True:
            if self.seconds_until_buy_time() < 0 and submit_success:
                self.logger.info("订单已提交成功，无需继续")
                return

            if self.seconds_until_buy_time() > 0:
                time.sleep(self.config.run.poll_interval_seconds)
                continue

            if retry_submit_times >= self.config.run.max_submit_retry_times:
                self.logger.info("重试抢购次数达到上限，停止重试")
                self.capture_screenshot("submit-retry-limit")
                return

            retry_submit_times += 1
            self.logger.info("[%s] 到达抢购时间，开始第 %s 次尝试", self.now_str(), retry_submit_times)

            try:
                self.switch_to_latest_window()

                if "cart.taobao.com" not in self.driver.current_url:
                    self.back_to_cart()

                if not self.wait_cart_page_stable(timeout=8):
                    self.logger.info("购物车页面未稳定，返回购物车后重试")
                    self.back_to_cart()
                    time.sleep(0.8)
                    need_reselect_after_retry = self.config.cart.auto_select_on_retry
                    continue

                if not self.ensure_cart_selected(
                    first_attempt=retry_submit_times == 1,
                    need_reselect_after_retry=need_reselect_after_retry,
                ):
                    self.logger.info("商品勾选失败，本轮跳过")
                    time.sleep(0.8)
                    self.back_to_cart()
                    need_reselect_after_retry = self.config.cart.auto_select_on_retry
                    continue

                if not self.click_settlement():
                    self.logger.info("本轮未能点击结算按钮")
                    time.sleep(0.8)
                    need_reselect_after_retry = self.config.cart.auto_select_on_retry
                    continue

                page_state = self.wait_for_page_after_settlement(timeout=10)

                if page_state == "ok":
                    if self.click_submit_order():
                        self.logger.info("订单提交流程已触发，请立刻检查页面并完成付款")
                        submit_success = True
                        self.capture_screenshot("submit-triggered")
                        return

                    self.logger.info("已到确认订单页，但未能点击提交订单按钮")
                    self.capture_screenshot("submit-button-missing")
                    time.sleep(0.8)
                    self.back_to_cart()
                    need_reselect_after_retry = self.config.cart.auto_select_on_retry
                    continue

                if page_state == "error":
                    self.logger.info("点击结算后进入系统繁忙/错误页，返回购物车重试")
                elif page_state == "cart":
                    self.logger.info("点击结算后仍停留在购物车页，返回重试")
                else:
                    self.logger.info("点击结算后页面状态超时，返回购物车重试")

                self.capture_screenshot(f"state-{page_state}")
                time.sleep(0.8)
                self.back_to_cart()
                need_reselect_after_retry = self.config.cart.auto_select_on_retry

            except WebDriverException as exc:
                self.logger.info("浏览器操作异常: %s", exc)
                self.capture_screenshot("webdriver-exception")
                time.sleep(1.0)
                self.back_to_cart()
                need_reselect_after_retry = self.config.cart.auto_select_on_retry

    def run(self, *, headless_override: bool | None = None) -> None:
        use_headless = self.config.browser.headless if headless_override is None else headless_override
        self.config.cart.validate(use_headless)
        self.start_driver(headless=use_headless)
        try:
            self.check_time()
            self.ensure_logged_in()
            self.keep_login_and_wait()
            self.buy()
        finally:
            if use_headless:
                self.stop_driver(force=True)
            else:
                self.stop_driver(force=False)

    def prepare_profile(self) -> None:
        self.start_driver(headless=False)
        try:
            self.logger.info("准备登录态目录: %s", self.config.browser.user_data_dir)
            self.open_url(self.config.taobao_home)
            time.sleep(2)
            self.close_possible_overlays()
            if not self.is_logged_in_current_page():
                self.open_login_page()
            self.logger.info("请在浏览器里完成淘宝登录。完成后回到终端按回车。")
            input()
            self.open_url(self.config.taobao_cart)
            time.sleep(2)
            self.logger.info("登录态已写入用户目录，下次可直接复用")
        finally:
            self.stop_driver(force=True)
