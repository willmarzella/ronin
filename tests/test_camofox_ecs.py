#!/usr/bin/env python3
"""ECS feasibility test for camofox-browser integration.

Tests that ronin's search and apply pipeline could work from an ECS cluster
in Australia using camofox-browser for anti-detection browser automation.

Usage:
    # With a running camofox-browser server:
    python tests/test_camofox_ecs.py

    # With custom server URL:
    CAMOFOX_URL=http://camofox:9377 python tests/test_camofox_ecs.py

    # Dry run (no camofox server needed, tests import/config only):
    python tests/test_camofox_ecs.py --dry-run

This validates:
1. Module imports and adapter construction
2. Config-based browser mode switching
3. Camofox REST API connectivity (if server available)
4. Seek.com.au page loading through camofox (if server available)
5. Accessibility snapshot parsing for form detection
6. Search layer works without browser (HTTP only)
"""

import os
import sys
import time

# Ensure project root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def print_result(name: str, passed: bool, detail: str = ""):
    """Print a test result."""
    status = "PASS" if passed else "FAIL"
    icon = "+" if passed else "x"
    line = f"  [{icon}] {name}: {status}"
    if detail:
        line += f" -- {detail}"
    print(line)
    return passed


def test_imports() -> bool:
    """Test that all camofox modules import correctly."""
    try:
        from ronin.applier.camofox import (  # noqa: F401
            CamofoxBrowserDriver,
            CamofoxDriver,
            CamofoxElement,
            CamofoxNoSuchElementException,
            CamofoxTimeoutException,
        )

        return print_result("Module imports", True)
    except ImportError as e:
        return print_result("Module imports", False, str(e))


def test_adapter_construction() -> bool:
    """Test that CamofoxDriver can be constructed without a server."""
    try:
        from ronin.applier.camofox import CamofoxDriver

        driver = CamofoxDriver(camofox_url="http://localhost:9377")
        assert driver.camofox_url == "http://localhost:9377"
        assert driver.driver is None
        assert driver.is_logged_in is False
        return print_result("Adapter construction", True)
    except Exception as e:
        return print_result("Adapter construction", False, str(e))


def test_env_override() -> bool:
    """Test that CAMOFOX_URL env var is respected."""
    try:
        from ronin.applier.camofox import CamofoxDriver

        old_val = os.environ.get("CAMOFOX_URL")
        os.environ["CAMOFOX_URL"] = "http://test-host:9999"
        try:
            driver = CamofoxDriver()
            assert driver.camofox_url == "http://test-host:9999"
        finally:
            if old_val:
                os.environ["CAMOFOX_URL"] = old_val
            else:
                del os.environ["CAMOFOX_URL"]

        return print_result("Env var override", True)
    except Exception as e:
        return print_result("Env var override", False, str(e))


def test_browser_mode_factory() -> bool:
    """Test that get_browser_driver returns correct type based on mode."""
    try:
        from ronin.applier.base import get_browser_driver
        from ronin.applier.browser import ChromeDriver
        from ronin.applier.camofox import CamofoxDriver

        # Test camofox mode via env var
        old_mode = os.environ.get("BROWSER_MODE")
        os.environ["BROWSER_MODE"] = "camofox"
        try:
            driver = get_browser_driver()
            assert isinstance(
                driver, CamofoxDriver
            ), f"Expected CamofoxDriver, got {type(driver)}"
        finally:
            if old_mode:
                os.environ["BROWSER_MODE"] = old_mode
            else:
                del os.environ["BROWSER_MODE"]

        # Test system mode (default)
        old_mode = os.environ.get("BROWSER_MODE")
        os.environ["BROWSER_MODE"] = "system"
        try:
            driver = get_browser_driver()
            assert isinstance(
                driver, ChromeDriver
            ), f"Expected ChromeDriver, got {type(driver)}"
        finally:
            if old_mode:
                os.environ["BROWSER_MODE"] = old_mode
            else:
                del os.environ["BROWSER_MODE"]

        return print_result("Browser mode factory", True)
    except Exception as e:
        return print_result("Browser mode factory", False, str(e))


