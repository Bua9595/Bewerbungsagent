import logging
import logging.handlers
import os

from .config import config


class JobFinderLogger:
    def __init__(self) -> None:
        self.logger = logging.getLogger("JobFinder")
        self.logger.setLevel(
            getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)
        )

        # Create logs directory if it doesn't exist
        os.makedirs("logs", exist_ok=True)

        # File handler with rotation
        log_filename = f"logs/{config.LOG_FILE}"
        file_handler = logging.handlers.RotatingFileHandler(
            log_filename,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
        )

        # Console handler
        console_handler = logging.StreamHandler()

        # Formatter
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - "
            "%(funcName)s:%(lineno)d - %(message)s"
        )

        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        # Avoid duplicate handlers on re-import
        if not self.logger.handlers:
            self.logger.addHandler(file_handler)
            self.logger.addHandler(console_handler)

    def get_logger(self) -> logging.Logger:
        return self.logger

    def log_job_search_start(self, keywords, locations) -> None:
        self.logger.info(
            f"Starting job search - Keywords: {keywords}, Locations: {locations}"
        )

    def log_job_search_end(self, job_count: int) -> None:
        self.logger.info(
            f"Job search completed - Found {job_count} jobs"
        )

    def log_job_application(
        self, job_title: str, company: str, status: str = "success"
    ) -> None:
        if status == "success":
            self.logger.info(
                f"Successfully applied to: {job_title} at {company}"
            )
        else:
            self.logger.error(
                f"Failed to apply to: {job_title} at {company} - {status}"
            )

    def log_error(
        self, error_type: str, message: str, exception: Exception | None = None
    ) -> None:
        if exception:
            self.logger.error(
                f"{error_type}: {message} - Exception: {exception}"
            )
        else:
            self.logger.error(f"{error_type}: {message}")

    def log_scheduling_event(self, event_type: str, details: str) -> None:
        self.logger.info(f"Scheduling Event - {event_type}: {details}")

    def log_email_sent(
        self, recipient: str, subject: str, status: str = "success"
    ) -> None:
        if status == "success":
            self.logger.info(
                f"Email sent successfully to {recipient} - Subject: {subject}"
            )
        else:
            self.logger.error(
                f"Failed to send email to {recipient} - "
                f"Subject: {subject} - {status}"
            )


# Global logger instance
job_logger = JobFinderLogger().get_logger()
