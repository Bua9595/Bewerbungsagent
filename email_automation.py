import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import os
from datetime import datetime
from config import config
from logger import job_logger


class EmailAutomation:
    def __init__(self):
        self.smtp_server = config.SMTP_SERVER
        self.smtp_port = config.SMTP_PORT
        self.sender_email = config.SENDER_EMAIL
        self.sender_password = config.SENDER_PASSWORD
        self.recipient_emails = config.RECIPIENT_EMAILS

    def send_job_alert(self, new_jobs):
        """Send alert for new job opportunities"""
        if not new_jobs:
            return
        if not getattr(config, "EMAIL_NOTIFICATIONS_ENABLED", True):
            return False

        subject = f"Neue Job-Möglichkeiten gefunden ({len(new_jobs)} Stellen)"
        body = self._create_job_alert_body(new_jobs)

        return self._send_email(subject, body)

    def send_weekly_summary(self, stats):
        """Send weekly summary of job search activities"""
        if not getattr(config, "EMAIL_NOTIFICATIONS_ENABLED", True):
            return False
        if not getattr(config, "WEEKLY_SUMMARY_ENABLED", True):
            return False
        subject = f"Wöchentliche Job-Suche Zusammenfassung - {datetime.now().strftime('%W/%Y')}"
        body = self._create_weekly_summary_body(stats)

        return self._send_email(subject, body)

    def send_error_notification(self, error_type, error_message, traceback=None):
        """Send notification for critical errors"""
        if not getattr(config, "EMAIL_NOTIFICATIONS_ENABLED", True):
            return False
        if not getattr(config, "ERROR_NOTIFICATIONS_ENABLED", True):
            return False
        subject = f"Job-Finder Fehler: {error_type}"
        body = self._create_error_body(error_type, error_message, traceback)

        return self._send_email(subject, body, priority="high")

    def _create_job_alert_body(self, jobs):
        body = f"""
        <html>
        <body>
            <h2>Neue Job-Möglichkeiten gefunden!</h2>
            <p>Es wurden {len(jobs)} neue Stellen gefunden, die Ihren Kriterien entsprechen:</p>
            <ul>
        """

        for job in jobs[:10]:  # Limit to 10 jobs in email
            body += f"""
                <li>
                    <strong>{job.get('title', 'N/A')}</strong> bei {job.get('company', 'N/A')}<br>
                    <em>{job.get('location', 'N/A')}</em><br>
                    <a href="{job.get('link', '#')}">Bewerben</a>
                </li>
            """

        if len(jobs) > 10:
            body += f"<li>... und {len(jobs) - 10} weitere Stellen</li>"

        body += """
            </ul>
            <p><em>Diese E-Mail wurde automatisch vom Job-Finder generiert.</em></p>
        </body>
        </html>
        """

        return body

    def _create_weekly_summary_body(self, stats):
        body = f"""
        <html>
        <body>
            <h2>Wöchentliche Job-Suche Zusammenfassung</h2>
            <p>Hier ist Ihre wöchentliche Übersicht der Job-Suche Aktivitäten:</p>
            <ul>
                <li><strong>Gesuchte Jobs:</strong> {stats.get('total_searched', 0)}</li>
                <li><strong>Neue Jobs gefunden:</strong> {stats.get('new_jobs', 0)}</li>
                <li><strong>Bewerbungen gesendet:</strong> {stats.get('applications_sent', 0)}</li>
                <li><strong>Fehler aufgetreten:</strong> {stats.get('errors', 0)}</li>
                <li><strong>Letzte Suche:</strong> {stats.get('last_search', 'N/A')}</li>
            </ul>
            <p><em>Diese E-Mail wurde automatisch vom Job-Finder generiert.</em></p>
        </body>
        </html>
        """

        return body

    def _create_error_body(self, error_type, error_message, traceback):
        body = f"""
        <html>
        <body>
            <h2 style="color: red;">Kritischer Fehler im Job-Finder</h2>
            <p><strong>Fehlertyp:</strong> {error_type}</p>
            <p><strong>Nachricht:</strong> {error_message}</p>
        """

        if traceback:
            body += f"""
            <p><strong>Traceback:</strong></p>
            <pre style="background-color: #f5f5f5; padding: 10px; border: 1px solid #ccc;">{traceback}</pre>
            """

        body += """
            <p>Bitte überprüfen Sie die Logs für weitere Details.</p>
            <p><em>Diese E-Mail wurde automatisch vom Job-Finder generiert.</em></p>
        </body>
        </html>
        """

        return body

    def _send_email(self, subject, body, priority="normal", attachment=None):
        """Send email with optional attachment"""
        if not getattr(config, "EMAIL_NOTIFICATIONS_ENABLED", True):
            job_logger.info("Email sending skipped: disabled via EMAIL_NOTIFICATIONS_ENABLED")
            return False
        try:
            msg = MIMEMultipart()
            msg['From'] = self.sender_email
            msg['To'] = ', '.join(self.recipient_emails)
            msg['Subject'] = subject

            if priority == "high":
                msg['X-Priority'] = '1'
                msg['X-MSMail-Priority'] = 'High'

            msg.attach(MIMEText(body, 'html', 'utf-8'))

            if attachment and os.path.exists(attachment):
                with open(attachment, 'rb') as f:
                    part = MIMEBase('application', 'octet-stream')
                    part.set_payload(f.read())
                    encoders.encode_base64(part)
                    part.add_header('Content-Disposition', f'attachment; filename={os.path.basename(attachment)}')
                    msg.attach(part)

            server = smtplib.SMTP(self.smtp_server, self.smtp_port)
            server.starttls()
            server.login(self.sender_email, self.sender_password)
            text = msg.as_string()
            server.sendmail(self.sender_email, self.recipient_emails, text)
            server.quit()

            job_logger.info(f"Email sent successfully: {subject}")
            return True

        except Exception as e:
            job_logger.error(f"Failed to send email: {subject} - Error: {str(e)}")
            return False


# Global email instance
email_automation = EmailAutomation()
