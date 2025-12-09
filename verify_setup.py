import os
import sys
import importlib.util
from pathlib import Path

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
    if not os.path.exists(".env"):
        print("MISSING: .env file")
        return False
    
    # Load .env manually to check keys
    env_vars = {}
    with open(".env", "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                env_vars[key.strip()] = val.strip()
    
    required_keys = [
        "SENDER_EMAIL", "SENDER_PASSWORD", "SMTP_SERVER", "SMTP_PORT",
        "RECIPIENT_EMAILS", "GROQ_API_KEY", "SEARCH_LOCATIONS",
        "SEARCH_KEYWORDS", "LOCATION_RADIUS_KM"
    ]
    
    missing_keys = [k for k in required_keys if k not in env_vars]
    if missing_keys:
        print(f"MISSING ENV VARS: {', '.join(missing_keys)}")
        return False
    
    print(".env file present and contains basic keys.")
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
