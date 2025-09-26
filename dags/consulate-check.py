import datetime

import requests
import undetected_chromedriver as uc
from rich.console import Console
from selenium import webdriver
from selenium.webdriver.common.by import By

# Constants
BASE_URL = "https://prenotami.esteri.it"
# PROXY = "http://154.208.10.126:80"
SERVICE_ID = 494
EMAIL = "williampmarzella@gmail.com"
PASSWORD = "tFs6csPNfE^#as"
WEBHOOK_URL = "https://eae4922a-7bb0-4800-8c94-e5a4cb1cc9ca.trayapp.io"
LOGO = "Starting..."
SLEEP_TIME = 8


# Setup browser options
def setup_browser():
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--allow-insecure-localhost")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36"
    )
    options.add_argument("--ignore-certificate-errors")
    return uc.Chrome(options=options)


# Post message to webhook
def post_to_webhook(message):
    data = {"message": message}
    try:
        response = requests.post(WEBHOOK_URL, json=data)
        response.raise_for_status()
        console.log("Successfully posted to webhook.", style="green")
    except requests.exceptions.RequestException as e:
        console.log(f"Failed to post to webhook: {e}", style="red")


# Login function
def login(browser):
    console.print("[green]Logging in...")
    # browser.get(f"{BASE_URL}/Home")
    browser.find_element(By.ID, "login-email").send_keys(EMAIL)
    browser.find_element(By.ID, "login-password").send_keys(PASSWORD)
    browser.find_element(By.XPATH, "//form[@id='login-form']/button").click()
    if browser.current_url == f"{BASE_URL}/UserArea":
        console.log("Login successful!", style="bold green")
        return True
    elif f"{BASE_URL}/Home/Login" in browser.current_url:
        console.log("Rate limit exceeded.", style="bold red")
        return False
    return False


# Check appointments
def check_appointments(browser):
    console.print("[green]Checking for appointments...")
    browser.get(f"{BASE_URL}/Services/Booking/{SERVICE_ID}")
    if browser.current_url != f"{BASE_URL}/Services":
        post_to_webhook("Appointment available!")
        console.log("Appointment available!", style="green")
        return True
    return False


# Main function
def open_browser_and_check_appointments():
    console.print(LOGO, style="green")
    browser = setup_browser()
    browser.implicitly_wait(SLEEP_TIME)
    browser.get(f"{BASE_URL}/UserArea")
    body_content = browser.find_element(By.TAG_NAME, "body").text
    if body_content == "Unavailable":
        browser.get(f"{BASE_URL}/Home")
    if not login(browser):
        console.log("Failed to login", style="red")
    else:
        # After successful login, check the current URL and proceed if it's correct
        if browser.current_url == f"{BASE_URL}/UserArea":
            if not check_appointments(browser):
                console.log("Appointment not available.", style="red")
        else:
            console.log("Unexpected URL after login", style="red")

    console.print("Exiting...", style="green")
    browser.quit()


if __name__ == "__main__":
    console = Console()
    open_browser_and_check_appointments()
    with open("backup.log", "a") as backup_file:
        backup_file.write(
            f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - "
            "Consulate checks done\n"
        )
