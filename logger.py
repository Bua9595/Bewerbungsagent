import logging
import logging.handlers
from datetime import datetime
import os
from config import config

class JobFinderLogger:
    def __init__(self):
        self.logger = logging.getLogger('JobFinder')
        self.logger.setLevel(getattr(logging, config.LOG_LEVEL.upper(), logging.INFO))

        # Create logs directory if it doesn't exist
        os.makedirs('logs', exist_ok=True)

        # File handler with rotation
        log_filename = f"logs/{config.LOG_FILE}"
        file_handler = logging.handlers.RotatingFileHandler(
            log_filename,
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5
        )

        # Console handler
        console_handler = logging.StreamHandler()

        # Formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
        )

        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)

    def get_logger(self):
        return self.logger

    def log_job_search_start(self, keywords, locations):
        self.logger.info(f"Starting job search - Keywords: {keywords}, Locations: {locations}")

    def log_job_search_end(self, job_count):
        self.logger.info(f"Job search completed - Found {job_count} jobs")

    def log_job_application(self, job_title, company, status="success"):
        if status == "success":
            self.logger.info(f"Successfully applied to: {job_title} at {company}")
        else:
            self.logger.error(f"Failed to apply to: {job_title} at {company} - {status}")

    def log_error(self, error_type, message, exception=None):
        if exception:
            self.logger.error(f"{error_type}: {message} - Exception: {str(exception)}")
        else:
            self.logger.error(f"{error_type}: {message}")

    def log_scheduling_event(self, event_type, details):
        self.logger.info(f"Scheduling Event - {event_type}: {details}")

    def log_email_sent(self, recipient, subject, status="success"):
        if status == "success":
            self.logger.info(f"Email sent successfully to {recipient} - Subject: {subject}")
        else:
            self.logger.error(f"Failed to send email to {recipient} - Subject: {subject} - {status}")

# Global logger instance
job_logger = JobFinderLogger().get_logger()
