from __future__ import annotations

from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.service import Service

from taobao_autobuy.config import BrowserConfig


def _parse_window_size(window_size: str) -> tuple[int, int]:
    try:
        width_text, height_text = window_size.split(",", 1)
        return int(width_text), int(height_text)
    except Exception as exc:
        raise ValueError("browser.window_size 必须类似 1440,900") from exc


def create_driver(config: BrowserConfig, *, headless: bool | None = None) -> webdriver.Chrome:
    use_headless = config.headless if headless is None else headless

    config.user_data_dir.mkdir(parents=True, exist_ok=True)

    options = webdriver.ChromeOptions()
    options.add_argument(f"--user-data-dir={config.user_data_dir}")
    options.add_argument(f"--profile-directory={config.profile_directory}")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    width, height = _parse_window_size(config.window_size)
    options.add_argument(f"--window-size={width},{height}")

    if use_headless:
        options.add_argument("--headless=new")

    if config.detach and not use_headless:
        options.add_experimental_option("detach", True)

    if config.chrome_binary:
        options.binary_location = config.chrome_binary

    service = Service(config.driver_path) if config.driver_path else Service()
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(config.page_load_timeout)

    if not use_headless:
        try:
            driver.maximize_window()
        except Exception:
            driver.set_window_size(width, height)

    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": """
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    });
                """
            },
        )
    except Exception:
        pass

    return driver
