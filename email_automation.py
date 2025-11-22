# -*- coding: utf-8 -*-
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Tuple

from config import config
from logger import job_logger


# ---------------------------
# Helper: Multiline title parsing (wie in tasks.py)
# ---------------------------

_COMPANY_HINT_RE = re.compile(
    r"\b(ag|gmbh|sa|s\.a\.|kg|sarl|s\u00e0rl|sarl\.?|ltd|inc|llc)\b",
    re.IGNORECASE,
)

_LABEL_RE = re.compile(
    r"(arbeitsort|pensum|vertragsart|einfach bewerben|neu)",
    re.IGNORECASE,
)

_RELDATE_INLINE_RE = re.compile(
    r"\b(heute|gestern|vorgestern|letzte woche|letzten monat|vor \d+\s*(tagen|wochen|monaten?))\b",
    re.IGNORECASE,
)

_CITY_HINT_RE = re.compile(
    r"\b("
    r"z\u00fcrich|zurich|zuerich|"
    r"b\u00fclach|buelach|"
    r"kloten|winterthur|baden|zug|aarau|basel|bern|luzern|thun|"
    r"gen\u00e8ve|geneve|"
    r"schweiz"
    r")\b",
    re.IGNORECASE,
)


def _normalize_line(l: str) -> str:
    # entfernt z.B. '01. [exact]' am Zeilenanfang
    l = re.sub(r"^\s*\d+\.\s*\[[^\]]+\]\s*", "", l)
    return l.strip().strip('"').strip()


def _is_noise_line(l: str) -> bool:
    if not l:
        return True
    if _LABEL_RE.search(l):
        return True
    if re.match(r"^ref[:\s]", l, re.IGNORECASE):
        return True
    if _RELDATE_INLINE_RE.search(l):
        return True
    return False


def _extract_from_multiline_title(raw_title: str) -> Tuple[str, str, str]:
    """
    Robustere Heuristik:
    - title enthaelt oft: Zeit, Jobtitel, Labels, Ort, Firma.
    - Filtert Labels/relative Zeiten (auch inline).
    - Jobtitel = erste non-noise Zeile.
    - Firma = letzte non-noise Zeile mit Rechtsform-Hint, sonst letzte non-noise Zeile.
    - Ort = Zeile nach "Arbeitsort:" falls vorhanden, sonst erste non-noise Zeile mit City-Hint.
    """
    raw_lines = [_normalize_line(x) for x in (raw_title or "").splitlines()]
    raw_lines = [x for x in raw_lines if x]

    # location: explizit nach "Arbeitsort"
    location = ""
    for i, l in enumerate(raw_lines):
        if l.lower().startswith("arbeitsort"):
            if i + 1 < len(raw_lines):
                location = _normalize_line(raw_lines[i + 1])
            break

    clean = [l for l in raw_lines if not _is_noise_line(l)]

    job_title = clean[0] if clean else ""
    company = ""

    # Firma: letzte Zeile mit Rechtsform-Hint
    for l in reversed(clean):
        if _COMPANY_HINT_RE.search(l):
            company = l
            break

    # fallback: letzte clean Zeile (wenn nicht schon job_title)
    if not company and len(clean) >= 2:
        company = clean[-1]
        if company == job_title:
            company = ""

    # fallback location via city hint
    if not location:
        for l in clean[1:]:
            if _CITY_HINT_RE.search(l):
                location = l
                break

    if location == company:
        location = ""

    return job_title, company, location


def _job_to_dict(job: Any) -> Dict[str, Any]:
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
    ]:
        if hasattr(job, k):
            out[k] = getattr(job, k)

    if hasattr(job, "__dict__"):
        for k, v in job.__dict__.items():
            out.setdefault(k, v)

    return out


def _escape(val: Any) -> str:
    s = str(val or "")
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _normalize_job(job: Any) -> Dict[str, Any]:
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

    needs_parse = (
        ("\n" in raw_title)
        or ("arbeitsort" in raw_title.lower())
        or (not company)
        or (not location)
    )
    if needs_parse and raw_title:
        t2, c2, l2 = _extract_from_multiline_title(raw_title)
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
    }


class EmailAutomation:
    def __init__(self):
        self.smtp_server = config.SMTP_SERVER
        self.smtp_port = config.SMTP_PORT
        self.sender_email = config.SENDER_EMAIL
        self.sender_password = config.SENDER_PASSWORD
        self.recipient_emails = config.RECIPIENT_EMAILS

    def send_job_alert(self, new_jobs):
        """Send alert for new job opportunities."""
        if not new_jobs:
            return False
        if not getattr(config, "EMAIL_NOTIFICATIONS_ENABLED", True):
            return False

        subject = f"Neue Job-M\u00f6glichkeiten gefunden ({len(new_jobs)} Stellen)"
        body = self._create_job_alert_body(new_jobs)

        return self._send_email(subject, body)

    def send_weekly_summary(self, stats):
        """Send weekly summary of job search activities."""
        if not getattr(config, "EMAIL_NOTIFICATIONS_ENABLED", True):
            return False
        if not getattr(config, "WEEKLY_SUMMARY_ENABLED", True):
            return False
        subject = f"W\u00f6chentliche Job-Suche Zusammenfassung - {datetime.now().strftime('%W/%Y')}"
        body = self._create_weekly_summary_body(stats)

        return self._send_email(subject, body)

    def send_error_notification(self, error_type, error_message, traceback=None):
        """Send notification for critical errors."""
        if not getattr(config, "EMAIL_NOTIFICATIONS_ENABLED", True):
            return False
        if not getattr(config, "ERROR_NOTIFICATIONS_ENABLED", True):
            return False
        subject = f"Job-Finder Fehler: {error_type}"
        body = self._create_error_body(error_type, error_message, traceback)

        return self._send_email(subject, body, priority="high")

    def _create_job_alert_body(self, jobs):
        jobs_norm = [_normalize_job(j) for j in jobs]

        max_jobs = int(getattr(config, "EMAIL_MAX_JOBS", 200) or 200)
        shown = jobs_norm[:max_jobs]

        items_html = ""
        for job in shown:
            meta_parts: List[str] = []
            if job["date"]:
                meta_parts.append(job["date"])
            if job["source"]:
                meta_parts.append(job["source"])
            if job["match"]:
                meta_parts.append(job["match"])
            if job["score"] != "":
                meta_parts.append(f"Score {job['score']}")

            meta_html = f"<small>{_escape(' | '.join(meta_parts))}</small><br>" if meta_parts else ""

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

        if len(jobs_norm) > max_jobs:
            items_html += (
                f"<li>... und {len(jobs_norm) - max_jobs} weitere Stellen "
                f"(nicht angezeigt wegen Mengenlimit)</li>"
            )

        body = f"""
        <html>
        <body>
            <h2>Neue Job-M\u00f6glichkeiten gefunden!</h2>
            <p>Es wurden {len(jobs_norm)} neue Stellen gefunden, die Ihren Kriterien entsprechen:</p>
            <ul>
                {items_html}
            </ul>
            <p><em>Diese E-Mail wurde automatisch vom Bua's Job-Finder generiert.</em></p>
        </body>
        </html>
        """

        return body

    def _create_weekly_summary_body(self, stats):
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


# Global email instance
email_automation = EmailAutomation()
