from config import config
print('Sender', config.SENDER_EMAIL)
print('SMTP', config.SMTP_SERVER, config.SMTP_PORT)
print('Recipients', config.RECIPIENT_EMAILS)
print('validate', config.validate_config())
from email_automation import EmailAutomation
e = EmailAutomation()
print('Email ready')
from direkt_job_finder import DirectJobFinder
f = DirectJobFinder()
f.save_application_templates()
f.create_job_tracking_sheet()
print('OK')
