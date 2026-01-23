# -*- coding: utf-8 -*-
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import os
from datetime import datetime
from typing import Any, Dict, List

from .config import config
from .logger import job_logger
from .job_text_utils import extract_from_multiline_title


def _job_to_dict(job: Any) -> Dict[str, Any]:
    # Job-Objekt robust in Dict normalisieren.
    """Normalize JobRow/Job dataclass oder dict -> dict mit Standardkeys."""
    if isinstance(job, dict):
        return dict(job)

    out: Dict[str, Any] = {}
    for k in [
        "title",
        "job_title",
        "position",
        "raw_title",
        "title_raw",
        "full_title",
        "company",
        "employer",
        "location",
        "city",
        "link",
        "url",
        "apply_url",
        "applyLink",
        "source",
        "portal",
        "origin",
        "match",
        "label",
        "score",
        "date",
        "date_found",
        "job_uid",
        "uid",
    ]:
        if hasattr(job, k):
            out[k] = getattr(job, k)

    if hasattr(job, "__dict__"):
        for k, v in job.__dict__.items():
            out.setdefault(k, v)

    return out


def _escape(val: Any) -> str:
    # HTML-escaping fuer Texte.
    s = str(val or "")
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _normalize_job(job: Any) -> Dict[str, Any]:
    # Felder fuer Mail-Ausgabe vereinheitlichen.
    data = _job_to_dict(job)

    raw_title = (
        data.get("raw_title")
        or data.get("title_raw")
        or data.get("full_title")
        or data.get("title")
        or data.get("job_title")
        or data.get("position")
        or ""
    ).strip()
    job_title = (data.get("job_title") or data.get("position") or "").strip()
    company = (data.get("company") or data.get("employer") or "").strip()
    location = (data.get("location") or data.get("city") or "").strip()
    source = (data.get("source") or data.get("portal") or data.get("origin") or "").strip()
    link = (data.get("link") or data.get("url") or data.get("apply_url") or data.get("applyLink") or "").strip()
    match = (data.get("match") or data.get("label") or "").strip()
    score = data.get("score")
    score_display = "" if score is None or score == "" else score
    date = (data.get("date") or data.get("date_found") or "").strip()
    job_uid = (data.get("job_uid") or data.get("uid") or "").strip()

    needs_parse = (
        ("\n" in raw_title)
        or ("arbeitsort" in raw_title.lower())
        or (not company)
        or (not location)
    )
    if needs_parse and raw_title:
        t2, c2, l2 = extract_from_multiline_title(raw_title)
        if not job_title and t2:
            job_title = t2
        if not company and c2:
            company = c2
        if not location and l2:
            location = l2

    if not job_title:
        job_title = raw_title or "Titel unbekannt"
    if not company:
        company = "Firma unbekannt"
    if not location:
        location = "Ort unbekannt"

    return {
        "job_title": job_title,
        "company": company,
        "location": location,
        "link": link,
        "source": source,
        "match": match,
        "score": score_display,
        "date": date,
        "job_uid": job_uid,
    }


