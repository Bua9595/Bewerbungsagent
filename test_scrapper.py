# test_scraper.py - Minimaler Test
from selenium import webdriver
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service

service = Service(ChromeDriverManager().install())
driver = webdriver.Chrome(service=service)
driver.get("https://www.jobscout24.ch")
print("✅ Selenium funktioniert!")
driver.quit()