def test_element_mock() -> bool:
    """Test that CamofoxElement provides the Selenium-compatible interface."""
    try:
        from ronin.applier.camofox import CamofoxBrowserDriver, CamofoxElement

        # Create a mock driver (won't connect to server)
        mock_driver = CamofoxBrowserDriver.__new__(CamofoxBrowserDriver)

        elem = CamofoxElement(
            driver=mock_driver,
            ref="e1",
            attrs={
                "tag": "input",
                "type": "text",
                "id": "test-input",
                "name": "firstName",
                "text": "",
                "data-testid": "first-name-input",
            },
        )

        assert elem.tag_name == "input"
        assert elem.get_attribute("id") == "test-input"
        assert elem.get_attribute("name") == "firstName"
        assert elem.get_attribute("data-testid") == "first-name-input"
        assert elem.is_displayed() is True
        assert elem.is_selected() is False
        assert elem.is_enabled() is True

        return print_result("Element interface", True)
    except Exception as e:
        return print_result("Element interface", False, str(e))


def test_css_selector_matching() -> bool:
    """Test CSS selector matching logic."""
    try:
        from ronin.applier.camofox import CamofoxBrowserDriver

        driver = CamofoxBrowserDriver.__new__(CamofoxBrowserDriver)

        # Test attribute selector
        attrs = {"tag": "input", "data-testid": "continue-button", "id": "btn1"}
        assert (
            driver._match_css_selector(attrs, "[data-testid='continue-button']") is True
        )
        assert driver._match_css_selector(attrs, "[data-testid='wrong']") is False
        assert driver._match_css_selector(attrs, "#btn1") is True
        assert driver._match_css_selector(attrs, "#wrong") is False

        # Test tag + attribute
        assert (
            driver._match_css_selector(attrs, "input[data-testid='continue-button']")
            is True
        )
        assert (
            driver._match_css_selector(attrs, "button[data-testid='continue-button']")
            is False
        )

        return print_result("CSS selector matching", True)
    except Exception as e:
        return print_result("CSS selector matching", False, str(e))


def test_search_layer_no_browser() -> bool:
    """Test that the search layer works without any browser (pure HTTP)."""
    try:
        from ronin.scraper.seek import SeekScraper

        config = {
            "search": {
                "keywords": ['"software engineer"'],
                "location": "Victoria-VIC",
                "date_range": 1,
                "salary": {"min": 0, "max": 400000},
            },
            "scraping": {
                "delay_seconds": 1,
                "timeout_seconds": 10,
                "quick_apply_only": True,
            },
        }

        scraper = SeekScraper(config)
        url = scraper.build_search_url(1)
        assert "seek.com.au" in url
        assert "software" in url.lower() or "%22software" in url.lower()

        return print_result("Search layer (no browser)", True, f"URL: {url[:80]}...")
    except Exception as e:
        return print_result("Search layer (no browser)", False, str(e))


def test_camofox_health(camofox_url: str) -> bool:
    """Test connectivity to camofox-browser server."""
    try:
        from ronin.applier.camofox import CamofoxBrowserDriver

        driver = CamofoxBrowserDriver(base_url=camofox_url)
        healthy = driver.health_check()

        return print_result(
            "Camofox health check",
            healthy,
            f"Server at {camofox_url}" if healthy else f"Cannot reach {camofox_url}",
        )
    except Exception as e:
        return print_result("Camofox health check", False, str(e))


def test_seek_page_load(camofox_url: str) -> bool:
    """Test loading Seek.com.au through camofox and getting a snapshot."""
    try:
        from ronin.applier.camofox import CamofoxBrowserDriver

        driver = CamofoxBrowserDriver(base_url=camofox_url)

        # Create tab with Seek
        tab_id = driver.create_tab("https://www.seek.com.au")
        assert tab_id is not None

        # Wait for page to load
        time.sleep(5)

        # Get snapshot
        snapshot = driver._get_snapshot(force=True)
        assert snapshot is not None

        page_text = driver.page_source.lower()
        has_content = any(
            kw in page_text for kw in ["seek", "jobs", "search", "sign in", "find"]
        )

        # Clean up
        driver.close_tab()

        return print_result(
            "Seek.com.au page load",
            has_content,
            f"Snapshot size: {len(page_text)} chars, "
            f"elements: {len(driver._snapshot_elements)}",
        )
    except Exception as e:
        return print_result("Seek.com.au page load", False, str(e))


def test_seek_job_page(camofox_url: str) -> bool:
    """Test loading a Seek job page and detecting form elements."""
    try:
        from ronin.applier.camofox import CamofoxBrowserDriver

        driver = CamofoxBrowserDriver(base_url=camofox_url)

        # Load a search results page
        driver.create_tab(
            "https://www.seek.com.au/software-engineer-jobs/in-Melbourne-VIC"
        )
        time.sleep(5)

        driver._get_snapshot(force=True)
        page_text = driver.page_source.lower()

        has_jobs = "job" in page_text or "software" in page_text
        element_count = len(driver._snapshot_elements)

        driver.close_tab()

        return print_result(
            "Seek job search page",
            has_jobs,
            f"Elements: {element_count}, has_jobs: {has_jobs}",
        )
    except Exception as e:
        return print_result("Seek job search page", False, str(e))


