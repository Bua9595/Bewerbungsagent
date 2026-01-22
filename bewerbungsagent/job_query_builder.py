from urllib.parse import quote_plus


def build_search_urls(config):
    """Compose curated job portal search URLs from config preferences.

    Returns a dict: {description: url}
    """
    locations = getattr(config, "SEARCH_LOCATIONS", ["Zuerich"]) or ["Zuerich"]
    try:
        radius = int(getattr(config, "LOCATION_RADIUS_KM", 25) or 25)
    except (TypeError, ValueError):
        radius = 25

    base_keywords = getattr(config, "SEARCH_KEYWORDS", ["IT Support"]) or ["IT Support"]
    variants = (getattr(config, "TITLE_VARIANTS_DE", []) or []) + (
        getattr(config, "TITLE_VARIANTS_EN", []) or []
    )
    neg = getattr(config, "NEGATIVE_KEYWORDS", []) or []

    def or_join(items):
        cleaned = [i.strip() for i in items if isinstance(i, str) and i.strip()]
        return " OR ".join([f'"{i}"' if " " in i else i for i in cleaned])

    def minus_join(items):
        cleaned = [i.strip() for i in items if isinstance(i, str) and i.strip()]
        # Negative Keywords dürfen keine Quotes brauchen – wir nutzen simple -token
        return " ".join([f"-{i}" for i in cleaned])

    # bewusst limitiert: zu lange Queries werden von Portalen schlechter verarbeitet
    pos_query = or_join((base_keywords + variants)[:8])
    neg_query = minus_join(neg)

    primary_kw = base_keywords[0].strip() if base_keywords else "IT Support"
    primary_loc = locations[0].strip() if locations else "Zuerich"

    # LinkedIn
    li_loc = quote_plus(f"{primary_loc}, Schweiz")
    li_q = quote_plus(f"{pos_query} {neg_query}".strip())
    linkedin = (
        f"https://www.linkedin.com/jobs/search/?keywords={li_q}"
        f"&location={li_loc}&distance={radius}&f_E=2"
    )

    # Indeed CH (stabil: nur 1 Keyword)
    indeed_q = quote_plus(primary_kw)
    indeed_l = quote_plus(primary_loc)
    indeed = (
        f"https://ch.indeed.com/jobs?q={indeed_q}&l={indeed_l}"
        f"&radius={radius}&fromage=7"
    )

    # jobs.ch
    jobsch_term = quote_plus(primary_kw)
    jobsch_loc = quote_plus(primary_loc)
    jobsch = f"https://www.jobs.ch/de/stellenangebote/?term={jobsch_term}&location={jobsch_loc}"

    # JobScout24
    js24_term = quote_plus(primary_kw)
    js24_place = quote_plus(primary_loc)
    jobscout24 = f"https://www.jobscout24.ch/de/jobs/?term={js24_term}&place={js24_place}"

    # Talent.com
    talent_q = quote_plus(primary_kw)
    talent_l = quote_plus(primary_loc)
    talent = f"https://ch.talent.com/de/jobs?k={talent_q}&l={talent_l}"

    # jobup.ch (stabil: term + location)
    jobup = f"https://www.jobup.ch/de/jobs/?term={jobsch_term}&location={jobsch_loc}"

    # Personalvermittler
    yellowshark = f"https://yellowshark.com/de/jobs?what={jobsch_term}&where={jobsch_loc}&distance={radius}"
    adecco = f"https://www.adecco.ch/de-ch/jobs?k={jobsch_term}&l={jobsch_loc}&distance={radius}"

    # Extra-Adapter Quellen (Requests-basiert)
    jobwinner = f"https://www.jobwinner.ch/jobs/?q={quote_plus(primary_kw)}&l={quote_plus(primary_loc)}"
    careerjet = f"https://www.careerjet.ch/suchen/stellenangebote?s={quote_plus(primary_kw)}&l={quote_plus(primary_loc)}"
    jobrapido = f"https://ch.jobrapido.com/?w={quote_plus(primary_kw)}&l={quote_plus(primary_loc)}"
    monster = f"https://www.monster.ch/jobs/suche/?q={quote_plus(primary_kw)}&where={quote_plus(primary_loc)}"
    jora = f"https://ch.jora.com/j?q={quote_plus(primary_kw)}&l={quote_plus(primary_loc)}"
    jooble = f"https://ch.jooble.org/SearchResult?ukw={quote_plus(primary_kw)}&rgns={quote_plus(primary_loc)}"

    return {
        "LinkedIn • Entry-Level IT": linkedin,
        "Indeed • Junior/1st Level": indeed,
        "jobs.ch • IT Support": jobsch,
        "JobScout24 • IT Support": jobscout24,
        "Talent.com • IT Support": talent,
        "jobup.ch • IT Support": jobup,
        "yellowshark • IT Support": yellowshark,
        "Adecco • IT Support": adecco,
        "JobWinner • Aggregator": jobwinner,
        "Careerjet • Aggregator": careerjet,
        "Jobrapido • Aggregator": jobrapido,
        "Monster • Jobs": monster,
        "Jora • Aggregator": jora,
        "Jooble • Aggregator": jooble,
    }
