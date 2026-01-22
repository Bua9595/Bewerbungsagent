import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bewerbungsagent.config import config
from bewerbungsagent.email_automation import EmailAutomation
from scripts.direkt_job_finder import DirectJobFinder


def main() -> None:
    print("Sender", config.SENDER_EMAIL)
    print("SMTP", config.SMTP_SERVER, config.SMTP_PORT)
    print("Recipients", config.RECIPIENT_EMAILS)
    print("validate", config.validate_config())

    EmailAutomation()  # init check
    print("Email ready")

    f = DirectJobFinder()
    f.save_application_templates()
    f.create_job_tracking_sheet()
    print("OK")


if __name__ == "__main__":
    main()