def test_proxy_compatibility() -> bool:
    """Test that proxy config works with both scraper and camofox."""
    try:
        # Test proxy config is picked up
        config = {
            "search": {"keywords": []},
            "scraping": {
                "delay_seconds": 1,
                "timeout_seconds": 10,
                "quick_apply_only": True,
            },
            "proxy": {
                "enabled": True,
                "http_url": "http://au-proxy.example.com:8080",
                "https_url": "https://au-proxy.example.com:8080",
            },
        }

        # BaseScraper is abstract, but we can check proxy config parsing
        # through a concrete subclass
        from ronin.scraper.seek import SeekScraper

        scraper = SeekScraper(config)
        proxies = scraper.session.proxies

        assert "http" in proxies or "https" in proxies

        return print_result(
            "Proxy compatibility", True, f"Proxies: {list(proxies.keys())}"
        )
    except Exception as e:
        return print_result("Proxy compatibility", False, str(e))


def main():
    """Run all ECS feasibility tests."""
    dry_run = "--dry-run" in sys.argv
    camofox_url = os.environ.get("CAMOFOX_URL", "http://localhost:9377")

    print("=" * 60)
    print("Ronin ECS Feasibility Test (camofox-browser)")
    print("=" * 60)
    print(f"  Camofox URL: {camofox_url}")
    print(f"  Dry run: {dry_run}")
    print()

    results = []

    # -- Tests that don't need a server --
    print("--- Offline Tests (no server needed) ---")
    results.append(test_imports())
    results.append(test_adapter_construction())
    results.append(test_env_override())
    results.append(test_browser_mode_factory())
    results.append(test_element_mock())
    results.append(test_css_selector_matching())
    results.append(test_search_layer_no_browser())
    results.append(test_proxy_compatibility())
    print()

    # -- Tests that need a running camofox server --
    if not dry_run:
        print("--- Online Tests (camofox server required) ---")
        server_ok = test_camofox_health(camofox_url)
        results.append(server_ok)

        if server_ok:
            results.append(test_seek_page_load(camofox_url))
            results.append(test_seek_job_page(camofox_url))
        else:
            print("  [!] Skipping browser tests (server unreachable)")
            print(f"      Start camofox-browser at {camofox_url} to run these tests")
    else:
        print("--- Online Tests: SKIPPED (dry run) ---")

    print()
    print("=" * 60)
    passed = sum(1 for r in results if r)
    total = len(results)
    print(f"Results: {passed}/{total} passed")

    if passed == total:
        print("ECS feasibility: VIABLE")
    elif passed >= total - 2:
        print("ECS feasibility: LIKELY VIABLE (some online tests skipped/failed)")
    else:
        print("ECS feasibility: ISSUES FOUND")

    print()
    print("--- Architecture Notes for ECS Deployment ---")
    print("1. SEARCH: Works as-is (pure HTTP/requests). No browser needed.")
    print("   Consider Australian residential proxy for IP reputation.")
    print()
    print("2. APPLY: Requires camofox-browser sidecar container in ECS task.")
    print("   - Run camofox-browser as a sidecar: port 9377")
    print("   - Set BROWSER_MODE=camofox and CAMOFOX_URL=http://localhost:9377")
    print("   - Login: Pre-load Seek session cookies (no interactive login)")
    print("   - Proxy: Route camofox through AU residential proxy for IP rep")
    print()
    print("3. ECS TASK DEFINITION:")
    print("   containers:")
    print("     - name: ronin")
    print("       image: ronin:latest")
    print("       env: BROWSER_MODE=camofox, CAMOFOX_URL=http://localhost:9377")
    print("     - name: camofox")
    print("       image: camofox-browser:latest")
    print("       ports: 9377")
    print()
    print("4. LIMITATIONS:")
    print("   - Selenium JS execution (execute_script) has limited camofox support")
    print(
        "   - Form extraction via JS (html_formatter.py)"
        " needs accessibility tree adapter"
    )
    print("   - Interactive Seek login won't work; need cookie-based auth")
    print("   - CSS selector matching is approximate (accessibility tree != DOM)")

    sys.exit(0 if passed >= total - 2 else 1)


if __name__ == "__main__":
    main()