class EmailAutomation:
    def __init__(self):
        # SMTP- und Empfaenger-Config laden.
        self.smtp_server = config.SMTP_SERVER
        self.smtp_port = config.SMTP_PORT
        self.sender_email = config.SENDER_EMAIL
        self.sender_password = config.SENDER_PASSWORD
        self.recipient_emails = config.RECIPIENT_EMAILS

    def send_job_alert(self, new_jobs, reminder_jobs=None):
        # Job-Alert-Mail (neu + Reminder) senden.
        """Send alert for new job opportunities and reminders."""
        reminder_jobs = reminder_jobs or []
        if not new_jobs and not reminder_jobs:
            return False
        if not getattr(config, "EMAIL_NOTIFICATIONS_ENABLED", True):
            return False

        subject = (
            "Job-Alert: "
            f"{len(new_jobs)} neu, {len(reminder_jobs)} offen"
        )
        body = self._create_job_alert_body(new_jobs, reminder_jobs)

        sent = self._send_email(subject, body)
        self._send_whatsapp_summary(new_jobs, reminder_jobs)
        return sent

    def send_weekly_summary(self, stats):
        # Woechentliche Statistik-Mail.
        """Send weekly summary of job search activities."""
        if not getattr(config, "EMAIL_NOTIFICATIONS_ENABLED", True):
            return False
        if not getattr(config, "WEEKLY_SUMMARY_ENABLED", True):
            return False
        subject = f"W\u00f6chentliche Job-Suche Zusammenfassung - {datetime.now().strftime('%W/%Y')}"
        body = self._create_weekly_summary_body(stats)

        return self._send_email(subject, body)

    def send_error_notification(self, error_type, error_message, traceback=None):
        # Fehlermeldung per Mail senden.
        """Send notification for critical errors."""
        if not getattr(config, "EMAIL_NOTIFICATIONS_ENABLED", True):
            return False
        if not getattr(config, "ERROR_NOTIFICATIONS_ENABLED", True):
            return False
        subject = f"Job-Finder Fehler: {error_type}"
        body = self._create_error_body(error_type, error_message, traceback)

        return self._send_email(subject, body, priority="high")

    def _create_job_alert_body(self, new_jobs, reminder_jobs):
        # HTML-Body fuer Job-Alert bauen.
        new_norm = [_normalize_job(j) for j in new_jobs]
        reminder_norm = [_normalize_job(j) for j in reminder_jobs]

        max_jobs = int(getattr(config, "EMAIL_MAX_JOBS", 200) or 200)

        # Render-Helfer fuer HTML-Liste.
        def _render_items(items):
            items_html = ""
            for job in items:
                meta_parts: List[str] = []
                if job["job_uid"]:
                    meta_parts.append(f"ID {job['job_uid']}")
                if job["date"]:
                    meta_parts.append(job["date"])
                if job["source"]:
                    meta_parts.append(job["source"])
                if job["match"]:
                    meta_parts.append(job["match"])
                if job["score"] != "":
                    meta_parts.append(f"Score {job['score']}")

                meta_html = (
                    f"<small>{_escape(' | '.join(meta_parts))}</small><br>"
                    if meta_parts
                    else ""
                )

                link_target = _escape(job["link"]) if job["link"] else "#"
                link_label = "Bewerben" if job["link"] else "Kein Link vorhanden"

                items_html += f"""
                    <li>
                        <strong>{_escape(job["job_title"])}</strong> bei {_escape(job["company"])}<br>
                        <em>{_escape(job["location"])}</em><br>
                        {meta_html}
                        <a href="{link_target}">{link_label}</a>
                    </li>
                """
            return items_html

        total = len(new_norm) + len(reminder_norm)
        shown_new = new_norm
        shown_reminder = reminder_norm

        if total > max_jobs:
            if len(new_norm) >= max_jobs:
                shown_new = new_norm[:max_jobs]
                shown_reminder = []
            else:
                remaining = max_jobs - len(new_norm)
                shown_reminder = reminder_norm[:remaining]

        new_html = _render_items(shown_new)
        reminder_html = _render_items(shown_reminder)

        truncated = max(total - max_jobs, 0)
        truncated_note = (
            f"<p>... und {truncated} weitere Stellen "
            f"(nicht angezeigt wegen Mengenlimit)</p>"
            if truncated
            else ""
        )

        body = f"""
        <html>
        <body>
            <h2>Job-Alert</h2>
            <p>Neu: {len(new_norm)} | Offen: {len(reminder_norm)}</p>
            <h3>NEW</h3>
            <ul>
                {new_html or "<li>Keine neuen Jobs.</li>"}
            </ul>
            <h3>OPEN REMINDERS</h3>
            <ul>
                {reminder_html or "<li>Keine offenen Erinnerungen.</li>"}
            </ul>
            {truncated_note}
            <p><em>Diese E-Mail wurde automatisch vom Job-Finder generiert.</em></p>
        </body>
        </html>
        """

        return body

    def _create_weekly_summary_body(self, stats):
        # HTML-Body fuer Wochenzusammenfassung.
        body = f"""
        <html>
        <body>
            <h2>W\u00f6chentliche Job-Suche Zusammenfassung</h2>
            <p>Hier ist Ihre w\u00f6chentliche \u00dcbersicht der Job-Suche Aktivit\u00e4ten:</p>
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
        # HTML-Body fuer Fehlermeldung.
        body = f"""
        <html>
        <body>
            <h2 style=\"color: red;\">Kritischer Fehler im Job-Finder</h2>
            <p><strong>Fehlertyp:</strong> {error_type}</p>
            <p><strong>Nachricht:</strong> {error_message}</p>
        """

        if traceback:
            body += f"""
            <p><strong>Traceback:</strong></p>
            <pre style=\"background-color: #f5f5f5; padding: 10px; border: 1px solid #ccc;\">{traceback}</pre>
            """

        body += """
            <p>Bitte \u00fcberpr\u00fcfen Sie die Logs f\u00fcr weitere Details.</p>
            <p><em>Diese E-Mail wurde automatisch vom Job-Finder generiert.</em></p>
        </body>
        </html>
        """
        return body

    def _send_email(self, subject, body, priority="normal", attachment=None):
        # SMTP-Versand mit optionalem Attachment.
        """Send email with optional attachment."""
        if not getattr(config, "EMAIL_NOTIFICATIONS_ENABLED", True):
            job_logger.info("Email sending skipped: disabled via EMAIL_NOTIFICATIONS_ENABLED")
            return False
        try:
            msg = MIMEMultipart()
            msg["From"] = self.sender_email
            msg["To"] = ", ".join(self.recipient_emails)
            msg["Subject"] = subject

            if priority == "high":
                msg["X-Priority"] = "1"
                msg["X-MSMail-Priority"] = "High"

            msg.attach(MIMEText(body, "html", "utf-8"))

            if attachment and os.path.exists(attachment):
                with open(attachment, "rb") as f:
                    part = MIMEBase("application", "octet-stream")
                    part.set_payload(f.read())
                    encoders.encode_base64(part)
                    part.add_header(
                        "Content-Disposition",
                        f"attachment; filename={os.path.basename(attachment)}",
                    )
                    msg.attach(part)

            server = smtplib.SMTP(self.smtp_server, self.smtp_port)
            server.starttls()
            server.login(self.sender_email, self.sender_password)
            server.sendmail(self.sender_email, self.recipient_emails, msg.as_string())
            server.quit()

            job_logger.info(f"Email sent successfully: {subject}")
            return True

        except Exception as e:
            job_logger.error(f"Failed to send email: {subject} - Error: {str(e)}")
            return False

    def _send_whatsapp_summary(self, new_jobs, reminder_jobs) -> None:
        # Kurze WhatsApp-Zusammenfassung senden (optional).
        try:
            from .notifier_whatsapp import send_whatsapp
        except Exception as e:
            job_logger.warning(f"WhatsApp init fehlgeschlagen: {e}")
            return

        summary = f"Job-Alert: {len(new_jobs)} neu, {len(reminder_jobs)} offen"
        lines = [summary]
        for job in (new_jobs or [])[:3]:
            data = _normalize_job(job)
            lines.append(
                f"- {data['job_title']} @ {data['company']} ({data['location']})"
            )
        try:
            send_whatsapp("\n".join(lines))
        except Exception as e:
            job_logger.warning(f"WhatsApp Versand fehlgeschlagen: {e}")


# Globale Email-Automation Instanz.
email_automation = EmailAutomation()
