import logging
import logging.handlers
import os

from .config import config


class JobFinderLogger:
    # Zentraler Logger mit Datei- und Konsolenhandlern.
    def __init__(self) -> None:
        # Basis-Logger konfigurieren.
        self.logger = logging.getLogger("JobFinder")
        self.logger.setLevel(
            getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)
        )

        # Log-Verzeichnis sicherstellen.
        os.makedirs("logs", exist_ok=True)

        # File-Handler mit Rotation.
        log_filename = f"logs/{config.LOG_FILE}"
        file_handler = logging.handlers.RotatingFileHandler(
            log_filename,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
        )

        # Console-Handler.
        console_handler = logging.StreamHandler()

        # Einheitliches Format fuer alle Handler.
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - "
            "%(funcName)s:%(lineno)d - %(message)s"
        )

        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        # Doppelte Handler bei Re-Import vermeiden.
        if not self.logger.handlers:
            self.logger.addHandler(file_handler)
            self.logger.addHandler(console_handler)

    def get_logger(self) -> logging.Logger:
        # Zugriff auf den konfigurierten Logger.
        return self.logger

    def log_job_search_start(self, keywords, locations) -> None:
        # Start-Event fuer die Jobsuche loggen.
        self.logger.info(
            f"Starting job search - Keywords: {keywords}, Locations: {locations}"
        )

    def log_job_search_end(self, job_count: int) -> None:
        # Abschluss-Event mit Trefferanzahl loggen.
        self.logger.info(
            f"Job search completed - Found {job_count} jobs"
        )

    def log_job_application(
        self, job_title: str, company: str, status: str = "success"
    ) -> None:
        # Bewerbungsergebnis je nach Status loggen.
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
        # Fehler mit optionaler Exception loggen.
        if exception:
            self.logger.error(
                f"{error_type}: {message} - Exception: {exception}"
            )
        else:
            self.logger.error(f"{error_type}: {message}")

    def log_scheduling_event(self, event_type: str, details: str) -> None:
        # Scheduler-Events protokollieren.
        self.logger.info(f"Scheduling Event - {event_type}: {details}")

    def log_email_sent(
        self, recipient: str, subject: str, status: str = "success"
    ) -> None:
        # E-Mail Versandstatus protokollieren.
        if status == "success":
            self.logger.info(
                f"Email sent successfully to {recipient} - Subject: {subject}"
            )
        else:
            self.logger.error(
                f"Failed to send email to {recipient} - "
                f"Subject: {subject} - {status}"
            )


# Globaler Logger fuer das Projekt.
job_logger = JobFinderLogger().get_logger()
