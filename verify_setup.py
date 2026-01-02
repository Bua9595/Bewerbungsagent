import sys
import importlib.util
from pathlib import Path
from dotenv import load_dotenv, dotenv_values

ENV_PATH = Path(".env")
REQUIRED_ENV_KEYS = [
    "SENDER_EMAIL",
    "SENDER_PASSWORD",
    "SMTP_SERVER",
    "SMTP_PORT",
    "RECIPIENT_EMAILS",
    "SEARCH_LOCATIONS",
    "LOCATION_RADIUS_KM",
]

def check_python_version():
    print(f"Python version: {sys.version}")
    if sys.version_info < (3, 11):
        print("WARNING: Python 3.11+ is recommended.")
        return False
    return True

def check_imports():
    required_modules = [
        "selenium", "webdriver_manager", "schedule", "dotenv", 
        "groq", "pandas", "openpyxl", "requests", "pytest", "flake8"
    ]
    missing = []
    for module in required_modules:
        if importlib.util.find_spec(module) is None:
            missing.append(module)
    
    if missing:
        print(f"MISSING MODULES: {', '.join(missing)}")
        return False
    print("All required modules found.")
    return True

def check_env_file():
    if not ENV_PATH.exists():
        print("MISSING: .env file")
        return False

    load_dotenv(ENV_PATH)
    env_vars = dotenv_values(ENV_PATH)

    missing_keys = [k for k in REQUIRED_ENV_KEYS if not env_vars.get(k)]
    if missing_keys:
        print(f"MISSING ENV VARS ({len(missing_keys)}): {', '.join(missing_keys)}")
        return False

    print(".env file present and contains required keys.")
    return True

def main():
    print("=== SETUP VERIFICATION ===")
    checks = [
        check_python_version(),
        check_imports(),
        check_env_file()
    ]
    
    if all(checks):
        print("\nSUCCESS: Setup looks good!")
        sys.exit(0)
    else:
        print("\nFAILURE: Some checks failed.")
        sys.exit(1)

if __name__ == "__main__":
    main()
