from urllib.parse import quote_plus


def build_search_urls(config):
    """Compose curated job portal search URLs from config preferences.

    Returns a dict: {description: url}
    """
    locations = getattr(config, 'SEARCH_LOCATIONS', ["Zuerich"]) or ["Zuerich"]
    radius = getattr(config, 'LOCATION_RADIUS_KM', 25)
    base_keywords = getattr(config, 'SEARCH_KEYWORDS', ["IT Support"]) or ["IT Support"]
    variants = (getattr(config, 'TITLE_VARIANTS_DE', []) + getattr(config, 'TITLE_VARIANTS_EN', []))
    neg = getattr(config, 'NEGATIVE_KEYWORDS', [])

    def or_join(items):
        return " OR ".join([f'"{i}"' if " " in i else i for i in items])

    def minus_join(items):
        return " ".join([f'-{i}' for i in items])

    pos_query = or_join(base_keywords + variants[:6])
    neg_query = minus_join(neg)

    # LinkedIn
    li_loc = quote_plus(f"{locations[0]}, Schweiz")
    li_q = quote_plus(f"{pos_query} {neg_query}")
    linkedin = (
        f"https://www.linkedin.com/jobs/search/?keywords={li_q}&location={li_loc}&distance={radius}&f_E=2"
    )

    # Indeed CH (vereinfachte Query: nur erstes Keyword, ohne Negatives)
    indeed_q = quote_plus(base_keywords[0])
    indeed_l = quote_plus(locations[0])
    indeed = f"https://ch.indeed.com/jobs?q={indeed_q}&l={indeed_l}&radius={radius}&fromage=7"

    # jobs.ch
    jobsch_term = quote_plus(base_keywords[0])
    jobsch_loc = quote_plus(locations[0])
    jobsch = f"https://www.jobs.ch/de/stellenangebote/?term={jobsch_term}&location={jobsch_loc}"

    # JobScout24
    js24_term = quote_plus(base_keywords[0])
    js24_place = quote_plus(locations[0])
    jobscout24 = f"https://www.jobscout24.ch/de/jobs/?term={js24_term}&place={js24_place}"

    # Talent.com
    talent_q = quote_plus(base_keywords[0])
    talent_l = quote_plus(locations[0])
    talent = f"https://ch.talent.com/de/jobs?k={talent_q}&l={talent_l}"

    # jobup.ch (nutzt term statt keywords stabiler)
    jobup = f"https://www.jobup.ch/de/jobs/?term={jobsch_term}&location={jobsch_loc}"

    # Personalvermittler
    yellowshark = f"https://yellowshark.com/de/jobs?what={jobsch_term}&where={jobsch_loc}&distance={radius}"
    adecco = f"https://www.adecco.ch/de-ch/jobs?k={jobsch_term}&l={jobsch_loc}&distance={radius}"

    return {
        "LinkedIn • Entry-Level IT": linkedin,
        "Indeed • Junior/1st Level": indeed,
        "jobs.ch • IT Support": jobsch,
        "JobScout24 • IT Support": jobscout24,
        "Talent.com • IT Support": talent,
        "jobup.ch • IT Support": jobup,
        "yellowshark • IT Support": yellowshark,
        "Adecco • IT Support": adecco,
    }
