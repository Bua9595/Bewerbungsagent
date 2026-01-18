from config import config
from direkt_job_finder import DirectJobFinder
from email_automation import EmailAutomation


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
